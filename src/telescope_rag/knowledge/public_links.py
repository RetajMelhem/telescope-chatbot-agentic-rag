"""Separately reviewed outgoing links, proven against saved official website HTML.

Targets are navigation destinations, never fetch permissions or facts about the
external account. This supplement does not modify the admitted vector catalog.
"""

import hashlib
import json
from datetime import datetime
from types import MappingProxyType
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from pydantic import Field, model_validator

from telescope_rag.ingestion.models import RawPage, Record, stable_id
from telescope_rag.retrieval.assembly import RequestPart

PLATFORM_HOSTS = {
    "Facebook": "www.facebook.com",
    "Instagram": "www.instagram.com",
    "LinkedIn": "www.linkedin.com",
    "YouTube": "www.youtube.com",
}


class WebsiteLink(Record):
    link_id: str
    platform: str
    target_url: str
    literal_label: str
    source_url: str
    document_id: str
    snapshot_id: str
    fetched_at: datetime
    source_content_hash: str
    source_language: str
    locator: str

    @model_validator(mode="after")
    def validate_link(self):
        target, source = urlsplit(self.target_url), urlsplit(self.source_url)
        if (
            self.platform not in PLATFORM_HOSTS
            or target.scheme != "https"
            or target.netloc != PLATFORM_HOSTS[self.platform]
            or target.query
            or target.fragment
            or target.path in {"", "/"}
            or source.scheme != "https"
            or source.netloc != "telescopecenter.com"
            or source.query
            or source.fragment
            or not self.literal_label.strip()
            or self.source_language not in {"en", "ar"}
            or self.fetched_at.utcoffset() is None
            or self.link_id
            != stable_id(
                "website-link-v1",
                self.document_id,
                self.source_content_hash,
                self.locator,
                self.literal_label,
                self.target_url,
            )
        ):
            raise ValueError("website_link_invalid")
        return self


class WebsiteLinksPlan(Record):
    version: str = "reviewed-website-links-v1"
    base_prepared_digest: str
    links: tuple[WebsiteLink, ...] = Field(min_length=1, max_length=8)


def links_digest(plan: WebsiteLinksPlan) -> str:
    return stable_id(
        "website-links-plan-v1",
        json.dumps(plan.model_dump(mode="json"), sort_keys=True, ensure_ascii=False),
    )


class PublicLinksCatalog:
    def __init__(
        self,
        plan: WebsiteLinksPlan,
        *,
        expected_digest: str,
        base_prepared_digest: str,
        pages: tuple[RawPage, ...],
    ):
        plan = WebsiteLinksPlan.model_validate_json(plan.model_dump_json())
        if (
            plan.version != "reviewed-website-links-v1"
            or links_digest(plan) != expected_digest
            or plan.base_prepared_digest != base_prepared_digest
            or len({link.link_id for link in plan.links}) != len(plan.links)
            or len({(link.document_id, link.locator) for link in plan.links}) != len(plan.links)
        ):
            raise ValueError("website_links_plan_binding_invalid")
        sources = {p.document_id: p for p in pages}
        soups = {}
        for link in plan.links:
            page = sources.get(link.document_id)
            if page is None or (
                page.canonical_url != link.source_url
                or page.snapshot_id != link.snapshot_id
                or page.fetched_at != link.fetched_at
                or page.content_hash != link.source_content_hash
                or hashlib.sha256(page.html.encode("utf-8")).hexdigest() != page.content_hash
            ):
                raise ValueError("website_link_source_binding_invalid")
            if page.document_id not in soups:
                soups[page.document_id] = BeautifulSoup(page.html, "html.parser")
            nodes = soups[page.document_id].select(link.locator)
            if (
                len(nodes) != 1
                or nodes[0].name != "a"
                or nodes[0].get("href") != link.target_url
                or nodes[0].get_text(" ").strip() != link.literal_label
            ):
                raise ValueError("website_link_literal_mismatch")
        self.links = MappingProxyType({link.link_id: link for link in plan.links})
        self.digest = expected_digest

    def eligible(self, part: RequestPart, operation: str) -> tuple[str, ...]:
        # This is capability scoping, not semantic routing. The existing writer
        # decides relevance from the original question and these literal links.
        scope = part.scope
        if (
            part.state != "public"
            or operation not in {"search", "read_source"}
            or scope.owner_id is not None
            or part.intended_use != "general_excerpt"
            or (scope.block_types and "contact" not in scope.block_types)
        ):
            return ()
        return tuple(
            link.link_id
            for link in self.links.values()
            if (not scope.document_ids or link.document_id in scope.document_ids)
            and (scope.language is None or scope.language == link.source_language)
        )

    def rendering(self, ids: tuple[str, ...]) -> list[dict]:
        return [
            {
                key: value
                for key, value in self.links[i].model_dump(mode="json").items()
                if key
                in {
                    "link_id",
                    "platform",
                    "target_url",
                    "literal_label",
                    "source_url",
                    "source_language",
                }
            }
            for i in dict.fromkeys(ids)
        ]
