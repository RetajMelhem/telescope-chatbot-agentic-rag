"""Operational failure labels must stay useful without accepting arbitrary content."""

import json
import logging

import pytest

from telescope_rag.core.logging import SafeJsonFormatter, safe_workflow_failure


@pytest.mark.parametrize("unsafe", ["SYNTHETIC-PRIVATE-CONTENT", None, [], {"secret": "value"}])
def test_failure_diagnostics_reject_arbitrary_or_malformed_values(unsafe):
    values = safe_workflow_failure(
        failure_code=unsafe, failure_stage=unsafe, provider_outcome=unsafe
    )
    assert set(values.values()) == {"unknown"}
    record = logging.LogRecord(
        "telescope_rag", logging.WARNING, "", 0, "chat_workflow_failed", (), None
    )
    record.failure_code = record.failure_stage = record.provider_outcome = unsafe
    rendered = json.loads(SafeJsonFormatter().format(record))
    assert all(rendered[key] == "unknown" for key in values)
    assert "secret" not in json.dumps(rendered) and "PRIVATE" not in json.dumps(rendered)


def test_failure_event_retains_only_closed_diagnostic_fields():
    record = logging.LogRecord(
        "telescope_rag", logging.WARNING, "", 0, "chat_workflow_failed", ("SYNTHETIC-SECRET",), None
    )
    record.request_id = "synthetic-request"
    record.failure_code = "provider_failed"
    record.failure_stage = "generate_draft"
    record.provider_outcome = "structured_output_invalid"
    record.body = record.headers = "SYNTHETIC-SECRET"
    rendered = SafeJsonFormatter().format(record)
    data = json.loads(rendered)
    assert data["event"] == "chat_workflow_failed"
    assert data["failure_code"] == "provider_failed"
    assert data["failure_stage"] == "generate_draft"
    assert data["provider_outcome"] == "structured_output_invalid"
    assert "SYNTHETIC-SECRET" not in rendered
