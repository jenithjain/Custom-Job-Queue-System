
# main.py
# -------
# FastAPI app for submitting “send_email” jobs with high/low priority,
# storing them in Redis, and exposing endpoints to enqueue and check status.
from typing import Literal
from pydantic import BaseModel, EmailStr, Field
from datetime import datetime
import uuid
import json
import os

import redis
from fastapi import FastAPI, HTTPException, status
from dotenv import load_dotenv

# 1) Load environment variables from .env
load_dotenv()
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB   = int(os.getenv("REDIS_DB",   "0"))

# 2) Initialize Redis client (decode_responses=True returns strings, not bytes)
r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)

# 3) Initialize FastAPI
app = FastAPI(
    title="Custom Job Queue API",
    description="Submit & track high/low priority 'send_email' jobs in Redis",
    version="1.0.0"
)

# --- 4. Pydantic models for request/response validation ---

class JobPayload(BaseModel):
    to: EmailStr
    subject: str = Field(min_length=1, max_length=255)
    message: str = Field(min_length=1)


class JobRequest(BaseModel):
    job_type: Literal["send_email"]
    priority: Literal["high", "low"]
    payload: JobPayload


class JobStatusResponse(BaseModel):
    job_id: str
    job_type: str
    priority: str
    payload: JobPayload
    status: Literal["pending", "processing", "completed", "failed"]
    retry_count: int
    created_ts: datetime
    picked_ts: datetime | None     = None
    completed_ts: datetime | None  = None
    available_after: datetime


# --- 5. Helper functions ---

def _current_utc_iso() -> str:
    return datetime.utcnow().isoformat()


def _make_job_entry(data: JobRequest) -> tuple[str, dict[str, str]]:
    """
    Create a new Redis hash key and dictionary for this job.
    All values are stored as strings.
    """
    job_id = str(uuid.uuid4())
    now_iso = _current_utc_iso()
    job_hash_key = f"jobs:hash:{job_id}"

    job = {
        "job_id": job_id,
        "job_type": data.job_type,
        "priority": data.priority,
        # Store payload as a JSON string
        "payload": data.payload.json(),
        "status": "pending",
        "retry_count": "0",
        "created_ts": now_iso,
        "picked_ts": "",
        "completed_ts": "",
        "available_after": now_iso
    }
    return job_hash_key, job


def _enqueue_job(job_hash_key: str, job: dict[str, str]) -> None:
    """
    Save the job in Redis and push its ID onto the high- or low-priority list.
    """
    # 1) Save the hash
    r.hset(job_hash_key, mapping=job)

    # 2) Push job_id onto the appropriate priority queue
    if job["priority"] == "high":
        r.lpush("jobs:queue:high", job["job_id"])
    else:
        r.lpush("jobs:queue:low", job["job_id"])


def _parse_job_hash_to_response(job_hash: dict[str, str]) -> JobStatusResponse:
    """
    Convert a Redis hash (all fields are strings) into a JobStatusResponse.
    Timestamps are ISO strings; "" → None.
    """
    # Parse payload JSON string back to dict
    payload_dict = json.loads(job_hash["payload"])

    def _parse_ts(field: str) -> datetime | None:
        val = job_hash.get(field, "")
        return datetime.fromisoformat(val) if val else None

    return JobStatusResponse(
        job_id          = job_hash["job_id"],
        job_type        = job_hash["job_type"],
        priority        = job_hash["priority"],
        payload         = JobPayload(**payload_dict),
        status          = job_hash["status"],
        retry_count     = int(job_hash["retry_count"]),
        created_ts      = datetime.fromisoformat(job_hash["created_ts"]),
        picked_ts       = _parse_ts("picked_ts"),
        completed_ts    = _parse_ts("completed_ts"),
        available_after = datetime.fromisoformat(job_hash["available_after"])
    )

# --- 6. API Endpoints ---

@app.post(
    "/submit-job",
    status_code=status.HTTP_201_CREATED,
    response_model=dict[str, str],
    summary="Submit a new 'send_email' job (high or low priority)"
)
async def submit_job(job_req: JobRequest):
    """
    Request JSON body must be:
    {
      "job_type": "send_email",
      "priority": "high" | "low",
      "payload": {
        "to": "user@example.com",
        "subject": "Hello",
        "message": "Test email."
      }
    }

    Returns (201):
    { "job_id": "<uuid>", "status": "enqueued" }
    """
    job_hash_key, job = _make_job_entry(job_req)
    _enqueue_job(job_hash_key, job)
    return {"job_id": job["job_id"], "status": "enqueued"}


@app.get(
    "/jobs/status/{job_id}",
    response_model=JobStatusResponse,
    summary="Get current status of a job"
)
async def job_status(job_id: str):
    """
    Path parameter: job_id (UUID)

    If the job exists, returns JSON like:
    {
      "job_id": "...",
      "job_type": "send_email",
      "priority": "high",
      "payload": { "to":"...","subject":"...","message":"..." },
      "status": "pending" | "processing" | "completed" | "failed",
      "retry_count": 0 | 1 | 2 | 3,
      "created_ts": "2025-06-02T08:20:00.123456",
      "picked_ts": null | "2025-06-02T08:20:05.123456",
      "completed_ts": null | "2025-06-02T08:20:07.123789",
      "available_after": "2025-06-02T08:20:00.123456"
    }

    If not found, returns 404.
    """
    job_key = f"jobs:hash:{job_id}"
    if not r.exists(job_key):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found"
        )
    job_hash = r.hgetall(job_key)
    return _parse_job_hash_to_response(job_hash)
