# Pulse — a job queue service built to be observed

A small HTTP service that accepts jobs, works through them in the background, publishes
numbers about itself, and can be made to fail on command.

The point is not the service. The point is being able to **see** what it is doing.

---

## Why this exists

A growing backlog, a slow endpoint, a memory leak: none of these are visible by looking
at an application. They are only visible in a graph over time.

So this project builds the graph first, then breaks the service on purpose to prove the
graph shows it.

Most portfolio projects demonstrate that something can be *built*. This one is about
being able to *operate* something — notice a problem, measure it, and prove what happened.

---

## Status

| Phase | What | State |
|---|---|---|
| 0 | Confirm the ground | done |
| 1 | Skeleton — `/`, `/healthz`, `/readyz` | done |
| 2 | Job queue and background worker | done |
| 3 | Metrics and `/metrics` | done |
| 4 | Fault injection endpoints | done |
| 5 | Control page | **not started** |
| 6 | Container (Dockerfile) | not started |
| 7 | Helm chart (needs no cluster) | not started |
| 8 | Cluster — ask first | not started |
| 9 | Monitoring stack — ask first | not started |
| 10 | Proof: incidents and dashboard screenshots | not started |

Current code: a single module, `app/main.py`, 117 lines. No Dockerfile, no chart, no
tests, no README before this one.

---

## The service contract

| Method | Path | Purpose | State |
|---|---|---|---|
| GET | `/` | Control page | returns JSON placeholder until Phase 5 |
| POST | `/jobs?count=N` | Add N jobs to the queue | live — `N` bounded 0–1000 |
| GET | `/state` | JSON snapshot of the queue | live |
| GET | `/healthz` | Liveness. Always 200. | live |
| GET | `/readyz` | Readiness. 200 when the worker is running, **503** when it is not. | live |
| GET | `/metrics` | Prometheus text format | live |
| POST | `/fault/slow?ms=N` | Make each job take N milliseconds longer | live — 0–10000 |
| POST | `/fault/error?rate=N` | Fail N percent of jobs | live — 0–100 |
| POST | `/fault/cpu?seconds=N` | Burn CPU for N seconds | live — 0–30 |
| POST | `/fault/memory?mb=N` | Allocate N MB and hold it | live — 0–200 per call |
| POST | `/fault/reset` | Clear all faults and release memory | live |

`/healthz` and `/readyz` answer different questions. Liveness asks "is this process
alive" — restarting it would not help, so it stays 200. Readiness asks "should traffic
come here" — if the worker thread is dead, the answer is no, and Kubernetes needs to
read that as a **status code**, not as a word in the response body.

---

## The six numbers

| Metric | Type | Why it exists |
|---|---|---|
| `jobs_received_total` | counter | Total jobs accepted. Shows traffic. |
| `jobs_processed_total` | counter | Total jobs finished. Shows good work. |
| `jobs_failed_total{reason}` | counter with a label | Errors, split by cause. |
| `job_processing_seconds` | histogram | How long jobs take — latency and its spread. |
| `queue_depth` | gauge | Jobs waiting. **This is the invisible one.** Nothing else in the app shows a backlog. |
| `worker_busy` | gauge, 0 or 1 | Whether the worker is actually working. |

A counter only goes up and is used with `rate()`. A gauge goes up and down and is read
as an instant value. Swap them and the queue depth becomes a meaningless ever-growing
number, and throughput becomes an instantaneous reading of something cumulative.

`prometheus-client` also publishes process-level numbers (CPU, memory, open files) for
free. They are kept.

---

## Running it locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn prometheus-client

uvicorn app.main:app --reload --port 8000
```

Then, in another terminal:

```bash
curl -s localhost:8000/healthz              # {"status":"ok"}
curl -s -X POST "localhost:8000/jobs?count=50"
curl -s localhost:8000/state                # queue depth, draining live
curl -s localhost:8000/metrics | grep queue_depth
```

Watch the backlog drain:

```bash
watch -n1 'curl -s localhost:8000/state'
```

---

## Injecting faults

Each fault is set with a POST and cleared by `/fault/reset`.

```bash
curl -s -X POST "localhost:8000/fault/slow?ms=2000"     # jobs now take ~2.5s each
curl -s -X POST "localhost:8000/fault/error?rate=50"    # half the jobs fail
curl -s -X POST "localhost:8000/fault/cpu?seconds=10"   # burn CPU
curl -s -X POST "localhost:8000/fault/memory?mb=150"    # hold 150MB
curl -s -X POST localhost:8000/fault/reset
```

Every fault is bounded on purpose. An unbounded fault on a small machine does not
produce a clean experiment — it produces a dead machine.

**Verified against the running service:** every bound is enforced at the API boundary —
`ms=10001`, `ms=-1` and `rate=101` all return 422. `/fault/cpu` returns in about 0.02s
while the burn runs on a separate thread, and `/healthz` stayed under 0.1s throughout a
6-second burn.

---

## Engineering for a 5 GB / 2 CPU box

This project is built on WSL2 with **5 GB of RAM and 2 CPUs**, where the VS Code server
alone holds about 2.8 GB. Roughly 1.4 GB is actually free. That constraint shaped almost
every design decision here, and it is the most honest part of the project.

**What was cut, and why:**

| Decision | Reason |
|---|---|
| No database | The queue lives in memory. Postgres would cost ~150 MB and buy nothing. |
| No frontend framework | One hand-written HTML page. A framework would cost build steps and memory for six numbers and five buttons. |
| Three dependencies only | `fastapi`, `uvicorn`, `prometheus-client`. Every extra dependency is more to install, load, and explain. |
| Every file under ~150 lines | Small enough to read in one sitting and to hold in your head while debugging. |
| `/fault/memory` capped per call | One request cannot kill the box. The running total is not yet bounded — see open issues. |
| `/fault/cpu` capped at 30s | A CPU burn on 2 vCPUs starves everything else, including the tools measuring it. |
| `/fault/slow` capped at 10s | Long enough to show a backlog building; short enough that 1000 queued jobs stay unrecoverable only in principle. |
| Docker images left cached | 35 images, ~6 GB. Deleting them makes starting the cluster slow and expensive. They are an asset here, not clutter. |

**What this changes downstream:**

- The Helm chart (Phase 7) sets explicit CPU and memory requests and limits sized for this
  box, with the arithmetic written down.
- The cluster (Phase 8) asks permission before starting, because minikube may simply not
  fit alongside VS Code.
- The monitoring stack (Phase 9) is trimmed: no Alertmanager, and the etcd, scheduler and
  proxy targets are disabled, because on a box this size they cost more than they show.

The result is deliberately not the architecture you would choose with unlimited resources.
It is the architecture that survives the machine it actually runs on — and the reasoning
is written down at every step.

---

## Known limitations — accepted by design

- **`job_queue.task_done()` has no paired `.join()`.** It is currently a no-op. It exists
  so that a shutdown path can wait for in-flight work; until that path exists, it does
  nothing.
- **Queue state is per-process.** `queue_depth` and `/state` report the view of one
  process. With replicas > 1, each pod reports only its own queue. This is a correctness
  issue for the deployment, not for the lab, and is documented rather than fixed.
- **`worker_busy` is blind to a concurrent CPU fault.** The gauge tracks job processing
  only. A CPU burn on another thread will not show up in it.
- **The worker has no exception handling**, deliberately. A crashable worker produces
  honest material for the fault story. A self-healing one hides the failure this project
  exists to make visible.

## Known issues — open

- **The `/fault/memory` cap is per request, not cumulative.** Verified live: three calls at
  `mb=100` all return 200 and hold 300 MB between them. At the 200 MB maximum, roughly two
  dozen calls would exhaust the box. The guard needs to check a running total rather than
  the current request alone.
- **`fault_state["memory_mb"]` is never written.** `/fault/reset` clears a key that nothing
  sets, so memory accounting resets nothing. Cosmetic, but it makes `/fault/reset` look
  like it does more than it does.

## Not built yet

No tests, no Dockerfile, no Helm chart, no control page, no incident notes.

---

## Roadmap

1. **Phase 5** — control page: one HTML file at `/`, live numbers, a button per fault.
2. **Phase 6** — `Dockerfile` and `.dockerignore`; measure the image's real memory cost.
3. **Phase 7** — Helm chart, parameterised and linting clean. Needs no cluster.
4. **Phase 8** — cluster, once the memory arithmetic is agreed.
5. **Phase 9** — Prometheus and Grafana, trimmed for this box. One dashboard: queue depth,
   jobs per second, failure rate, job duration.
6. **Phase 10** — run each fault, screenshot the dashboard before and after, and write one
   incident note per fault in `docs/incidents/`.

---

## Design rules

- No database. No authentication. No frontend framework. No CI pipeline. No Terraform.
- Three dependencies. A fourth has to justify its cost in memory and complexity.
- Every file under about 150 lines.
- No secrets in committed files — `.env.example` only.
