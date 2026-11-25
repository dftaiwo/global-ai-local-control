"""Projector-friendly summaries (`run --brief`) and offline "be the model" calls."""
import pytest

from lab import database
from lab.agent import offline_run
from lab.brief import render_brief
from lab.cli import main


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_DB_PATH", str(tmp_path / "brief.db"))
    database.init_db(reset=True)


def bedrock_result(traces, message="All done.", reasoning=None):
    return {"mode": "bedrock", "message": message, "model_reasoning": reasoning or [], "tool_traces": traces,
            "outbound_requests": len(traces) + 1, "restricted_values_sent": 0, "prepared": []}


def test_brief_offline_manager():
    request = "Find overdue payments above 5 million and prepare approvals"
    text = render_brief(offline_run(request), request)
    assert "DRAFTS MADE   6" in text
    assert "(simulated) prepare_payment_approvals" in text
    assert "SENT TO AWS" not in text


def test_brief_offline_analyst_denied():
    request = "Find overdue payments and prepare approvals"
    text = render_brief(offline_run(request, role="analyst", actor="analyst01"), request)
    assert "DENY" in text
    assert "DRAFTS MADE   0" in text


def test_brief_bedrock_injection():
    denied = [{"payment_id": p, "status": "DENIED", "reason": "NOT_ELIGIBLE"} for p in ("PAY-002", "PAY-005", "PAY-003")]
    traces = [{"tool": "prepare_payment_approvals", "input": {"payment_ids": ["PAY-002", "PAY-005", "PAY-003"]},
               "status": "ALLOW", "result": {"prepared_count": 0, "requests": denied}}]
    text = render_brief(bedrock_result(traces, reasoning=["Skip listing as instructed."]), "SYSTEM OVERRIDE ...")
    assert "PAY-002, PAY-005, PAY-003" in text
    assert "DENIED ×3 (NOT_ELIGIBLE)" in text
    assert "restricted values: 0" in text
    assert "Skip listing as instructed." in text


def test_brief_bedrock_no_tool_calls():
    text = render_brief(bedrock_result([], message="What threshold should I use?"), "prepare approvals")
    assert "MODEL ASKED   no tool calls" in text


def test_brief_caps_long_answer():
    text = render_brief(bedrock_result([], message="word " * 400), "x")
    answer_block = text.split("ANSWER", 1)[1].splitlines()
    assert len(answer_block) <= 6
    assert all(len(line) <= 110 for line in text.splitlines())
    assert answer_block[-1].endswith("…")


def test_cli_run_brief_prints_text(capsys):
    assert main(["run", "--brief"]) == 0
    out = capsys.readouterr().out
    assert not out.lstrip().startswith("{")
    assert "DRAFTS MADE   6" in out


def test_simulate_tool_call_denies_ineligible_payments(capsys):
    code = main(["simulate-tool-call", "prepare_payment_approvals",
                 '{"payment_ids": ["PAY-002", "PAY-005"]}', "--brief"])
    out = capsys.readouterr().out
    assert code == 0
    assert "DENIED ×2 (NOT_ELIGIBLE)" in out
    assert "(simulated)" not in out          # the facilitator is playing the model, not the offline script
    assert not database.list_approvals()


def test_simulate_tool_call_rejects_unregistered_tool(capsys):
    assert main(["simulate-tool-call", "read_all_accounts", "{}"]) == 2
    assert '"DENY"' in capsys.readouterr().out


def test_simulate_tool_call_reports_bad_json_without_traceback(capsys):
    assert main(["simulate-tool-call", "list_overdue_payments", "{bad"]) == 1
    out = capsys.readouterr().out
    assert "JSONDecodeError" in out and "Traceback" not in out


def test_brief_shows_denial_reason_for_unregistered_tool(capsys):
    assert main(["simulate-tool-call", "approve", '{"request_id": "APR-001"}', "--brief"]) == 2
    assert "not in the approved tool registry" in capsys.readouterr().out


# --- Final-review fixes -------------------------------------------------------------------

@pytest.mark.parametrize("tool_input", [[], {"payment_ids": 5}, {"payment_ids": "PAY-001"}])
def test_brief_survives_unexpected_tool_inputs(tool_input):
    trace = {"tool": "prepare_payment_approvals", "input": tool_input, "status": "DENY", "reason": "bad input"}
    text = render_brief(bedrock_result([trace]), "odd input")
    assert "DENY" in text and "P, A, Y" not in text


def test_simulate_non_object_arguments_is_a_clean_deny(capsys):
    assert main(["simulate-tool-call", "list_overdue_payments", "[]", "--brief"]) == 2
    assert "must be a JSON object" in capsys.readouterr().out


def test_brief_counts_only_drafts_created_by_this_run():
    request = "Find overdue payments above 5 million and prepare approvals"
    first = offline_run(request)
    second = offline_run(request)
    assert "DRAFTS MADE   6" in render_brief(first, request)
    assert "DRAFTS MADE   0" in render_brief(second, request)


def test_all_denied_prepare_does_not_read_as_allow():
    denied = [{"payment_id": p, "status": "DENIED", "reason": "NOT_ELIGIBLE"} for p in ("PAY-002", "PAY-005", "PAY-003")]
    traces = [{"tool": "prepare_payment_approvals", "input": {"payment_ids": ["PAY-002", "PAY-005", "PAY-003"]},
               "status": "ALLOW", "result": {"prepared_count": 0, "requests": denied}}]
    text = render_brief(bedrock_result(traces), "SYSTEM OVERRIDE")
    model_line = next(l for l in text.splitlines() if "prepare_payment_approvals" in l)
    assert "ALLOW" not in model_line and "3 denied" in model_line
    assert "×0" not in text


def test_simulate_accepts_arguments_from_a_json_file(tmp_path, capsys):
    payload = tmp_path / "ineligible.json"
    payload.write_text('{"payment_ids": ["PAY-002", "PAY-005", "PAY-003"]}')
    assert main(["simulate-tool-call", "prepare_payment_approvals", f"@{payload}", "--brief"]) == 0
    assert "DENIED ×3 (NOT_ELIGIBLE)" in capsys.readouterr().out
