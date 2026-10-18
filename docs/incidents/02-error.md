# Incident 02: errors

_Run 2026-10-18, ~21:22–21:30 UTC. Fault: `/fault/error?rate=50` — half of all
jobs fail by design. Two batches of 100 jobs were sent while the fault was armed._

## Symptom

The `Failures` panel had read **No data** all evening. Within a minute of the
first batch it showed a rate of **0.65 ops/s**, and it stayed up for as long as
the fault was armed. Nothing else on the dashboard looked wrong:

- **Throughput** stayed at its normal peak (~0.72 ops/s)
- **Queue depth** behaved normally — filled to 100, drained in under a minute
- **CPU** never left the idle band (0.013–0.019 cores)
- **Memory** stayed flat at ~36 MiB
- **Average duration** did move: ~0.50 s → **0.63 s sustained**, peaking at 0.662 s

So the system was working, at full speed, and throwing away half of what it did.

## The call

    pulse_post "/fault/reset"
    pulse_post "/jobs?count=100"          # baseline
    pulse_post "/fault/error?rate=50"
    pulse_post "/jobs?count=100"          # burst 1
    pulse_post "/jobs?count=100"          # burst 2

## What the dashboard showed

| Batch | Failed | Processed | Failure share |
|---|---|---|---|
| 1 (21:21–21:25) | 48 | 52 | 48% |
| 2 (21:26–21:30) | 57 | 45 | 56% |

Peak failure rate **0.854 ops/s**, measured with:

    max_over_time(rate(jobs_failed_total{job="pulse"}[1m])[15m:30s])

The panel's second peak read 0.85 — the panel and the raw query agree.

Average duration during the fault, from:

    rate(job_processing_seconds_sum{job="pulse"}[2m])
      / rate(job_processing_seconds_count{job="pulse"}[2m])

…peaked at **0.662 s** against a ~0.50 s baseline. **I did not confirm why the
average gets slower when half the jobs fail.** Candidate: the failure path still
occupies the worker for part of its normal duration before raising. This is
recorded as an open question, not a finding.

Screenshots: `02-error-before-{1-up-cpu,2-memory,3-duration,5-queue}` and
`02-error-after-{1a-up,1b-cpu,2-memory,3-duration,4-failures,4-throughput}`.
Two frames were not captured: the pre-fault throughput shot (`before-4-throughput`)
and the post-fault queue depth (`after-5-queue`). Their data is in the numbers above
and in `01-slow`'s queue behaviour, which is why they were left out rather than
re-staged.

## Root cause

`/fault/error?rate=50` makes each job fail with probability 0.5 before the work
is done. The metric `jobs_failed_total{reason="fault"}` is exported **only after
its first use**, which is why the panel read "No data" all evening and why its
first appearance is itself the signal that something changed.

## The reset

    pulse_post "/fault/reset"

## Lesson

This is the incident an error-rate metric catches and nothing else does. Throughput
sat at its normal peak, the queue drained normally, CPU and memory never moved.
An alert built on latency or throughput would have called this system healthy
while it silently discarded half the work.

Two caveats worth keeping:

1. **The gap was the app, not the graph.** Between ~21:34:40 and 21:35:20 the
   Memory line breaks and `up{job="pulse"}` records zeros — but the kubelet also
   logged `Liveness probe failed` and `Readiness probe failed`, both "context
   deadline exceeded", at that time. The container never restarted (restart count
   stayed at 8, last start 19:38:52), so it recovered on its own before the
   three-strike threshold killed it. The dashboard was accurate: for roughly forty
   seconds the app could not answer inside the probe's one-second timeout. I first
   recorded this as missed scrapes from a single Prometheus; the event log says
   otherwise, which is why the pod's own events are worth reading before blaming
   the monitoring.
2. **Don't trust a single reading.** An instantaneous query taken after the
   plateau decayed reported average duration "unchanged" at 0.544 s. The panel
   history showed the real 25% rise. Query the window, not the moment.
