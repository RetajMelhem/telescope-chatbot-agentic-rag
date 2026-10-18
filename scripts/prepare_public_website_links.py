"""Reproduce the bounded, separately reviewed homepage-link supplement offline.

No crawl, inference, embeddings or index writes. The selected two official pages
and four platforms are an explicit review scope, not a whole-site omission audit.
"""

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from telescope_rag.api.local import PREPARED_DIGEST
from telescope_rag.ingestion.extraction import _locators
from telescope_rag.ingestion.models import stable_id
from telescope_rag.ingestion.runner import load_reviewed_bundle
from telescope_rag.knowledge.public_links import (
    PLATFORM_HOSTS,
    PublicLinksCatalog,
    WebsiteLink,
    WebsiteLinksPlan,
    links_digest,
)


def prepare(root: Path, output: Path) -> str:
    bundle = load_reviewed_bundle(root / "data/processed/m3-execution-approved-v6-v2")
    links, pages = [], []
    for source_url, language in (
        ("https://telescopecenter.com/", "en"),
        ("https://telescopecenter.com/ar/", "ar"),
    ):
        page = next(
            d.document.page for d in bundle.documents if d.document.page.canonical_url == source_url
        )
        pages.append(page)
        soup = BeautifulSoup(page.html, "html.parser")
        locators = _locators(soup)
        for platform, host in PLATFORM_HOSTS.items():
            nodes = [
                node for node in soup.select("a[href]") if urlsplit(node["href"]).netloc == host
            ]
            if len(nodes) != 1:
                raise ValueError("homepage_link_inventory_changed_requires_review")
            node = nodes[0]
            label, target, locator = node.get_text(" ").strip(), node["href"], locators[id(node)]
            links.append(
                WebsiteLink(
                    link_id=stable_id(
                        "website-link-v1",
                        page.document_id,
                        page.content_hash,
                        locator,
                        label,
                        target,
                    ),
                    platform=platform,
                    target_url=target,
                    literal_label=label,
                    source_url=source_url,
                    document_id=page.document_id,
                    snapshot_id=page.snapshot_id,
                    fetched_at=page.fetched_at,
                    source_content_hash=page.content_hash,
                    source_language=language,
                    locator=locator,
                )
            )
    plan = WebsiteLinksPlan(base_prepared_digest=PREPARED_DIGEST, links=tuple(links))
    digest = links_digest(plan)
    PublicLinksCatalog(
        plan, expected_digest=digest, base_prepared_digest=PREPARED_DIGEST, pages=tuple(pages)
    )
    output.mkdir(parents=True, exist_ok=False)
    (output / "reviewed-links-plan.json").write_text(
        plan.model_dump_json(indent=2), encoding="utf-8"
    )
    (output / "source-verification.json").write_text(
        json.dumps(
            {
                "plan_digest": digest,
                "sources": [p.canonical_url for p in pages],
                "source_occurrences": len(links),
                "distinct_targets": len({link.target_url for link in links}),
                "every_href_and_label_exactly_verified": True,
                "external_accounts_fetched_or_independently_verified": False,
                "base_prepared_digest": PREPARED_DIGEST,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return digest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(prepare(Path.cwd(), args.output))
