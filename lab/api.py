"""Optional browser demo. NOT production authentication; never expose publicly."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import database
from .agent import bedrock_run, offline_run
from .policy import BoundaryViolation
from .tools import approve

load_dotenv()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    database.init_db()
    yield


app = FastAPI(title="Global AI. Local Control. - Workshop Demo", lifespan=lifespan)

class RunRequest(BaseModel):
    message: str = Field(min_length=1, max_length=600)
    backend: Literal["offline", "bedrock"] = "offline"
    role: Literal["analyst", "manager", "approver"] = "manager"
    actor: str = "manager01"
    min_amount_ngn: int = 5_000_000

class ApproveRequest(BaseModel):
    actor: str = "approver01"
    role: Literal["analyst", "manager", "approver"] = "approver"

@app.get("/")
def home():
    return FileResponse(Path(__file__).parent / "static" / "index.html")

@app.get("/health")
def health():
    return {"ok": True, "note": "Local synthetic demo; AWS off by default."}

@app.post("/agent/run")
def run_agent(req: RunRequest):
    try:
        if req.backend == "bedrock":
            return bedrock_run(req.message, role=req.role, actor=req.actor)
        return offline_run(req.message, role=req.role, actor=req.actor, min_amount=req.min_amount_ngn)
    except BoundaryViolation as exc:
        raise HTTPException(403, detail=str(exc)) from exc
    except Exception as exc:
        # Avoid reflecting internal error details in a production-facing API.
        raise HTTPException(503, detail=f"Demo backend unavailable: {type(exc).__name__}") from exc

@app.get("/approvals")
def get_approvals():
    return database.list_approvals()

@app.post("/approvals/{request_id}/approve")
def human_approve(request_id: str, req: ApproveRequest):
    try:
        return approve(request_id, req.role, req.actor)
    except BoundaryViolation as exc:
        raise HTTPException(403, detail=str(exc)) from exc

@app.get("/audit")
def audit():
    return database.audit_rows()
