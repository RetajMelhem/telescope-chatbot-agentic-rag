"""Request-owned reservations: synchronous updates are atomic within one event loop."""

from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic

from telescope_rag.core.settings import Settings
from telescope_rag.providers.contracts import AttemptReceipt, OperationKind, TokenCount, UsageReport
from telescope_rag.providers.errors import ProviderError


@dataclass
class Reservation:
    kind: OperationKind
    count: TokenCount
    output: int
    settled: bool = False


class ExecutionBudget:
    """Share across a request's operations; use a new bounded budget per ingestion batch."""

    def __init__(self, settings: Settings, *, clock: Callable[[], float] = monotonic) -> None:
        self._clock = clock
        self.deadline = clock() + settings.request_timeout_seconds
        self._operation_limits = {
            "chat": settings.max_llm_calls,
            "embedding": settings.max_embedding_calls,
        }
        self._attempt_limits = {
            kind: count * (1 + settings.provider_max_retries)
            for kind, count in self._operation_limits.items()
        }
        self._input_limits = {
            "chat": settings.max_total_input_tokens,
            "embedding": settings.max_embedding_input_tokens,
        }
        self._output_limit = settings.max_total_output_tokens
        self.operations = {"chat": 0, "embedding": 0}
        self.attempts = {"chat": 0, "embedding": 0}
        self.input_charged = {"chat": 0, "embedding": 0}
        self.output_charged = 0
        self.blocked = False
        self._receipts: list[AttemptReceipt] = []

    @property
    def receipts(self) -> tuple[AttemptReceipt, ...]:
        return tuple(self._receipts)

    def remaining_seconds(self) -> float:
        remaining = self.deadline - self._clock()
        if self.blocked or remaining <= 0:
            raise ProviderError("execution_budget_exhausted")
        return remaining

    def begin(self, kind: OperationKind) -> int:
        self.remaining_seconds()
        if self.operations[kind] >= self._operation_limits[kind]:
            raise ProviderError("operation_budget_exhausted")
        self.operations[kind] += 1
        return self.operations[kind]

    def reserve(self, kind: OperationKind, count: TokenCount, output: int) -> Reservation:
        self.remaining_seconds()
        if (
            self.attempts[kind] >= self._attempt_limits[kind]
            or self.input_charged[kind] + count.units > self._input_limits[kind]
            or self.output_charged + output > self._output_limit
        ):
            raise ProviderError("token_or_attempt_budget_exhausted")
        self.attempts[kind] += 1
        self.input_charged[kind] += count.units
        self.output_charged += output
        return Reservation(kind, count, output)

    def settle(self, reservation: Reservation, usage: UsageReport) -> None:
        if reservation.settled:
            return
        reservation.settled = True
        if (usage.input_tokens is not None and usage.input_tokens > reservation.count.units) or (
            usage.output_tokens is not None and usage.output_tokens > reservation.output
        ):
            self.blocked = True
            raise ProviderError("reported_usage_exceeds_reservation")
        # Missing/partial usage or unknown dispatch outcomes retain the full reservation.
        if usage.complete_for(reservation.kind):
            self.input_charged[reservation.kind] -= reservation.count.units - usage.input_tokens
            if reservation.kind == "chat":
                self.output_charged -= reservation.output - usage.output_tokens

    def record(self, receipt: AttemptReceipt) -> None:
        self._receipts.append(receipt)
