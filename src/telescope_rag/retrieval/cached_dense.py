"""Pure bounded cosine ranking of explicitly supplied, already cached vectors.

The caller owns source admission, cache/configuration verification and grouping
policy. This ranker neither loads files nor fetches, creates or embeds content.
"""

import math
from collections import defaultdict
from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from unicodedata import category

from telescope_rag.ingestion.models import PreparedChunk

MAX_CACHED_CHUNKS = 10_000
MAX_CACHED_DIMENSIONS = 4096
MAX_CACHED_RESULTS = 100
MAX_ID_CHARACTERS = 256


@dataclass(frozen=True, slots=True)
class RankedCachedHit:
    chunk_id: str
    score: float
    occurrence_ids: tuple[str, ...]


def _identity(value: object) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= MAX_ID_CHARACTERS
        or value != value.strip()
        or any(category(character).startswith("C") for character in value)
    ):
        raise ValueError("cached_dense_invalid_identity")
    return value


def _bounded_mapping(value: object) -> dict:
    if not isinstance(value, Mapping) or not 1 <= len(value) <= MAX_CACHED_CHUNKS:
        raise ValueError("cached_dense_invalid_inventory")
    copied = {}
    for count, (key, item) in enumerate(value.items(), start=1):
        key = _identity(key)
        if count > MAX_CACHED_CHUNKS or key in copied:
            raise ValueError("cached_dense_invalid_inventory")
        copied[key] = item
    if len(copied) != len(value):
        raise ValueError("cached_dense_invalid_inventory")
    return copied


def _normalize(vector: object, dimensions: int) -> tuple[float, ...]:
    if (
        not isinstance(vector, Sequence)
        or isinstance(vector, (str, bytes, bytearray))
        or len(vector) != dimensions
    ):
        raise ValueError("cached_dense_invalid_vector")
    values: list[float] = []
    try:
        for value in vector:
            if len(values) >= dimensions or type(value) not in {float, int}:
                raise ValueError("invalid_coordinate")
            coordinate = float(value)
            if not math.isfinite(coordinate):
                raise ValueError("nonfinite_coordinate")
            values.append(coordinate)
        if len(values) != dimensions:
            raise ValueError("inconsistent_vector_length")
        scale = max(abs(value) for value in values)
        if scale == 0:
            raise ValueError("zero_vector")
        # Scaling first avoids overflow/underflow in the Euclidean norm while
        # retaining the direction of finite large or subnormal coordinates.
        scaled = tuple(value / scale for value in values)
        norm = math.hypot(*scaled)
        return tuple(value / norm for value in scaled)
    except (ValueError, TypeError, OverflowError):
        raise ValueError("cached_dense_invalid_vector") from None


class CachedDenseRanker:
    """Rank every supplied occurrence before applying an explicit grouping key.

    Grouping is optional and does not compare text, owners or specialties. A
    supplied key defines exact groups; each selected hit lists every occurrence
    in its group across the complete inventory, including lower ranked ones.
    """

    def __init__(
        self,
        chunks: Mapping[str, PreparedChunk],
        vectors: Mapping[str, Sequence[float]],
        *,
        expected_dimensions: int = MAX_CACHED_DIMENSIONS,
    ) -> None:
        if (
            type(expected_dimensions) is not int
            or not 1 <= expected_dimensions <= MAX_CACHED_DIMENSIONS
        ):
            raise ValueError("cached_dense_invalid_dimensions")
        chunk_values = _bounded_mapping(chunks)
        vector_values = _bounded_mapping(vectors)
        if set(chunk_values) != set(vector_values):
            raise ValueError("cached_dense_vector_inventory_mismatch")
        frozen_chunks: dict[str, PreparedChunk] = {}
        normalized: dict[str, tuple[float, ...]] = {}
        point_ids: set[str] = set()
        configurations: set[tuple] = set()
        for chunk_id in sorted(chunk_values):
            chunk = chunk_values[chunk_id]
            if not isinstance(chunk, PreparedChunk):
                raise ValueError("cached_dense_invalid_chunk")
            try:
                # Clone and revalidate even model_copy instances; later caller
                # mutation cannot alter this ranker's snapshot or vector input.
                copied = PreparedChunk.model_validate_json(chunk.model_dump_json())
                if copied.chunk_id != chunk_id or not copied.snapshot_id:
                    raise ValueError("forged_chunk_identity")
                point_id = _identity(copied.point_id)
                if point_id in point_ids:
                    raise ValueError("duplicate_point_identity")
            except (ValueError, TypeError, OverflowError):
                raise ValueError("cached_dense_invalid_chunk") from None
            configurations.add(
                (
                    copied.snapshot_id,
                    copied.preparation_version,
                    copied.tokenizer_version,
                    copied.embedding_format_version,
                    copied.embedding_format_hash,
                    copied.admission_policy_hash,
                    copied.embedding_ready,
                )
            )
            point_ids.add(point_id)
            frozen_chunks[chunk_id] = copied
            normalized[chunk_id] = _normalize(vector_values[chunk_id], expected_dimensions)
        if len(configurations) != 1:
            raise ValueError("cached_dense_mixed_snapshot_or_configuration")
        self._dimensions = expected_dimensions
        self._chunks = MappingProxyType(frozen_chunks)
        self._vectors = MappingProxyType(normalized)

    def search(
        self,
        query_vector: Sequence[float],
        *,
        limit: int = 20,
        group_key: Callable[[PreparedChunk], Hashable] | None = None,
    ) -> tuple[RankedCachedHit, ...]:
        if type(limit) is not int or not 1 <= limit <= MAX_CACHED_RESULTS:
            raise ValueError("cached_dense_invalid_limit")
        if group_key is not None and not callable(group_key):
            raise ValueError("cached_dense_invalid_group_key")
        query = _normalize(query_vector, self._dimensions)
        ranked = sorted(
            (
                (
                    chunk_id,
                    max(
                        -1.0,
                        min(
                            1.0,
                            math.fsum(a * b for a, b in zip(query, vector, strict=True)),
                        ),
                    ),
                )
                for chunk_id, vector in self._vectors.items()
            ),
            key=lambda hit: (-hit[1], hit[0]),
        )
        if group_key is None:
            return tuple(
                RankedCachedHit(chunk_id, score, (chunk_id,)) for chunk_id, score in ranked[:limit]
            )
        groups: dict[Hashable, list[str]] = defaultdict(list)
        group_by_id: dict[str, Hashable] = {}
        try:
            for chunk_id in sorted(self._chunks):
                key = group_key(self._chunks[chunk_id])
                hash(key)
                groups[key].append(chunk_id)
                group_by_id[chunk_id] = key
        except Exception:
            raise ValueError("cached_dense_invalid_group_key") from None
        selected: list[RankedCachedHit] = []
        seen: set[Hashable] = set()
        for chunk_id, score in ranked:
            key = group_by_id[chunk_id]
            if key in seen:
                continue
            seen.add(key)
            selected.append(RankedCachedHit(chunk_id, score, tuple(groups[key])))
            if len(selected) == limit:
                break
        return tuple(selected)
