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
| 5 | Control page | done |
| 6 | Container (Dockerfile) | done — 152 MB image, memory measured |
| 7 | Helm chart (needs no cluster) | not started |
| 8 | Cluster — ask first | not started |
| 9 | Monitoring stack — ask first | not started |
| 10 | Proof: incidents and dashboard screenshots | not started |

Current code: `app/main.py` (141 lines), `app/static/index.html` (73 lines), `Dockerfile`
and `requirements.txt` (three dependencies). No tests and no chart yet.

---

## The service contract

| Method | Path | Purpose | State |
|---|---|---|---|
| GET | `/` | Control page — one HTML file, live-polled once a second | live |
| POST | `/jobs?count=N` | Add N jobs to the queue | live — `N` bounded 0–1000 |
| GET | `/state` | JSON snapshot of the queue | live |
| GET | `/healthz` | Liveness. Always 200. | live |
| GET | `/readyz` | Readiness. 200 when the worker is running, **503** when it is not. | live |
| GET | `/metrics` | Prometheus text format | live |
| POST | `/fault/slow?ms=N` | Make each job take N milliseconds longer | live — 0–10000 |
| POST | `/fault/error?rate=N` | Fail N percent of jobs | live — 0–100 |
| POST | `/fault/cpu?seconds=N` | Burn CPU for N seconds | live — 0–30, 429 if one is already running |
| POST | `/fault/memory?mb=N` | Allocate N MB and hold it | live — 0–200 per call and 200 MB total |
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

Each fault is set with a POST and cleared by `/fault/reset`. The same five actions are on
the control page at `/` — one hand-written HTML file, no framework, polling `/state` once
a second, and shown a visible error when the API rejects a fault rather than failing
silently.

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
`ms=10001`, `ms=-1`, `rate=101` and `/jobs?count=1001` all return 422. `/fault/cpu`
returns in **0.01s** for a 3-second burn, so the burn really is on another thread, and a
second concurrent burn is refused with **429**. `/fault/memory` refuses the call that
would pass 200 MB — 100 + 100 returns 200, the next 100 returns **429**. The cap is `>`
200, so exactly 200 MB is accepted and 201 refused; worth knowing before writing the
Phase 10 boundary note. Readiness is not taken on trust: with the worker thread dead,
`/healthz` still answers 200 while `/readyz` answers **503**.

The CPU guard is not just the happy path either. Injecting an exception into the burning
thread mid-burn leaves the flag **cleared**, because the `clear()` sits in a `finally` —
so a crashed burn cannot wedge `/fault/cpu` at 429 until a restart.

---

## The container

Phase 6. `python:3.11-slim`, the three dependencies, and `app/` copied in.

```bash
docker build -t pulse:latest .
docker run -d --name pulse -p 8000:8000 pulse:latest
curl -s localhost:8000/healthz
```

The static file path is anchored to the module directory rather than the working
directory, so the root route resolves wherever the process is started from — the CWD
happens to be `/app` here, but nothing depends on that.

**Memory, measured with `docker stats --no-stream`** rather than estimated:

| State | Memory |
|---|---|
| Idle | ~35 MiB |
| Under light job load | ~35 MiB |
| Holding a 100 MB memory fault | ~135 MiB |
| Holding the 200 MB maximum fault | ~235 MiB |
| After `/fault/reset` | back to ~35 MiB |

The fourth row is the one that sizes Phase 7. The endpoint's hard cap allows 200 MB, so
the worst case is baseline + cap = **235 MiB**, not the ~135 MiB a typical fault produces.
A 256Mi limit leaves 21 MiB of headroom and would OOMKill the pod during a deliberate
maximum fault. The chart sets a **320Mi** limit — about 25% over the worst case — and the
arithmetic is written down here so it can be argued with.

The image is 152 MB, most of it the base layer.

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
| `/fault/memory` capped per call *and* in total | One request cannot kill the box, and repeated requests cannot add up to killing it either: the running total is capped at 200 MB and the over-cap call is refused with 429. |
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
- **`/state` reads the gauge's private `_value`.** `worker_busy._value.get()` works but is
  not public API; a module-level variable would be the tidy fix. Cosmetic, left for now.

## Known issues — open

None. Every defect surfaced by the Phase 2–6 reviews is fixed and re-verified against the
running service: the shadowed `/fault/cpu` route, the per-request memory cap, the dead
`memory_mb` key, the unvalidated `/jobs` count, `/readyz` returning 200 while reporting
"not ready", the control page's silent rejections, the CWD-relative static path, and
`cpu_burn_active` staying set after an abnormal burn exit.

## Not built yet

No tests, no Helm chart (Phase 7), no `docs/` incident notes.

---

## Roadmap

1. **Phase 7** — Helm chart, parameterised and linting clean. Needs no cluster.
2. **Phase 8** — cluster, once the memory arithmetic is agreed.
3. **Phase 9** — Prometheus and Grafana, trimmed for this box. One dashboard: queue depth,
   jobs per second, failure rate, job duration.
4. **Phase 10** — run each fault, screenshot the dashboard before and after, and write one
   incident note per fault in `docs/incidents/`.

---

## Design rules

- No database. No authentication. No frontend framework. No CI pipeline. No Terraform.
- Three dependencies. A fourth has to justify its cost in memory and complexity.
- Every file under about 150 lines.
- No secrets in committed files — `.env.example` only.
