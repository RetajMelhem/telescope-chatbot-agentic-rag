"""Bounded local BM25 and rank fusion for a reproducible retrieval comparison.

This literal lexical baseline is not a native Qdrant sparse index or a claim
that its analyzer is optimal for Arabic. Source occurrence identities remain
independent even when their text is identical. Analysis performs only NFC,
case folding and Unicode letter/number/combining-mark tokenization; it never
stems, translates, folds Arabic letters, expands queries or drops stopwords.
"""

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import log
from unicodedata import category, normalize

MAX_DOCUMENTS = 10_000
MAX_DOCUMENT_BYTES = 1_000_000
MAX_CORPUS_BYTES = 64_000_000
MAX_QUERY_CHARACTERS = 16_000
MAX_RESULTS = 100
MAX_RANKINGS = 8
MAX_IDENTITY_CHARACTERS = 256
MAX_RANK_CONSTANT = 10_000

_K1 = 1.2
_B = 0.75


@dataclass(frozen=True)
class LexicalHit:
    chunk_id: str
    score: float


def _identity(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("chunk identity must be a string")
    if (
        not value
        or len(value) > MAX_IDENTITY_CHARACTERS
        or value != value.strip()
        or any(category(character).startswith("C") for character in value)
    ):
        raise ValueError("chunk identity is empty, malformed or too long")
    return value


def _limit(value: object) -> int:
    if type(value) is not int or not 1 <= value <= MAX_RESULTS:
        raise ValueError(f"limit must be an integer from 1 to {MAX_RESULTS}")
    return value


def _tokens(text: str) -> tuple[str, ...]:
    tokens: list[str] = []
    current: list[str] = []
    for character in normalize("NFC", text).casefold():
        if category(character)[0] in {"L", "N", "M"}:
            current.append(character)
        elif current:
            tokens.append("".join(current))
            current.clear()
    if current:
        tokens.append("".join(current))
    return tuple(tokens)


class BM25Index:
    """Okapi BM25 with k1=1.2, b=.75 and positive Lucene-style IDF.

    Query term repetitions contribute repeated term scores. Empty/tokenless
    document text is permitted and remains part of corpus length statistics;
    it can never produce a matching hit. The caller's mapping is not retained.
    """

    def __init__(self, documents: Mapping[str, str]) -> None:
        if not isinstance(documents, Mapping) or not 1 <= len(documents) <= MAX_DOCUMENTS:
            raise ValueError(f"documents must be a mapping of 1 to {MAX_DOCUMENTS} occurrences")
        self._lengths: dict[str, int] = {}
        self._postings: dict[str, dict[str, int]] = defaultdict(dict)
        total_bytes = 0
        for raw_identity, text in documents.items():
            chunk_id = _identity(raw_identity)
            if chunk_id in self._lengths:
                raise ValueError("duplicate chunk identity")
            if len(self._lengths) >= MAX_DOCUMENTS:
                raise ValueError("too many document occurrences")
            if not isinstance(text, str):
                raise ValueError("document text must be a string")
            if len(text) > MAX_DOCUMENT_BYTES:
                raise ValueError("document text exceeds byte limit")
            try:
                size = len(text.encode("utf-8"))
            except UnicodeEncodeError as error:
                raise ValueError("document text must be valid Unicode") from error
            if size > MAX_DOCUMENT_BYTES:
                raise ValueError("document text exceeds byte limit")
            total_bytes += size
            if total_bytes > MAX_CORPUS_BYTES:
                raise ValueError("corpus text exceeds byte limit")
            terms = Counter(_tokens(text))
            self._lengths[chunk_id] = terms.total()
            for term, frequency in terms.items():
                self._postings[term][chunk_id] = frequency
        if len(self._lengths) != len(documents):
            raise ValueError("document mapping changed or reported an inconsistent length")
        self._document_count = len(self._lengths)
        self._average_length = sum(self._lengths.values()) / self._document_count

    def search(self, query: str, *, limit: int = 20) -> tuple[LexicalHit, ...]:
        limit = _limit(limit)
        if not isinstance(query, str):
            raise ValueError("query must be a string")
        if len(query) > MAX_QUERY_CHARACTERS:
            raise ValueError("query exceeds character limit")
        if any(0xD800 <= ord(character) <= 0xDFFF for character in query):
            raise ValueError("query must be valid Unicode")
        scores: dict[str, float] = defaultdict(float)
        for term, query_frequency in Counter(_tokens(query)).items():
            matches = self._postings.get(term)
            if not matches:
                continue
            inverse_frequency = log(
                1 + (self._document_count - len(matches) + 0.5) / (len(matches) + 0.5)
            )
            for chunk_id, frequency in matches.items():
                normalization = _K1 * (1 - _B + _B * self._lengths[chunk_id] / self._average_length)
                scores[chunk_id] += (
                    query_frequency
                    * inverse_frequency
                    * frequency
                    * (_K1 + 1)
                    / (frequency + normalization)
                )
        ordered = sorted(scores.items(), key=lambda hit: (-hit[1], hit[0]))
        return tuple(
            LexicalHit(chunk_id, score) for chunk_id, score in ordered[:limit] if score > 0
        )


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[str]], *, limit: int = 20, rank_constant: int = 60
) -> tuple[LexicalHit, ...]:
    """Fuse at most eight lists of at most 100 distinct occurrence identities.

    Ranks start at one and each list has equal weight: sum(1 / (k + rank)).
    Repeated identities across lists accumulate; duplicates within one list
    are invalid because they would give the occurrence extra votes.
    """
    limit = _limit(limit)
    if type(rank_constant) is not int or not 1 <= rank_constant <= MAX_RANK_CONSTANT:
        raise ValueError(f"rank constant must be an integer from 1 to {MAX_RANK_CONSTANT}")
    if (
        not isinstance(rankings, Sequence)
        or isinstance(rankings, (str, bytes))
        or len(rankings) > MAX_RANKINGS
    ):
        raise ValueError(f"rankings must be a sequence of at most {MAX_RANKINGS} lists")
    scores: dict[str, float] = defaultdict(float)
    for list_number, ranking in enumerate(rankings, start=1):
        if list_number > MAX_RANKINGS:
            raise ValueError("too many rankings")
        if (
            not isinstance(ranking, Sequence)
            or isinstance(ranking, (str, bytes))
            or len(ranking) > MAX_RESULTS
        ):
            raise ValueError(f"each ranking must contain at most {MAX_RESULTS} identities")
        seen: set[str] = set()
        for rank, raw_identity in enumerate(ranking, start=1):
            if rank > MAX_RESULTS:
                raise ValueError("too many identities in a ranking")
            chunk_id = _identity(raw_identity)
            if chunk_id in seen:
                raise ValueError("duplicate identity within a ranking")
            seen.add(chunk_id)
            scores[chunk_id] += 1 / (rank_constant + rank)
    ordered = sorted(scores.items(), key=lambda hit: (-hit[1], hit[0]))
    return tuple(LexicalHit(chunk_id, score) for chunk_id, score in ordered[:limit])
