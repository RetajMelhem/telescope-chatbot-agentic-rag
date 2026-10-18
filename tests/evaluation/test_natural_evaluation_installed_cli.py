"""The public runner selects the installed HTTP path and preserves failed receipts."""

import asyncio
import json
import sys

import pytest

from scripts import natural_evaluation as runner
from scripts import natural_evaluation_portable as portable


@pytest.mark.parametrize("failed", [False, True])
def test_installed_execution_binds_receipts_even_after_a_failed_run(tmp_path, monkeypatch, failed):
    plan_dir, output = tmp_path / "plan", tmp_path / "run"
    plan_dir.mkdir()
    runner.write_new(plan_dir / "plan.json", {})
    plan = {
        "transport_kind": "installed_portable_http",
        "requests_sha256": "synthetic",
        "prepared_digest": "synthetic",
        "transport": "HTTP",
    }
    monkeypatch.setattr(runner, "verify_plan", lambda *args: plan)
    monkeypatch.setattr(runner, "requests_from", lambda *args: [{"case_id": "U01-en"}])

    async def fake_run(directory, selected_plan, installation, destination, requests, limit):
        assert directory == plan_dir and selected_plan == plan and limit == 1
        destination.mkdir()
        runner.write_new(destination / "execution-index.json", {"attempted_cases": 0})
        for name in ("preflight-before.json", "http-preflight.json", "preflight-after.json"):
            runner.write_new(destination / name, {"status": "failed" if failed else "verified"})
        if failed:
            raise ValueError("installation_changed_during_run")

    monkeypatch.setattr(portable, "run_portable", fake_run)
    operation = runner.execute_installed(tmp_path, plan_dir, tmp_path / "installed", output, 1)
    if failed:
        with pytest.raises(ValueError, match="installation_changed_during_run"):
            asyncio.run(operation)
    else:
        asyncio.run(operation)
    binding = json.loads((output / "run-binding.json").read_bytes())
    assert binding["execution_kind"] == "installed_portable_http"
    assert len(binding["installed_receipts_sha256"]) == 3
    assert binding["index_sha256"] == runner.digest(output / "execution-index.json")


def test_installed_execution_rejects_a_host_plan_before_creating_a_client(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "verify_plan", lambda *args: {"transport_kind": "asgi"})
    with pytest.raises(ValueError, match="plan_does_not_target_installed_release"):
        asyncio.run(runner.execute_installed(tmp_path, tmp_path, tmp_path, tmp_path / "run", 50))
    assert not (tmp_path / "run").exists()


def test_cli_run_selects_installed_transport(tmp_path, monkeypatch):
    received = []

    async def installed(*args):
        received.append(args)

    monkeypatch.setattr(runner, "execute_installed", installed)
    monkeypatch.setattr(
        sys,
        "argv",
        ["eval", "run", "--plan", str(tmp_path), "--output", str(tmp_path / "run"), "--execute"],
    )
    runner.main()
    assert len(received) == 1 and received[0][-1] == 50


@pytest.mark.parametrize(
    "arguments",
    [
        ["run", "--plan", "plan"],
        ["run", "--execute"],
        ["preflight", "--plan", "plan", "--execute"],
        ["score", "--plan", "plan", "--run", "run", "--execute"],
    ],
)
def test_cli_rejects_invalid_execution_flags_before_work(monkeypatch, arguments):
    monkeypatch.setattr(sys, "argv", ["eval", *arguments, "--output", "unused"])
    with pytest.raises(SystemExit) as error:
        runner.main()
    assert error.value.code == 2
