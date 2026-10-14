"""Synthetic HTTP/DNS fixtures; no clinic or other network request is made."""

import asyncio
import json

import httpcore2
import httpx2 as httpx
import pytest

from telescope_rag.core.settings import Settings
from telescope_rag.ingestion.collection import (
    CollectionError,
    CollectionLimits,
    CollectionManifest,
    PinnedPublicBackend,
    PinnedPublicTransport,
    canonical_url,
    collect,
)

ORIGIN = "https://telescopecenter.com"


async def public_dns(host):
    assert host in {"telescopecenter.com", "www.telescopecenter.com"}
    return ("93.184.216.34",)


def configuration(**values):
    return Settings(_env_file=None, app_env="test", crawl_delay_seconds=0, **values)


def html(value, status=200, **headers):
    return httpx.Response(status, text=value, headers={"content-type": "text/html", **headers})


def run_collection(
    tmp_path, routes, *, settings=None, limits=None, seeds=None, resolver=public_dns
):
    calls = []

    async def handler(request):
        assert request.method == "GET"
        assert "authorization" not in request.headers
        assert request.headers["accept-encoding"] == "identity"
        calls.append(str(request.url))
        response = routes.get(str(request.url))
        if response is None:
            return httpx.Response(404)
        if callable(response):
            return await response(request)
        return response

    result = asyncio.run(
        collect(
            settings or configuration(),
            tmp_path / "snapshot",
            "synthetic-snapshot",
            transport=httpx.MockTransport(handler),
            resolver=resolver,
            seeds=seeds or (ORIGIN + "/",),
            limits=limits,
        )
    )
    return result, calls


@pytest.mark.parametrize(
    "url",
    [
        "http://telescopecenter.com/",
        "https://evil.example/",
        "https://telescopecenter.com:444/",
        "https://user:secret@telescopecenter.com/",
        ORIGIN + "/?patient=secret",
        ORIGIN + "/patient-report/123",
        ORIGIN + "/request-medical-report/",
        ORIGIN + "/medical-request-report/",
        ORIGIN + "/testimonial/",
        ORIGIN + "/testimonials/",
        ORIGIN + "/suggestions-complaints/",
        ORIGIN + "/international-patients-form/",
        ORIGIN + "/book-appointment/",
        ORIGIN + "/wp-admin/admin-ajax.php",
        ORIGIN + "/%70atient-report/",
        ORIGIN + "/%252e%252e/",
        ORIGIN + "/%2e%2e/",
        ORIGIN + "/%5cadmin/",
        ORIGIN + "/%00admin/",
        ORIGIN + "/wp-admin;ignored/",
        ORIGIN + "/%FF/",
        ORIGIN + "/bad\npath",
        ORIGIN + "/bad\\path",
    ],
)
def test_unapproved_action_and_ambiguous_urls_rejected(url):
    with pytest.raises((CollectionError, ValueError)):
        canonical_url(url)


def test_canonicalization_preserves_language_name_case_and_slash():
    assert (
        canonical_url("/ar/الأطباء/#section", base=ORIGIN)
        == ORIGIN + "/ar/%D8%A7%D9%84%D8%A3%D8%B7%D8%A8%D8%A7%D8%A1/"
    )
    assert (
        canonical_url("https://www.telescopecenter.com:443/Doctors")
        == "https://www.telescopecenter.com/Doctors"
    )
    assert canonical_url(ORIGIN + "/doctors") != canonical_url(ORIGIN + "/doctors/")
    assert canonical_url(ORIGIN + "/contact-us/") == ORIGIN + "/contact-us/"


def test_immutable_snapshot_preserves_html_bytes_metadata_and_safe_discovery(tmp_path):
    content = (
        '<main><h1>الأطباء Doctors</h1><a href="/ar/doctors/">العربية</a>'
        '<a href="/doctors/">English</a><a href="/doctors/#top">again</a>'
        '<a href="/request-medical-report/?secret=hidden">report</a>'
        '<a href="https://evil.example/">external</a>'
        '<form><a href="/form-target/">do not follow</a></form></main>'
    )
    manifest, calls = run_collection(
        tmp_path,
        {
            ORIGIN + "/": html(content),
            ORIGIN + "/doctors/": html("<main>Dr Test — Orthopedics</main>"),
            ORIGIN + "/ar/doctors/": html("<main>طبيب تجريبي</main>"),
        },
    )
    assert len(manifest.pages) == 3
    assert manifest.approved is False
    assert manifest.coverage_complete
    assert ORIGIN + "/robots.txt" in calls
    assert ORIGIN + "/sitemap.xml" in calls
    assert not any("secret" in url or "evil" in url or "form-target" in url for url in calls)
    assert any(item.outcome == "duplicate" for item in manifest.records)
    page = next(page for page in manifest.pages if page.canonical_url == ORIGIN + "/")
    assert page.html == content
    assert (
        tmp_path / "snapshot" / "raw" / f"{page.document_id}.html"
    ).read_bytes() == content.encode()
    restored = CollectionManifest.model_validate_json(
        (tmp_path / "snapshot" / "manifest.json").read_text(encoding="utf-8")
    )
    assert restored == manifest
    serialized_records = json.dumps([record.model_dump(mode="json") for record in manifest.records])
    assert "hidden" not in serialized_records and "evil.example" not in serialized_records
    with pytest.raises(FileExistsError):
        asyncio.run(
            collect(
                configuration(),
                tmp_path / "snapshot",
                "again",
                transport=httpx.MockTransport(lambda request: pytest.fail("network")),
                resolver=public_dns,
            )
        )


def test_robots_denial_and_unavailable_fail_closed(tmp_path):
    manifest, calls = run_collection(
        tmp_path,
        {
            ORIGIN + "/robots.txt": httpx.Response(
                200, text="User-agent: *\nDisallow: /\n", headers={"content-type": "text/plain"}
            ),
            ORIGIN + "/": html("must not fetch"),
        },
    )
    assert calls == [ORIGIN + "/robots.txt"]
    assert not manifest.pages and "robots_disallowed_or_unavailable" in manifest.coverage_gaps
    unavailable, unavailable_calls = run_collection(
        tmp_path / "unavailable",
        {
            ORIGIN + "/robots.txt": httpx.Response(503),
            ORIGIN + "/": html("do not fetch"),
        },
    )
    assert unavailable_calls == [ORIGIN + "/robots.txt"]
    assert "robots_unavailable" in unavailable.coverage_gaps


@pytest.mark.parametrize(
    "rules, allowed",
    [
        ("Allow: /\nDisallow: /sensitive/", False),
        ("Disallow: /\nAllow: /sensitive/", True),
        ("Allow: /sensitive/\nDisallow: /sensitive/", True),
        ("Allow: /\nDisallow: /*sensitive", False),
        ("Allow: /\nDisallow: /%73ensitive/", False),
        ("Disallow: /sensitive/$", False),
    ],
)
def test_robots_longest_rule_and_unsupported_patterns_fail_closed(tmp_path, rules, allowed):
    manifest, calls = run_collection(
        tmp_path,
        {
            ORIGIN + "/robots.txt": httpx.Response(
                200, text="User-agent: *\n" + rules, headers={"content-type": "text/plain"}
            ),
            ORIGIN + "/sensitive/": html("<main>Public permitted fixture</main>"),
        },
        seeds=(ORIGIN + "/sensitive/",),
    )
    assert (ORIGIN + "/sensitive/" in calls) is allowed
    assert bool(manifest.pages) is allowed


def test_robots_bot_specific_group_overrides_star_group(tmp_path):
    manifest, calls = run_collection(
        tmp_path,
        {
            ORIGIN + "/robots.txt": httpx.Response(
                200,
                text=(
                    "User-agent: *\nDisallow: /\nUser-agent: TelescopePublicKnowledgeBot\nAllow: /"
                ),
                headers={"content-type": "text/plain"},
            ),
            ORIGIN + "/": html("<main>public</main>"),
        },
    )
    assert len(manifest.pages) == 1 and ORIGIN + "/" in calls


def test_permitted_sitemap_discovers_pages_and_records_failures(tmp_path):
    manifest, calls = run_collection(
        tmp_path,
        {
            ORIGIN + "/robots.txt": httpx.Response(
                200,
                text=f"User-agent: *\nDisallow: /private\nSitemap: {ORIGIN}/sitemap_index.xml",
                headers={"content-type": "text/plain"},
            ),
            ORIGIN + "/sitemap_index.xml": httpx.Response(
                200,
                text=f"<sitemapindex><sitemap><loc>{ORIGIN}/pages.xml</loc></sitemap></sitemapindex>",
                headers={"content-type": "application/xml"},
            ),
            ORIGIN + "/pages.xml": httpx.Response(
                200,
                text=f"<urlset><url><loc>{ORIGIN}/faqs/</loc></url><url><loc>{ORIGIN}/missing/</loc></url></urlset>",
                headers={"content-type": "application/xml"},
            ),
            ORIGIN + "/": html("<main>Home</main>"),
            ORIGIN + "/faqs/": html("<main>Friday hours shown as published.</main>"),
        },
    )
    assert ORIGIN + "/faqs/" in calls
    assert len(manifest.pages) == 2
    assert not manifest.coverage_complete
    missing = next(record for record in manifest.records if record.url == ORIGIN + "/missing/")
    assert missing.outcome == "failed" and missing.status_code == 404


def test_sitemap_entities_never_resolved(tmp_path):
    manifest, calls = run_collection(
        tmp_path,
        {
            ORIGIN + "/": html("<main>public</main>"),
            ORIGIN + "/sitemap.xml": httpx.Response(
                200,
                text='<!DOCTYPE urlset [<!ENTITY x SYSTEM "http://127.0.0.1/secret">]><urlset><url><loc>&x;</loc></url></urlset>',
                headers={"content-type": "application/xml"},
            ),
        },
    )
    assert any(record.code == "sitemap_entities_forbidden" for record in manifest.records)
    assert "sitemap_failure" in manifest.coverage_gaps
    assert all("127.0.0.1" not in url for url in calls)


@pytest.mark.parametrize(
    "target",
    [
        "http://telescopecenter.com/",
        "https://evil.example/",
        ORIGIN + "/request-medical-report/",
        ORIGIN + "/?patient=hidden",
    ],
)
def test_redirect_destination_checked_before_dispatch(tmp_path, target):
    manifest, calls = run_collection(
        tmp_path, {ORIGIN + "/": httpx.Response(302, headers={"location": target})}
    )
    assert calls == [ORIGIN + "/robots.txt", ORIGIN + "/", ORIGIN + "/sitemap.xml"]
    assert not manifest.pages
    assert any(record.outcome == "failed" for record in manifest.records)


def test_redirect_rechecks_new_host_robots_and_dns(tmp_path):
    www = "https://www.telescopecenter.com"
    manifest, calls = run_collection(
        tmp_path,
        {
            ORIGIN + "/": httpx.Response(302, headers={"location": www + "/"}),
            www + "/robots.txt": httpx.Response(
                200, text="User-agent: *\nDisallow: /", headers={"content-type": "text/plain"}
            ),
            www + "/": html("must not fetch"),
        },
    )
    assert www + "/robots.txt" in calls and www + "/" not in calls
    assert not manifest.pages


@pytest.mark.parametrize(
    "addresses",
    [
        ("127.0.0.1",),
        ("93.184.216.34", "10.0.0.1"),
        ("::1",),
        ("169.254.169.254",),
        ("224.0.0.1",),
        (),
        ("not-an-ip",),
    ],
)
def test_dns_all_answers_public_before_any_dispatch(tmp_path, addresses):
    async def resolver(host):
        return addresses

    manifest, calls = run_collection(tmp_path, {ORIGIN + "/": html("unsafe")}, resolver=resolver)
    assert calls == [] and not manifest.pages
    assert not manifest.coverage_complete


def test_backend_pins_numeric_ip_and_rejects_rebinding():
    calls, answers = [], iter([("93.184.216.34",), ("127.0.0.1",)])

    async def resolver(host):
        return next(answers)

    class Backend(httpcore2.AsyncNetworkBackend):
        async def connect_tcp(self, host, port, **kwargs):
            calls.append((host, port))
            return object()

    backend = PinnedPublicBackend(resolver, backend=Backend())

    async def scenario():
        await backend.connect_tcp("telescopecenter.com", 443)
        with pytest.raises(CollectionError, match="dns_non_public"):
            await backend.connect_tcp("telescopecenter.com", 443)
        with pytest.raises(CollectionError, match="unsafe_connection_target"):
            await backend.connect_tcp("evil.example", 443)
        with pytest.raises(CollectionError, match="unix_connections_forbidden"):
            await backend.connect_unix_socket("unsafe")

    asyncio.run(scenario())
    assert calls == [("93.184.216.34", 443)]


def test_pinned_transport_keeps_hostname_for_tls_and_host_header():
    async def scenario():
        transport = PinnedPublicTransport(public_dns)
        requests = []

        class Pool:
            async def handle_async_request(self, request):
                requests.append(request)
                return httpcore2.Response(
                    200, headers=[(b"content-type", b"text/html")], content=b"hello"
                )

            async def aclose(self):
                pass

        await transport.pool.aclose()
        transport.pool = Pool()
        async with httpx.AsyncClient(transport=transport) as client:
            response = await client.get(ORIGIN + "/")
            assert response.text == "hello"
            with pytest.raises(CollectionError, match="only_get_allowed"):
                await client.post(ORIGIN + "/")
        assert requests[0].url.host == b"telescopecenter.com"
        assert (b"Host", b"telescopecenter.com") in requests[0].headers or (
            b"host",
            b"telescopecenter.com",
        ) in requests[0].headers

    asyncio.run(scenario())


def test_actual_core_connection_pins_ip_and_uses_original_tls_hostname():
    connections, tls_names, writes = [], [], []

    class Stream(httpcore2.AsyncMockStream):
        async def start_tls(self, ssl_context, server_hostname=None, **kwargs):
            assert ssl_context.check_hostname is True
            tls_names.append(server_hostname)
            return self

        async def write(self, buffer, **kwargs):
            writes.append(buffer)

    class Backend(httpcore2.AsyncNetworkBackend):
        async def connect_tcp(self, host, port, **kwargs):
            connections.append((host, port))
            return Stream([b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nhello"])

    async def scenario():
        transport = PinnedPublicTransport(public_dns)
        await transport.pool.aclose()
        transport.pool = httpcore2.AsyncConnectionPool(
            network_backend=PinnedPublicBackend(public_dns, backend=Backend()),
            max_keepalive_connections=0,
            retries=0,
        )
        async with httpx.AsyncClient(transport=transport) as client:
            assert (await client.get(ORIGIN + "/")).text == "hello"
            assert (await client.get(ORIGIN + "/doctors/")).text == "hello"

    asyncio.run(scenario())
    assert connections == [("93.184.216.34", 443)] * 2
    assert tls_names == ["telescopecenter.com"] * 2
    assert b"Host: telescopecenter.com" in b"".join(writes)


@pytest.mark.parametrize(
    "settings, limits, gap",
    [
        (configuration(crawl_max_pages=1), None, "page_limit"),
        (configuration(crawl_max_depth=0), None, "depth_limit"),
        (configuration(), CollectionLimits(max_discoveries=1), "discovery_limit"),
        (configuration(), CollectionLimits(max_requests=1), "request_limit"),
    ],
)
def test_limits_record_coverage_gaps(tmp_path, settings, limits, gap):
    manifest, calls = run_collection(
        tmp_path,
        {
            ORIGIN + "/": html('<main><a href="/doctors/">doctors</a></main>'),
            ORIGIN + "/doctors/": html("<main>doctor</main>"),
        },
        settings=settings,
        limits=limits,
    )
    assert gap in manifest.coverage_gaps
    assert not manifest.coverage_complete


def test_repeated_navigation_counts_unique_urls_and_retains_occurrences(tmp_path):
    links = "".join(f'<a href="/doctors/#{index}">doctor</a>' for index in range(100))
    links += '<a href="/faqs/">FAQ</a>'
    manifest, calls = run_collection(
        tmp_path,
        {
            ORIGIN + "/": html("<main>" + links + "</main>"),
            ORIGIN + "/doctors/": html("<main>Doctor fixture</main>"),
            ORIGIN + "/faqs/": html("<main>FAQ fixture</main>"),
        },
        limits=CollectionLimits(max_discoveries=3),
    )
    assert len(manifest.pages) == 3
    assert manifest.coverage_complete and "discovery_limit" not in manifest.coverage_gaps
    duplicates = [record for record in manifest.records if record.outcome == "duplicate"]
    assert len(duplicates) == 99
    assert {record.source_url for record in duplicates} == {ORIGIN + "/"}
    assert [record.occurrence_index for record in duplicates] == list(range(1, 100))
    assert calls.count(ORIGIN + "/doctors/") == 1


def test_new_unique_url_overflow_is_deferred_without_dispatch(tmp_path):
    manifest, calls = run_collection(
        tmp_path,
        {
            ORIGIN + "/": html(
                '<main><a href="/doctors/">doctor</a><a href="/faqs/">FAQ</a></main>'
            ),
            ORIGIN + "/doctors/": html("<main>Doctor</main>"),
        },
        limits=CollectionLimits(max_discoveries=2),
    )
    assert "discovery_limit" in manifest.coverage_gaps
    assert ORIGIN + "/faqs/" not in calls
    deferred = [record for record in manifest.records if record.code == "discovery_limit"]
    assert len(deferred) == 1 and deferred[0].url == ORIGIN + "/faqs/"
    assert deferred[0].occurrence_index == 1


@pytest.mark.parametrize(
    "limits, expected_gap",
    [
        (CollectionLimits(max_links_per_page=3), "page_link_occurrence_limit"),
        (CollectionLimits(max_link_occurrences=3), "link_occurrence_limit"),
        (CollectionLimits(max_records=3), "record_limit"),
    ],
)
def test_independent_occurrence_and_record_caps_are_honest(tmp_path, limits, expected_gap):
    links = '<a href="/">same</a>' * 20
    manifest, _ = run_collection(
        tmp_path, {ORIGIN + "/": html("<main>" + links + "</main>")}, limits=limits
    )
    assert expected_gap in manifest.coverage_gaps
    assert "discovery_limit" not in manifest.coverage_gaps
    assert not manifest.coverage_complete
    assert len(manifest.records) <= limits.max_records


@pytest.mark.parametrize(
    "response, code",
    [
        (html("<main>" + "x" * 200 + "</main>"), "body_limit"),
        (
            httpx.Response(200, content=b"\xff", headers={"content-type": "text/html"}),
            "source_encoding_invalid",
        ),
        (
            httpx.Response(200, text="{}", headers={"content-type": "application/json"}),
            "page_content_type",
        ),
        (
            httpx.Response(
                200,
                text="encoded",
                headers={"content-type": "text/html", "content-encoding": "unsupported"},
            ),
            "compressed_response_not_accepted",
        ),
    ],
)
def test_invalid_source_never_persisted_as_raw_page(tmp_path, response, code):
    manifest, _ = run_collection(
        tmp_path, {ORIGIN + "/": response}, settings=configuration(crawl_max_page_bytes=100)
    )
    assert code in manifest.coverage_gaps
    assert not manifest.pages and list((tmp_path / "snapshot" / "raw").iterdir()) == []


def test_timeout_cancellation_and_error_bodies_do_not_leak(tmp_path):
    async def slow(request):
        await asyncio.sleep(0.1)
        return html("must not be reached")

    manifest, _ = run_collection(
        tmp_path, {ORIGIN + "/": slow}, limits=CollectionLimits(timeout_seconds=0.01)
    )
    assert "fetch_timeout" in manifest.coverage_gaps
    assert "must not be reached" not in manifest.model_dump_json()


def test_client_cancellation_propagates(tmp_path):
    async def handler(request):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            collect(
                configuration(),
                tmp_path / "snapshot",
                "synthetic",
                transport=httpx.MockTransport(handler),
                resolver=public_dns,
            )
        )
