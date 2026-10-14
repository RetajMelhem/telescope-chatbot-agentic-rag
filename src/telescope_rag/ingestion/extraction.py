"""Conservative HTML structure extraction with occurrence-level source mappings.

Locators address the original DOM. Offsets address text extracted from that node,
not HTML bytes. No model, network request, or factual rewrite is involved.
"""

import re
import unicodedata
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from telescope_rag.ingestion.models import (
    AuditItem,
    ContentUnit,
    ExtractedDocument,
    RawPage,
    Segment,
    SourceSpan,
    stable_id,
)

_HEADINGS = re.compile(r"^h[1-6]$")
_DOCTOR = re.compile(
    r"^(?:(?:Prof\.?|Professor)\s+)?(?:Dr\.?\s+|Doctor\s+|د(?:\s*\.\s*|\s+)"
    r"|(?:الأستاذ(?:ة)?\s+)?الدكتور(?:ة)?\s+|دكتور(?:ة)?\s+)",
    re.I,
)
_QUESTION = re.compile(r"[?؟]\s*$")
_REMOVABLE = {
    "script": "executable_content",
    "style": "presentation_styles",
    "noscript": "fallback_or_tracking_content",
    "template": "inactive_template",
    "nav": "navigation",
    "form": "form_submission_content",
    "input": "form_control",
    "select": "form_control",
    "textarea": "form_control",
    "button": "form_control",
    "iframe": "external_or_embedded_content",
    "svg": "nontext_graphic",
    "canvas": "nontext_graphic",
}
_REMOVABLE_CLASSES = {
    "testimonial": "patient_testimonial",
    "testimonials": "patient_testimonial",
    "review": "patient_testimonial",
    "reviews": "patient_testimonial",
    "elementor-widget-testimonial": "patient_testimonial",
    "elementor-widget-testimonial-carousel": "patient_testimonial",
    "elementor-testimonial": "patient_testimonial",
    "elementor-widget-reviews": "patient_testimonial",
    "commentlist": "user_submission",
    "comment-list": "user_submission",
    "comment-content": "user_submission",
    "comments-area": "user_submission",
    "wp-block-comments": "user_submission",
    "wp-block-comment-template": "user_submission",
    "elementor-widget-social-icons": "external_social_navigation",
    "elementor-social-icons-wrapper": "external_social_navigation",
    "skip-link": "navigation_skip_link",
    "wp-block-navigation": "navigation",
    "cookie-banner": "cookie_notice",
    "cookie-consent": "cookie_notice",
    "cookie-notice": "cookie_notice",
}
_PROFILE_CLASSES = {"doctor", "doctor-card", "doctor-profile", "team-member", "physician"}
_FAQ_CLASSES = {"faq-item", "faq-question", "accordion-item", "schema-faq-section"}
_PLACEHOLDERS = re.compile(r"^(?:lorem ipsum\b.*|coming soon[.!]?|under construction[.!]?)$", re.I)
_DUMMY_TEXT = re.compile(r"\blorem\s+ipsum(?:\b|u00a0)", re.I)
MAX_DOM_NODES = 20_000
MAX_DOM_DEPTH = 128
MAX_HTML_BYTES = 2_000_000


def normalize_text(value: str) -> str:
    """NFC/layout whitespace only; retain letters, diacritics, numbers and punctuation."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", value)).strip()


def _language(value: str) -> str:
    if re.search(r"[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff]", value):
        return "ar"
    if re.search(r"[A-Za-z]", value):
        return "en"
    return "und"


def _classes(node: Tag) -> set[str]:
    return set(node.get("class", []))


class _StructureLimit(Exception):
    pass


def _locators(soup: BeautifulSoup) -> dict[int, str]:
    """One sibling pass per parent; avoid repeated preceding-sibling scans."""
    result = {}
    stack = [(soup, "", 0)]
    while stack:
        parent, prefix, depth = stack.pop()
        counts: dict[str, int] = {}
        for child in parent.children:
            if not isinstance(child, Tag):
                continue
            if depth + 1 > MAX_DOM_DEPTH or len(result) >= MAX_DOM_NODES:
                raise _StructureLimit("dom_complexity_limit")
            counts[child.name] = counts.get(child.name, 0) + 1
            component = f"{child.name}:nth-of-type({counts[child.name]})"
            locator = f"{prefix} > {component}" if prefix else component
            result[id(child)] = locator
            stack.append((child, locator, depth + 1))
    return result


@dataclass
class _State:
    headings: list[tuple[int, Segment]] = field(default_factory=list)
    doctor: Segment | None = None
    doctor_level: int | None = None
    faq: Segment | None = None
    faq_level: int | None = None


class _Extractor:
    def __init__(self, page: RawPage):
        self.page = page
        if len(page.html.encode("utf-8")) > MAX_HTML_BYTES:
            raise _StructureLimit("html_size_limit")
        self.soup = BeautifulSoup(page.html, "html.parser")
        self.locators = _locators(self.soup)
        self.originals = {
            id(node): node.get_text(separator=" ", strip=False) for node in self.soup.find_all(True)
        }
        self.units: list[ContentUnit] = []
        self.removed: list[AuditItem] = []
        self.gaps: list[AuditItem] = []
        self.state = _State()
        self.pending: list[Segment] = []
        self.pending_kind = "section"
        self.emitted_owners: set[str] = set()
        title = self.soup.find("title")
        self.title_context = self.segment(title) if title else None
        self.title = self.title_context.text if self.title_context else ""
        if self.title_context and _DUMMY_TEXT.search(self.title_context.text):
            self.audit(title, "placeholder_title")
            self.title_context = None
            self.gaps.append(
                AuditItem(code="placeholder_document", locator=self.locators[id(title)])
            )
        self.profile_roots: set[int] = set()
        # Repeated Elementor wrappers are not identities. A separate, minimal
        # container containing one literal doctor heading and attached paragraphs
        # supplies a boundary even if every card reuses the same CSS classes.
        for heading in self.soup.find_all(_HEADINGS):
            if not _DOCTOR.match(normalize_text(heading.get_text(" ", strip=False))):
                continue
            for ancestor in heading.parents:
                if not isinstance(ancestor, Tag) or ancestor.name in {
                    "main",
                    "body",
                    "html",
                    "[document]",
                }:
                    break
                doctor_headings = [
                    h
                    for h in ancestor.find_all(_HEADINGS)
                    if _DOCTOR.match(normalize_text(h.get_text(" ", strip=False)))
                ]
                if len(doctor_headings) != 1:
                    break
                if ancestor.find("p"):
                    self.profile_roots.add(id(ancestor))
                    break

    def segment(self, node: Tag, text: str | None = None) -> Segment:
        original = self.originals[id(node)]
        locator = self.locators[id(node)]
        return Segment(
            text=normalize_text(node.get_text(separator=" ", strip=False))
            if text is None
            else text,
            source=SourceSpan(
                block_id=stable_id(self.page.document_id, locator),
                locator=locator,
                original_text=original,
                end=len(original),
                source_line=node.sourceline,
            ),
        )

    def audit(self, node: Tag, code: str, *, gap: bool = False):
        (self.gaps if gap else self.removed).append(
            AuditItem(code=code, locator=self.locators.get(id(node)))
        )

    def clean(self):
        for node in list(self.soup.find_all(True)):
            if node.parent is None:
                continue
            code = _REMOVABLE.get(node.name)
            if not code:
                code = next(
                    (_REMOVABLE_CLASSES[c] for c in _classes(node) if c in _REMOVABLE_CLASSES),
                    None,
                )
            if code:
                self.audit(node, code)
                node.decompose()

    def context(self) -> tuple[Segment, ...]:
        context = ([self.title_context] if self.title_context else []) + [
            segment for _, segment in self.state.headings
        ]
        for extra in (self.state.doctor, self.state.faq):
            if extra and all(s.source.block_id != extra.source.block_id for s in context):
                context.append(extra)
        return tuple(context)

    def emit(self, kind: str, segments: list[Segment], *, extra: list[Segment] | None = None):
        admitted = []
        for segment in segments:
            if _DUMMY_TEXT.search(segment.text):
                self.removed.append(
                    AuditItem(code="placeholder_content", locator=segment.source.locator)
                )
                self.gaps.append(
                    AuditItem(
                        code="placeholder_content_quarantined", locator=segment.source.locator
                    )
                )
            else:
                admitted.append(segment)
        segments = admitted
        if not segments:
            return
        doctor = self.state.doctor
        context = self.context() + tuple(extra or [])
        if any(_DUMMY_TEXT.search(segment.text) for segment in context):
            self.gaps.append(AuditItem(code="placeholder_context_quarantined"))
            return
        unit_id = stable_id(
            self.page.document_id,
            kind,
            *(s.source.block_id for s in segments),
            *(s.source.block_id for s in context),
        )
        self.units.append(
            ContentUnit(
                unit_id=unit_id,
                kind=kind,
                section_path=tuple(s.text for _, s in self.state.headings),
                context=context,
                segments=tuple(segments),
                doctor_id=stable_id("doctor", self.page.document_id, doctor.source.block_id)
                if doctor
                else None,
                doctor_name=doctor.text if doctor else None,
                language=_language(" ".join(s.text for s in (*context, *segments))),
            )
        )

        if doctor:
            self.emitted_owners.add(doctor.source.block_id)

    def finish_owner(self):
        owner = self.state.doctor
        if owner and owner.source.block_id not in self.emitted_owners:
            self.emit("doctor", [owner])

    def flush(self):
        if self.pending:
            kind = (
                "faq" if self.state.faq else ("doctor" if self.state.doctor else self.pending_kind)
            )
            self.emit(kind, self.pending)
            self.pending = []

    def heading(self, node: Tag):
        self.flush()
        level = int(node.name[1])
        segment = self.segment(node)
        if self.state.doctor_level is not None and level <= self.state.doctor_level:
            self.finish_owner()
            self.state.doctor = None
            self.state.doctor_level = None
        if self.state.faq_level is not None and level <= self.state.faq_level:
            self.state.faq = None
            self.state.faq_level = None
        self.state.headings = [(n, s) for n, s in self.state.headings if n < level]
        # Removed headings still delimit ownership/section scope in the source.
        if not segment.text:
            self.audit(node, "empty_heading")
            return
        if _PLACEHOLDERS.fullmatch(segment.text) or _DUMMY_TEXT.search(segment.text):
            self.audit(node, "placeholder_heading")
            return
        self.state.headings.append((level, segment))
        if _DOCTOR.match(segment.text):
            self.state.doctor = segment
            self.state.doctor_level = level
        elif _QUESTION.search(segment.text):
            self.state.faq = segment
            self.state.faq_level = level

    def details(self, node: Tag):
        self.flush()
        question = node.find("summary", recursive=False)
        if not question:
            self.audit(node, "faq_question_missing", gap=True)
            return
        question_segment = self.segment(question)
        answer_nodes = [child for child in node.children if child is not question]
        segments = self.answer_segments(answer_nodes)
        if not question_segment.text or not segments:
            self.audit(node, "faq_pair_incomplete", gap=True)
            return
        self.emit("faq", segments, extra=[question_segment])

    def text_segment(self, node: NavigableString) -> Segment:
        parent = node.parent
        siblings = [value for value in parent.contents if isinstance(value, NavigableString)]
        index = next(i for i, value in enumerate(siblings, 1) if value is node)
        original = str(node)
        locator = f"{self.locators[id(parent)]}::text({index})"
        return Segment(
            text=normalize_text(original),
            source=SourceSpan(
                block_id=stable_id(self.page.document_id, locator),
                locator=locator,
                original_text=original,
                end=len(original),
                source_line=parent.sourceline,
            ),
        )

    def answer_segments(self, nodes: list[Tag | NavigableString]) -> list[Segment]:
        result = []
        for child in nodes:
            if isinstance(child, Comment):
                continue
            if isinstance(child, NavigableString):
                if normalize_text(str(child)):
                    result.append(self.text_segment(child))
                continue
            if child.name in {"p", "li"} or not child.find(["p", "li", "div", "ul", "ol"]):
                segment = self.segment(child)
                if segment.text:
                    result.append(segment)
                continue
            for descendant in child.children:
                if isinstance(descendant, Tag):
                    result.extend(self.answer_segments([descendant]))
                elif (
                    isinstance(descendant, NavigableString)
                    and not isinstance(descendant, Comment)
                    and normalize_text(str(descendant))
                ):
                    # Keep direct answer text too; its text-node locator remains a
                    # separate original occurrence beside structured paragraphs.
                    result.append(self.text_segment(descendant))
        return result

    def definition_list(self, node: Tag):
        self.flush()
        current: Segment | None = None
        answers: list[Segment] = []
        for child in node.find_all(["dt", "dd"], recursive=False):
            if child.name == "dt":
                if current:
                    if answers:
                        self.emit("faq", answers, extra=[current])
                    else:
                        self.audit(node, "faq_pair_incomplete", gap=True)
                current = self.segment(child)
                answers = []
            elif current:
                answers.extend(self.answer_segments([child]))
            else:
                self.audit(child, "orphan_definition_answer", gap=True)
        if current:
            if answers:
                self.emit("faq", answers, extra=[current])
            else:
                self.audit(node, "faq_pair_incomplete", gap=True)

    def faq_card(self, node: Tag):
        self.flush()
        question = node.find(attrs={"itemprop": "name"}) or node.find(_HEADINGS)
        answer = node.find(attrs={"itemprop": "acceptedAnswer"}) or node.find(
            class_=lambda value: (
                value and ("answer" in value.split() or "faq-answer" in value.split())
            )
        )
        if not question or not answer or question is answer:
            # An unresolved accordion layout is not a license to guess a pairing.
            self.audit(node, "faq_pair_unresolved", gap=True)
            return
        question_segment = self.segment(question)
        answers = self.answer_segments([answer])
        if question_segment.text and answers:
            self.emit("faq", answers, extra=[question_segment])
        else:
            self.audit(node, "faq_pair_incomplete", gap=True)

    def table(self, node: Tag):
        self.flush()
        if any(
            cell.get("rowspan", "1") != "1" or cell.get("colspan", "1") != "1"
            for cell in node.find_all(["th", "td"])
        ):
            self.audit(node, "ambiguous_table_span", gap=True)
            return
        if node.find("table"):
            self.audit(node, "nested_table_unresolved", gap=True)
            return
        rows = node.find_all("tr")
        header_rows = [row for row in rows if row.find_parent("thead")]
        if not header_rows and rows and rows[0].find("th"):
            header_rows = [rows[0]]
        if len(header_rows) != 1:
            self.audit(node, "table_headers_unresolved", gap=True)
            return
        header = header_rows[0]
        cells = header.find_all(["th", "td"], recursive=False)
        labels = [self.segment(cell) for cell in cells]
        if not labels or any(not label.text for label in labels):
            self.audit(node, "table_headers_unresolved", gap=True)
            return
        extra = []
        caption = node.find("caption", recursive=False)
        if caption:
            extra.append(self.segment(caption))
        extra.extend(labels)
        foot = node.find("tfoot", recursive=False)
        if foot:
            extra.append(self.segment(foot))
        described_by = str(node.get("aria-describedby", "")).split()
        for identifier in described_by:
            note = self.soup.find(id=identifier)
            if note:
                extra.append(self.segment(note))
            else:
                self.audit(node, "table_footnote_unresolved", gap=True)
                return
        segments = []
        for row in rows:
            if row in header_rows or row.find_parent("tfoot"):
                continue
            row_cells = row.find_all(["th", "td"], recursive=False)
            if len(row_cells) != len(labels):
                self.audit(node, "table_row_width_mismatch", gap=True)
                return
            values = [self.segment(cell).text for cell in row_cells]
            if not any(values):
                self.audit(row, "empty_table_row")
                continue
            segments.append(
                self.segment(row).model_copy(
                    update={
                        "table_cells": tuple(self.segment(cell).source for cell in row_cells),
                        "table_headers": tuple(label.source for label in labels),
                    }
                )
            )
        if not segments:
            self.audit(node, "table_rows_missing", gap=True)
            return
        self.emit("table", segments, extra=extra)

    def list(self, node: Tag):
        self.flush()
        if node.name == "ol" and (
            node.has_attr("reversed")
            or node.get("start", "1") != "1"
            or any(item.has_attr("value") for item in node.find_all("li", recursive=False))
        ):
            self.audit(node, "list_numbering_unresolved", gap=True)
            return
        if node.find(["ul", "ol"]):
            self.audit(node, "nested_list_requires_explicit_segmentation", gap=True)
            return
        items = node.find_all("li", recursive=False)
        segments = [self.segment(item) for item in items]
        # A literal profile name in a list establishes only that list item's owner.
        pending = []
        for item, segment in zip(items, segments, strict=True):
            if _DOCTOR.match(segment.text):
                self.emit("list", pending)
                pending = []
                saved = self.state.doctor
                names = [
                    child
                    for child in item.find_all(["strong", "b", "span"])
                    if _DOCTOR.match(self.segment(child).text)
                ]
                self.state.doctor = self.segment(names[0]) if names else segment
                self.emit("doctor", [segment])
                self.state.doctor = saved
            else:
                pending.append(segment)
        self.emit("list", pending)

    def walk(self, node: Tag, *, inside_profile: bool = False):
        if node.name == "head":
            return
        if _HEADINGS.match(node.name):
            self.heading(node)
            return
        if node.name == "details":
            self.details(node)
            return
        if node.name == "dl":
            self.definition_list(node)
            return
        if node.name == "table":
            self.table(node)
            return
        if node.name == "div" and "grid" in _classes(node):
            children = [child for child in node.children if isinstance(child, Tag)]
            header_cells = [child for child in children if {"cell", "header"} <= _classes(child)]
            if len(header_cells) >= 2:
                # This explicit CSS table pattern carries column and merged group
                # relationships that a generic div/paragraph walk would destroy.
                # Retain its pristine snapshot/locator for a later supported parser.
                self.flush()
                self.audit(node, "unsupported_css_grid_table", gap=True)
                return
        if node.name in {"ul", "ol"}:
            self.list(node)
            return
        if _FAQ_CLASSES.intersection(_classes(node)) or node.get("itemtype", "").endswith(
            "Question"
        ):
            self.faq_card(node)
            return
        if not inside_profile and (
            id(node) in self.profile_roots
            or _PROFILE_CLASSES.intersection(_classes(node))
            or node.get("itemtype", "").endswith("Physician")
        ):
            self.flush()
            saved_state = self.state
            self.state = _State(headings=list(saved_state.headings))
            name = node.find(attrs={"itemprop": "name"}) or node.find(_HEADINGS)
            if not name or not self.segment(name).text:
                self.audit(node, "doctor_owner_unresolved", gap=True)
            else:
                self.state.doctor = self.segment(name)
                for child in node.children:
                    if isinstance(child, Tag):
                        self.walk(child, inside_profile=True)
                self.flush()
                self.finish_owner()
            self.state = saved_state
            return
        if node.name in {"p", "address", "blockquote", "pre"}:
            segment = self.segment(node)
            if not segment.text:
                self.audit(node, "empty_content")
            elif _PLACEHOLDERS.fullmatch(segment.text):
                self.audit(node, "placeholder_content")
            else:
                if node.name == "address" or node.find_parent("footer"):
                    if self.pending_kind != "contact":
                        self.flush()
                    self.pending_kind = "contact"
                elif self.pending_kind != "section":
                    self.flush()
                    self.pending_kind = "section"
                self.pending.append(segment)
            return
        children = [child for child in node.children if isinstance(child, Tag)]
        if node.name in {"div", "section", "article", "aside", "footer"} and not node.find(
            [
                "p",
                "h1",
                "h2",
                "h3",
                "h4",
                "h5",
                "h6",
                "ul",
                "ol",
                "table",
                "details",
                "dl",
                "div",
                "section",
                "article",
                "address",
            ]
        ):
            segment = self.segment(node)
            if segment.text:
                if _PLACEHOLDERS.fullmatch(segment.text):
                    self.audit(node, "placeholder_content")
                else:
                    self.pending.append(segment)
            return
        if not children:
            segment = self.segment(node)
            if segment.text:
                # Meaningful unsupported layouts stay visible in the audit, not silently dropped.
                self.audit(node, "unsupported_text_structure", gap=True)
            return
        for child in children:
            self.walk(child, inside_profile=inside_profile)
        if any(
            isinstance(child, NavigableString)
            and not isinstance(child, Comment)
            and normalize_text(str(child))
            for child in node.children
        ):
            self.audit(node, "unsupported_direct_text_structure", gap=True)

    def extract(self) -> ExtractedDocument:
        self.clean()
        main = self.soup.find("main")
        if main:
            self.walk(main)
            self.flush()
            self.finish_owner()
            if not self.units:
                self.gaps.append(AuditItem(code="main_content_missing"))
            for footer in self.soup.find_all("footer"):
                if not footer.find_parent("main"):
                    self.state = _State()
                    self.pending_kind = "contact"
                    self.walk(footer)
                    self.flush()
            for header in self.soup.find_all("header"):
                if not header.find_parent("main"):
                    self.audit(header, "header_navigation_not_indexed")
        else:
            self.walk(self.soup.find("body") or self.soup)
        self.flush()
        self.finish_owner()
        if not self.units:
            self.gaps.append(AuditItem(code="no_meaningful_units"))
        return ExtractedDocument(
            page=self.page,
            title=self.title,
            units=tuple(self.units),
            removed=tuple(self.removed),
            gaps=tuple(self.gaps),
        )


def extract_page(page: RawPage) -> ExtractedDocument:
    """Extract supported units from one immutable, already admitted HTML snapshot."""
    try:
        return _Extractor(page).extract()
    except _StructureLimit as error:
        return ExtractedDocument(page=page, title="", units=(), gaps=(AuditItem(code=str(error)),))


extract_document = extract_page
