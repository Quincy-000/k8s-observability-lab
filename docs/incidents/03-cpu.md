# Incident 03: CPU burn

_Run 2026-10-18, ~21:52 UTC. Fault: `/fault/cpu?seconds=30` — one thread burns
at full speed for 30 seconds. Container limit: **250m CPU**, 256Mi memory._

## Symptom

The `CPU (cores)` panel sat at an idle floor of **0.0025–0.004 cores** — about 1%
of the limit — with occasional blips to 0.006. On invoking the fault it climbed to
**0.125 cores within a minute** and the trace was still rising when the capture
was taken.

Nothing else moved. The pod did **not** restart: restart count stayed at 8, last
container start 19:38:52. Queue depth and memory were not captured for this
incident (lighter evidence set than 01 and 02), so no claim is made about them.

## The call

    pulse_post "/fault/reset"
    pulse_post "/fault/cpu?seconds=30"

## What the dashboard showed

The panel's 1-minute rate peaked at **0.1247 cores**. That looks like half the
limit, and it is — but not because the burn was weak. It ran for 30 seconds inside
a 60-second window:

    0.25 cores × (30 s / 60 s) = 0.125 cores

A 30-second rate over the same period returns **0.219 cores**, which is the real
figure and is consistent with a burn pinned at the 250m ceiling.

    max_over_time(rate(process_cpu_seconds_total{job="pulse"}[1m])[10m:15s])
      -> 0.1247
    max_over_time(rate(process_cpu_seconds_total{job="pulse"}[30s])[10m:15s])
      -> 0.2191

Screenshots: `03-cpu-before-cpu.png`, `03-cpu-after-cpu.png`. The after capture
catches the leading edge of the rise, not the plateau — the peak figure above comes
from Prometheus, not from the pixels.

## Root cause

`/fault/cpu?seconds=30` starts a thread that loops until the deadline. With a 250m
limit the container is capped: demand above 0.25 cores becomes throttled time, not
more throughput. The fault is therefore self-limiting, and the panel's ceiling is
the limit rather than the burn's appetite.

**The expected probe kill did not happen.** The chart sets a liveness probe of
`timeout=1s, period=10s, failure=3`, so a starved app that cannot answer
`/healthz` inside a second should be killed. Thirty seconds at the ceiling was not
enough to provoke it. What it *did* prove is the reverse: the app kept answering
health checks while a thread was pinned, which is the behaviour you want and a
credit to the worker running off the request path.

## The reset

    pulse_post "/fault/reset"

The burn also stops on its own after `seconds`.

## Lesson

**Choose the window before you read the graph.** The same 30-second event is
0.125 cores on a 1-minute rate and 0.219 on a 30-second one. Neither number is
wrong; quoting the first without saying it is a one-minute average understates the
burn by half and would make a capped fault look like a gentle one. State the
window, or state both.

Second: a stress fault is not an availability incident by default. The pod
survived, and the reason it survived is that the burn never blocked the health
endpoints. Had the fault been implemented on the request path instead of a
background thread, the 1-second liveness timeout would have turned a CPU test into
a restart loop — which is the failure mode incident 05 exists to document.
