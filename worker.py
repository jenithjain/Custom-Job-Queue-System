# worker.py
# ---------
# Worker process that continuously polls Redis for jobs,
# processes them in strict priority order (high then low),
# and implements exponential backoff (max 3 retries) for “send_email”.

import redis
import time
import json
import datetime
import random
import os

from dotenv import load_dotenv

# 1) Load environment variables from .env
load_dotenv()
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB   = int(os.getenv("REDIS_DB",   "0"))

# 2) Initialize Redis client
r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)

# 3) Base delay (in seconds) for exponential backoff
BACKOFF_BASE = 1

def _current_utc_iso() -> str:
    return datetime.datetime.utcnow().isoformat()

def _fetch_next_job_id() -> str | None:
    """
    Attempt to pop from high-priority queue first; if empty, pop from low.
    Returns job_id (string) or None if both are empty.
    """
    job_id = r.rpop("jobs:queue:high")
    if job_id:
        return job_id
    job_id = r.rpop("jobs:queue:low")
    return job_id  # could be None

def _get_job_hash(job_id: str) -> dict[str, str] | None:
    """
    Return the Redis hash for this job_id, or None if not found.
    """
    job_key = f"jobs:hash:{job_id}"
    if not r.exists(job_key):
        return None
    return r.hgetall(job_key)

def _should_run(job: dict[str, str]) -> bool:
    """
    Compare job['available_after'] vs. now.
    Return True if now >= available_after, else False.
    """
    avail = datetime.datetime.fromisoformat(job["available_after"])
    return avail <= datetime.datetime.utcnow()

def _update_job_field(job_id: str, field: str, value: str) -> None:
    """
    Set a single field in the job's Redis hash.
    """
    job_key = f"jobs:hash:{job_id}"
    r.hset(job_key, field, value)

def _requeue_job(job_id: str, priority: str) -> None:
    """
    LPUSH job_id back into the appropriate queue.
    Since the worker does RPOP, LPUSH puts it at the tail (i.e., oldest).
    """
    if priority == "high":
        r.lpush("jobs:queue:high", job_id)
    else:
        r.lpush("jobs:queue:low", job_id)

def process_job(job_id: str) -> None:
    """
    1) Load job hash
    2) If not ready (available_after > now), requeue and return
    3) Mark status="processing", set picked_ts
    4) Simulate send_email: sleep 2s + 20% random failure
    5) On success: set status="completed", completed_ts
    6) On failure: increment retry_count, if <3 schedule next backoff & requeue; else mark failed
    """
    job_key = f"jobs:hash:{job_id}"
    job = _get_job_hash(job_id)
    if job is None:
        print(f"[Worker] Job {job_id} not found. Skipping.")
        return

    # 2) Check backoff
    if not _should_run(job):
        _requeue_job(job_id, job["priority"])
        return

    # 3) Mark as processing
    _update_job_field(job_id, "status", "processing")
    _update_job_field(job_id, "picked_ts", _current_utc_iso())

    # 4) Simulate send_email
    try:
        payload = json.loads(job["payload"])
        print(f"[Worker] Processing job {job_id} → sending email to {payload['to']} ...")
        time.sleep(2)  # simulate work

        # Simulate 20% chance of failure
        if random.random() < 0.2:
            raise Exception("Simulated random failure")

        # Success:
        _update_job_field(job_id, "status", "completed")
        _update_job_field(job_id, "completed_ts", _current_utc_iso())
        print(f"[Worker] Job {job_id} COMPLETED successfully.")

    except Exception:
        # 5) Failure path: increment retry_count
        old_retries = int(job["retry_count"])
        new_retries = old_retries + 1
        _update_job_field(job_id, "retry_count", str(new_retries))

        if new_retries < 3:
            # Schedule a retry with exponential backoff
            delay_secs = BACKOFF_BASE * (2 ** (new_retries - 1))  # 1s, 2s, 4s
            next_avail = (datetime.datetime.utcnow() + datetime.timedelta(seconds=delay_secs)).isoformat()
            _update_job_field(job_id, "status", "pending")
            _update_job_field(job_id, "available_after", next_avail)
            _requeue_job(job_id, job["priority"])
            print(
                f"[Worker] Job {job_id} FAILED (attempt {new_retries}). "
                f"Retrying after {delay_secs}s at {next_avail}."
            )
        else:
            # Permanent failure
            _update_job_field(job_id, "status", "failed")
            _update_job_field(job_id, "completed_ts", _current_utc_iso())
            print(f"[Worker] Job {job_id} PERMANENTLY FAILED after {new_retries} attempts.")


if __name__ == "__main__":
    print("[Worker] Starting worker loop. Listening for jobs...")
    while True:
        job_id = _fetch_next_job_id()
        if job_id:
            process_job(job_id)
        else:
            time.sleep(1)
