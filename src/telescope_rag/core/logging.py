"""Application logs include only explicitly selected non-content fields."""

import json
import logging
from datetime import UTC, datetime

SAFE_EVENTS = frozenset(
    {
        "request_completed",
        "adapter_cleanup_timed_out",
        "adapter_cleanup_failed",
        "chat_workflow_failed",
    }
)

WORKFLOW_FAILURE_FIELDS = {
    "failure_code": frozenset(
        {
            "provider_failed",
            "deadline_exceeded",
            "workflow_failed",
            "planning_failed",
            "invalid_plan",
            "invalid_hours_plan",
            "invalid_hours_input",
            "retrieval_failed",
            "assembly_failed",
            "generation_failed",
            "invalid_draft",
            "invalid_conversational_answer",
            "invalid_conversational_coverage",
            "invalid_conversational_citation",
            "invalid_conversational_fixed_outcome",
            "invalid_conversational_unknown",
            "invalid_conversational_hours_outcome",
            "invalid_source_page_choices",
        }
    ),
    "failure_stage": frozenset(
        {
            "validate_request",
            "plan_query",
            "validate_plan",
            "retrieve_evidence",
            "assemble_evidence",
            "generate_draft",
            "validate_draft",
            "finalize_safe",
        }
    ),
    "provider_outcome": frozenset(
        {
            "success",
            "structured_output_invalid",
            "truncated_completion",
            "invalid_provider_json",
            "invalid_provider_usage",
            "invalid_chat_response",
            "missing_structured_output",
            "unexpected_completion_kind",
            "provider_timeout",
            "provider_connection_failed",
            "provider_transport_error",
            "provider_protocol_error",
            "provider_error_response",
            "reported_model_mismatch",
            "missing_reported_model",
            "provider_refusal",
            "provider_request_rejected",
            "provider_authentication_failed",
            "provider_credit_unavailable",
            "provider_model_unavailable",
            "provider_rate_limited",
            "provider_unavailable",
            "provider_http_error",
            "not_attempted",
        }
    ),
}


def safe_workflow_failure(**values: str) -> dict[str, str]:
    """Closed labels only, never upstream exception text or request content."""
    return {
        name: values.get(name)
        if type(values.get(name)) is str and values.get(name) in allowed
        else "unknown"
        for name, allowed in WORKFLOW_FAILURE_FIELDS.items()
    }


class SafeJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "event": record.msg
            if isinstance(record.msg, str) and record.msg in SAFE_EVENTS
            else "application_event",
        }
        for name in ("request_id", "route", "status_code", "duration_ms"):
            if hasattr(record, name):
                payload[name] = getattr(record, name)
        if record.msg == "chat_workflow_failed":
            payload.update(
                safe_workflow_failure(
                    **{name: getattr(record, name, "unknown") for name in WORKFLOW_FAILURE_FIELDS}
                )
            )
        # Deliberately omit message args, exc_info, HTTP headers, URLs, and bodies.
        return json.dumps(payload)


def configure_logging(level: str) -> logging.Logger:
    logger = logging.getLogger("telescope_rag")
    logger.setLevel(level)
    logger.propagate = False
    if not any(getattr(handler, "telescope_safe", False) for handler in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(SafeJsonFormatter())
        handler.telescope_safe = True
        logger.addHandler(handler)
    return logger
