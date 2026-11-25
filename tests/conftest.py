import os

import pytest


@pytest.fixture(autouse=True)
def no_accidental_aws(monkeypatch):
    """The offline suite must never reach AWS. Tests that need boto3 patch it themselves."""
    monkeypatch.delenv("AGENT_MODE", raising=False)   # .env may set bedrock; the offline suite stays offline
    if os.getenv("RUN_LIVE_AWS") == "1":
        return
    import boto3

    def refuse(*args, **kwargs):
        raise AssertionError("Offline test attempted a real AWS call")

    monkeypatch.setattr(boto3, "client", refuse)
