"""Narrow readiness contract; it grants no index writes or inference capability."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class KnowledgeReadiness:
    reachable: bool = False
    approved: bool = False
    snapshot_id: str | None = None
    embedding_model: str | None = None
    dimensions: int | None = None


class KnowledgeProbe(Protocol):
    async def check_readiness(self) -> KnowledgeReadiness: ...

    async def aclose(self) -> None: ...


class UnavailableKnowledgeProbe:
    """Fail closed until M3/M4 supply a real approved-snapshot adapter."""

    async def check_readiness(self) -> KnowledgeReadiness:
        return KnowledgeReadiness()

    async def aclose(self) -> None:
        return None
