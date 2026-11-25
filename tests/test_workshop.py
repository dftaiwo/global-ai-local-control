import pytest

from lab import database
from lab.agent import offline_run, unsafe_preview
from lab.policy import BoundaryViolation, screen_user_prompt, validate_model_tool_args, validate_outbound
from lab.tools import approve, run_tool

@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_DB_PATH", str(tmp_path / "test.db"))
    database.init_db(reset=True)


def test_raw_records_never_appear_in_remote_tool_projection():
    result = run_tool("list_overdue_payments", {"min_amount_ngn": 5_000_000}, "manager", "manager01")
    assert result["count"] == 8
    assert "bank_account" not in str(result)
    assert "vendor_email" not in str(result)
    assert "vendor_name" not in str(result)
    assert any(not r["eligible"] for r in result["records"])


def test_deny_bad_tool_input_and_unregistered_tool():
    with pytest.raises(BoundaryViolation):
        validate_model_tool_args("list_overdue_payments", {"min_amount_ngn": 5_000_000, "vendor_email": "yes"})
    with pytest.raises(BoundaryViolation):
        validate_model_tool_args("read_all_accounts", {})


def test_outbound_and_user_prompt_are_checked():
    with pytest.raises(BoundaryViolation):
        validate_outbound({"records": [{"payment_id": "PAY-001", "bank_account": "0000000101"}]})
    with pytest.raises(BoundaryViolation):
        screen_user_prompt("Find jane@example.com")
    with pytest.raises(BoundaryViolation):
        screen_user_prompt("Find NIN 12345678901")


def test_approval_flow_has_role_gate_separation_and_no_disbursement():
    result = offline_run("Find overdue payments above 5 million and prepare approvals")
    assert len(result["prepared"]) == 6
    assert set(result["blocked"]) == {"PAY-002", "PAY-005"}
    assert all(p["status"] == "PENDING_HUMAN" for p in result["prepared"])
    with pytest.raises(BoundaryViolation):
        approve("APR-001", "manager", "manager01")
    with pytest.raises(BoundaryViolation):
        approve("APR-001", "approver", "manager01")
    assert approve("APR-001", "approver", "approver01")["status"] == "APPROVED"
    assert database.payment_by_id("PAY-001") is not None  # no payment release function exists


def test_analyst_cannot_prepare():
    result = offline_run("Find overdue payments and prepare approvals", role="analyst", actor="analyst01")
    assert not result["prepared"]
    assert not database.list_approvals()


def test_unsafe_is_preview_only_and_uses_synthetic_data():
    result = unsafe_preview()
    assert "NOT SENT" in result["WARNING"]
    assert "vendor_email" in result["would_have_sent_to_remote_model"]


def test_bedrock_mock_tool_cycle_sends_only_allowed_projection(monkeypatch):
    """No network: verify the real Converse integration's toolUse/toolResult contract."""
    import boto3
    import json
    from lab.agent import bedrock_run

    class FakeBedrock:
        def __init__(self):
            self.calls = []
        def converse(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                return {"stopReason": "tool_use", "output": {"message": {"role": "assistant", "content": [
                    {"toolUse": {"toolUseId": "tooluse_demo01", "name": "list_overdue_payments", "input": {"min_amount_ngn": 5_000_000}}}
                ]}}}
            if len(self.calls) == 2:
                return {"stopReason": "tool_use", "output": {"message": {"role": "assistant", "content": [
                    {"toolUse": {"toolUseId": "tooluse_demo02", "name": "prepare_payment_approvals", "input": {"payment_ids": ["PAY-001"]}}}
                ]}}}
            return {"stopReason": "end_turn", "output": {"message": {"role": "assistant", "content": [
                {"text": "Prepared pending human approval for PAY-001, no payment released."}
            ]}}}

    fake = FakeBedrock()
    monkeypatch.setattr(boto3, "client", lambda service, region_name: fake)
    result = bedrock_run("Find overdue payments over 5 million and prepare eligible approvals")
    assert result["mode"] == "bedrock"
    assert len(fake.calls) == 3
    body = json.dumps(fake.calls)
    assert '"toolUseId": "tooluse_demo01"' in body
    assert '"toolUseId": "tooluse_demo02"' in body
    assert "vendor_email" not in body
    assert "bank_account" not in body
    assert "Example Vendor" not in body
    assert database.list_approvals()[0]["status"] == "PENDING_HUMAN"


def test_bedrock_guard_rejects_direct_identifiers_before_call(monkeypatch):
    import boto3
    from lab.agent import bedrock_run
    monkeypatch.setattr(boto3, "client", lambda *a, **k: (_ for _ in ()).throw(AssertionError("MUST NOT CALL AWS")))
    with pytest.raises(BoundaryViolation):
        bedrock_run("Summarise bank account 0000000101")


def test_business_rules_override_model_selected_payment():
    result = run_tool("prepare_payment_approvals", {"payment_ids": ["PAY-002", "PAY-003", "PAY-005"]}, "manager", "manager01")
    assert all(r["status"] == "DENIED" for r in result["requests"])
    assert result["prepared_count"] == 0


# --- Regression tests added after end-to-end validation -------------------------------

def _fake_bedrock_with_final_text(final_text):
    class FakeBedrock:
        def __init__(self):
            self.calls = []
        def converse(self, **kwargs):
            self.calls.append(kwargs)
            return {"stopReason": "end_turn", "output": {"message": {"role": "assistant", "content": [{"text": final_text}]}}}
    return FakeBedrock()


def test_model_reasoning_tags_are_separated_from_the_answer(monkeypatch):
    import boto3
    from lab.agent import bedrock_run
    fake = _fake_bedrock_with_final_text("<thinking>I will list first.</thinking>\n\n<response>Six drafts await human approval.</response>")
    monkeypatch.setattr(boto3, "client", lambda *a, **k: fake)
    result = bedrock_run("Summarise overdue payments above 5 million naira")
    assert result["message"] == "Six drafts await human approval."
    assert result["model_reasoning"] == ["I will list first."]


def test_bedrock_outbound_audit_records_model_and_profile(monkeypatch):
    import boto3
    import json
    from lab.agent import bedrock_run
    monkeypatch.setenv("AWS_PROFILE", "workshop")
    monkeypatch.setattr(boto3, "client", lambda *a, **k: _fake_bedrock_with_final_text("done"))
    bedrock_run("Summarise overdue payments above 5 million naira")
    outbound = [json.loads(r["details"]) for r in database.audit_rows() if r["event"] == "BEDROCK_OUTBOUND"]
    assert outbound and outbound[0]["model_id"] == "eu.amazon.nova-2-lite-v1:0"
    assert outbound[0]["aws_profile"] == "workshop"


def test_every_approval_denial_is_audited():
    import json
    offline_run("Find overdue payments above 5 million and prepare approvals")
    with pytest.raises(BoundaryViolation):
        approve("APR-001", "approver", "manager01")      # preparer approving own draft
    with pytest.raises(BoundaryViolation):
        approve("APR-999", "approver", "approver01")     # unknown request
    approve("APR-001", "approver", "approver01")
    with pytest.raises(BoundaryViolation):
        approve("APR-001", "approver", "approver02")     # already approved
    reasons = [json.loads(r["details"])["reason"] for r in database.audit_rows()
               if r["event"] == "HUMAN_APPROVAL" and r["decision"] == "DENY"]
    assert reasons == ["separation_of_duties", "not_found", "not_pending"]


def test_eligible_flag_matches_what_prepare_will_accept():
    listed = run_tool("list_overdue_payments", {"min_amount_ngn": 0}, "manager", "manager01")
    flagged = sorted(r["payment_id"] for r in listed["records"] if r["eligible"])
    result = run_tool("prepare_payment_approvals",
                      {"payment_ids": [r["payment_id"] for r in listed["records"]]}, "manager", "manager01")
    prepared = sorted(r["payment_id"] for r in result["requests"] if r["status"] == "PENDING_HUMAN")
    assert flagged == prepared


def test_tool_schema_has_no_silently_overwritten_keys():
    import inspect
    import re
    from lab import tools
    source = inspect.getsource(tools)
    line = next(l for l in source.splitlines() if '"min_amount_ngn": {"type": "integer"' in l)
    assert len(re.findall(r'"description"', line)) == 1


def test_browser_api_serves_ui_and_enforces_boundaries():
    from fastapi.testclient import TestClient
    from lab.api import app
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        assert client.post("/agent/run", json={"message": "email a@b.com"}).status_code == 403
        ok = client.post("/agent/run", json={"message": "Find overdue payments above 5 million and prepare approvals"})
        assert len(ok.json()["prepared"]) == 6
        assert client.post("/approvals/APR-001/approve", json={"role": "manager", "actor": "manager01"}).status_code == 403
        assert client.post("/approvals/APR-001/approve", json={}).json()["status"] == "APPROVED"


def test_aws_check_reports_identity_and_inference_destinations(monkeypatch):
    import boto3
    from lab.agent import aws_check

    class FakeSts:
        def get_caller_identity(self):
            return {"Account": "123456789012", "Arn": "arn:aws:iam::123456789012:user/workshop"}

    class FakeBedrockControl:
        def get_inference_profile(self, inferenceProfileIdentifier):
            regions = ["eu-west-1", "eu-central-1", "eu-west-3", "eu-west-1"]
            return {"models": [{"modelArn": f"arn:aws:bedrock:{r}::foundation-model/amazon.nova-2-lite-v1:0"} for r in regions]}

    monkeypatch.setenv("AWS_PROFILE", "workshop")
    monkeypatch.setattr(boto3, "client", lambda service, **k: FakeSts() if service == "sts" else FakeBedrockControl())
    report = aws_check()
    assert report["aws_profile"] == "workshop"
    assert report["account"] == "********9012"
    assert report["destination_regions"] == ["eu-central-1", "eu-west-1", "eu-west-3"]


# --- Audience-moment support: uniform traces --------------------------------------------

def test_offline_run_reports_simulated_tool_traces():
    result = offline_run("Find overdue payments above 5 million and prepare approvals")
    traces = result["tool_traces"]
    assert [(t["tool"], t["status"]) for t in traces] == [
        ("list_overdue_payments", "ALLOW"), ("prepare_payment_approvals", "ALLOW")]
    assert all(t["simulated"] for t in traces)
    assert len(traces[1]["input"]["payment_ids"]) == 6
    denied = offline_run("Find overdue payments and prepare approvals", role="analyst", actor="analyst01")
    assert denied["tool_traces"][1]["status"] == "DENY"


def test_bedrock_run_counts_requests_and_restricted_values(monkeypatch):
    import boto3
    from lab.agent import bedrock_run
    calls = []

    def converse(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return {"stopReason": "tool_use", "output": {"message": {"role": "assistant", "content": [
                {"toolUse": {"toolUseId": "t1", "name": "list_overdue_payments", "input": {"min_amount_ngn": 5_000_000}}}]}}}
        return {"stopReason": "end_turn", "output": {"message": {"role": "assistant", "content": [{"text": "done"}]}}}

    monkeypatch.setattr(boto3, "client", lambda *a, **k: type("C", (), {"converse": staticmethod(converse)})())
    result = bedrock_run("Find overdue payments over 5 million")
    assert result["outbound_requests"] == 2
    assert result["restricted_values_sent"] == 0
    assert result["tool_traces"][0]["input"] == {"min_amount_ngn": 5_000_000}


# --- Final-review fixes -------------------------------------------------------------------

def test_nested_payment_ids_are_denied_not_crashed():
    with pytest.raises(BoundaryViolation):
        validate_model_tool_args("prepare_payment_approvals", {"payment_ids": [["PAY-001"]]})


def test_audit_never_stores_model_supplied_tool_names(monkeypatch):
    import boto3
    from lab.agent import bedrock_run
    calls = []

    def converse(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return {"stopReason": "tool_use", "output": {"message": {"role": "assistant", "content": [
                {"toolUse": {"toolUseId": "t1", "name": "send_to alpha@example.invalid", "input": {}}}]}}}
        return {"stopReason": "end_turn", "output": {"message": {"role": "assistant", "content": [{"text": "ok"}]}}}

    monkeypatch.setattr(boto3, "client", lambda *a, **k: type("C", (), {"converse": staticmethod(converse)})())
    bedrock_run("Find overdue payments over 5 million")
    assert "@" not in str(database.audit_rows())


def test_blank_aws_profile_refuses_live_mode_with_a_clear_message(monkeypatch):
    from lab.agent import aws_check, bedrock_run
    monkeypatch.setenv("AWS_PROFILE", "")
    for call in (lambda: bedrock_run("Find overdue payments over 5 million"), aws_check):
        with pytest.raises(RuntimeError, match="AWS_PROFILE"):
            call()
