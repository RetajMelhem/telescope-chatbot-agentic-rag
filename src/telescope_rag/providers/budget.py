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
    count: TokenCount | None
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
        self._reported_chat = settings.chat_input_accounting == "reported_usage"
        self._chat_reservation_mode: str | None = None
        self._reported_chat_pending = 0
        self._reported_chat_known = 0
        self._reported_chat_unknown = False
        self.operations = {"chat": 0, "embedding": 0}
        self.attempts = {"chat": 0, "embedding": 0}
        self.input_charged: dict[OperationKind, int | None] = {"chat": 0, "embedding": 0}
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
        if kind == "chat" and self._chat_reservation_mode == "reported_usage":
            raise ProviderError("mixed_chat_accounting_modes")
        charged = self.input_charged[kind]
        if (
            charged is None
            or self.attempts[kind] >= self._attempt_limits[kind]
            or charged + count.units > self._input_limits[kind]
            or self.output_charged + output > self._output_limit
        ):
            raise ProviderError("token_or_attempt_budget_exhausted")
        self.attempts[kind] += 1
        if kind == "chat":
            self._chat_reservation_mode = "strict"
        self.input_charged[kind] = charged + count.units
        self.output_charged += output
        return Reservation(kind, count, output)

    def reserve_reported_chat(self, output: int) -> Reservation:
        """Reserve output/attempts, honestly leaving input unknown until usage.

        There is no input-token ceiling enforcement in this mode. Request bytes
        are bounded by the adapter, never converted into invented token units.
        """
        self.remaining_seconds()
        if not self._reported_chat:
            raise ProviderError("reported_chat_accounting_not_enabled")
        if self._chat_reservation_mode == "strict":
            raise ProviderError("mixed_chat_accounting_modes")
        if type(output) is not int or output < 1:
            raise ProviderError("invalid_output_limit")
        if (
            self.attempts["chat"] >= self._operation_limits["chat"]
            or self.output_charged + output > self._output_limit
        ):
            raise ProviderError("token_or_attempt_budget_exhausted")
        self._chat_reservation_mode = "reported_usage"
        self._reported_chat_pending += 1
        self.input_charged["chat"] = None
        self.attempts["chat"] += 1
        self.output_charged += output
        return Reservation("chat", None, output)

    def settle(self, reservation: Reservation, usage: UsageReport) -> None:
        if reservation.settled:
            return
        reservation.settled = True
        if reservation.count is None:
            if reservation.kind != "chat" or not self._reported_chat:
                self.blocked = True
                raise ProviderError("invalid_reported_usage_reservation")
            self._reported_chat_pending -= 1
            if usage.input_tokens is None:
                self._reported_chat_unknown = True
            else:
                self._reported_chat_known += usage.input_tokens
            self.input_charged["chat"] = (
                None
                if self._reported_chat_pending or self._reported_chat_unknown
                else self._reported_chat_known
            )
            if usage.output_tokens is not None:
                if usage.output_tokens > reservation.output:
                    self.blocked = True
                    raise ProviderError("reported_usage_exceeds_reservation")
                self.output_charged -= reservation.output - usage.output_tokens
            return
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
