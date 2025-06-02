# Custom Job Queue System  
**Priority-based “send_email” jobs with FastAPI & Redis**  

<p align="center">
  <img src="https://img.shields.io/badge/python-3.8%2B-blue" alt="Python 3.8+">
  <img src="https://img.shields.io/badge/fastapi-v0.98.0-green" alt="FastAPI">
  <img src="https://img.shields.io/badge/redis-v5.0-yellow" alt="Redis">
  <img src="https://img.shields.io/badge/license-MIT-brightgreen" alt="License">
</p>

---
# Demo Video 


https://github.com/user-attachments/assets/bfa84f5c-493e-41a4-b987-d9ea2a81ff5e

## Project Overview

This project implements a **custom job queue system** using:

- **FastAPI** for a simple REST API (submit jobs & query status).  
- **Redis** as the persistent backing store (hashes for metadata, lists for priority queues).  
- A standalone **Python worker** that continuously polls Redis, processes jobs in strict priority order (high before low), and implements **exponential backoff** (1s → 2s → 4s) on failures (max 3 retries).

The only job type supported initially is `"send_email"`, where the worker simply `sleep(2)` to simulate email sending. However, the design is easily extensible to additional job types (e.g., image processing, report generation).

---

## Architecture

1. **Client (Swagger UI / curl / Postman)**  
   - Calls `POST /submit-job` with JSON `{ job_type, priority, payload }`.  
   - Receives a `job_id` immediately.  
   - Polls `GET /jobs/status/{job_id}` to track job.

2. **FastAPI Server (`main.py`)**  
   - Validates requests with **Pydantic** (ensuring `job_type == "send_email"`, `priority` is `"high"` or `"low"`, and `payload.to` is a valid email).  
   - Stores each job in a Redis hash:  
     ```
     Key:   jobs:hash:{job_id}
     Fields:
       job_id, job_type, priority, payload (JSON string),
       status ("pending"/"processing"/"completed"/"failed"),
       retry_count, created_ts, picked_ts, completed_ts, available_after
     ```
   - Enqueues `job_id` onto either `jobs:queue:high` or `jobs:queue:low` (Redis lists).  
   - Exposes:
     - `POST /submit-job → 201 Created`  
     - `GET  /jobs/status/{job_id} → 200 OK or 404 Not Found`

3. **Redis**  
   - **Hashes (`jobs:hash:{job_id}`)** store all job metadata.  
   - **Lists**:
     - `jobs:queue:high` (LPUSH new high-priority `job_id`)  
     - `jobs:queue:low`  (LPUSH new low-priority `job_id`)

4. **Worker (`worker.py`)**  
   - In an infinite loop:  
     1. `RPOP jobs:queue:high` (if not empty) else `RPOP jobs:queue:low`.  
     2. Load job hash. If `available_after > now`, re-enqueue and skip.  
     3. Mark `status="processing"` & set `picked_ts`.  
     4. Simulate work: `sleep(2)` + 20% chance of “failure.”  
     5. **On Success**: update `status="completed"`, set `completed_ts`.  
     6. **On Failure**: increment `retry_count`.  
        - If `< 3`, compute backoff delay (`1s, 2s, 4s`), set `status="pending"`, update `available_after`, re-enqueue.  
        - If `== 3`, set `status="failed"`, set `completed_ts`.

---

## Features

- 🏷️ **Priority Queues**: High vs. Low priority in Redis lists (strict ordering).  
- 🔄 **Retry & Exponential Backoff**: 3 attempts with delays (1s → 2s → 4s).  
- 📦 **FastAPI + Pydantic**: Automatic data validation & Swagger documentation.  
- ⚡ **Simple Worker**: Single Python script that can be horizontally scaled to multiple instances.  
- 🔍 **Status Endpoint**: Clients can poll `GET /jobs/status/{job_id}` for full job metadata.  
- 🖥️ **Interactive API Docs**: `http://localhost:8000/docs` (Swagger UI) & `/redoc` (ReDoc).  

---

## Prerequisites

- **Python 3.8+** installed and in `PATH`.  
- **Redis** installed & running (default: `localhost:6379`).  
- Familiarity with `pip`, virtual environments, and using a terminal (PowerShell / bash).  

---

## Getting Started
## 🚀 How to Run This Project

Follow these steps to set up and run the custom job queue system locally:

---

### 🔧 1. **Clone the Repository**

```bash
git clone https://github.com/your-username/custom-job-queue.git
cd custom-job-queue

python -m venv venv
.\venv\Scripts\Activate.ps1

pip install --upgrade pip
pip install -r requirements.txt


```
#  Start Redis Server (30 seconds)

```bash
cd path\to\Redis
.\redis-server.exe
```
# Start the Worker Process 

```bash
python worker.py
[Worker] Starting worker loop. Listening for jobs…
```
# Start the FastAPI Server

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Swagger UI (interactive docs): http://localhost:8000/docs


