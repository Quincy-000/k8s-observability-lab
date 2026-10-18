# Incident 04: memory

_Run 2026-10-18, ~21:59–22:05 UTC. Fault: `/fault/memory?mb=200` — the endpoint
appends `bytearray(mb * 1024 * 1024)` and holds it. Container limit **256Mi**,
request 64Mi. Baseline RSS: **36 MiB**._

## Symptom

The pod went unresponsive rather than fat. The Memory panel shows the line at
**36–47 MiB**, a gap from **22:03:16 to 22:04:31**, and then the same flat line
again. No climb toward 256 MiB is visible anywhere in the graph.

What the cluster recorded:

- Restart count **8 → 11** — three terminations during the run
- **15 failed scrapes** (`up{job="pulse"} == 0`) inside 15 minutes
- Last State: **Terminated, Reason: Completed, Exit Code 0**

## The call

    pulse_post "/fault/reset"
    pulse_post "/fault/memory?mb=200"

## What the dashboard showed

Nothing spectacular, and that is the finding. Peak `process_resident_memory_bytes`
in every scrape across the window:

    max_over_time(process_resident_memory_bytes{job="pulse"}[15m]) / 1024 / 1024
      -> 46.9 MiB

The allocation was real — it is a zero-filled `bytearray`, so the pages are
touched and resident immediately — but **the scrapes that would have caught it
never succeeded**. The app could not answer `/metrics`, which is the same reason
it could not answer `/healthz`.

Screenshots: `04-memory-before-memory.jpg`, `04-memory-after-memory.png`. The gap
is the evidence, not the line.

## Root cause

`/fault/memory?mb=200` holds 200 MB inside the process. With a 256Mi limit, the
container is pushed to the edge of its own ceiling, and the Python process stops
responding to HTTP in time: the kubelet's liveness probe is `timeout=1s,
period=10s, failure=3`, so three consecutive misses over 30 seconds is a SIGTERM.

**It was not an OOMKill.** The last termination is exit code **0**, Reason
`Completed` — uvicorn's graceful shutdown handler catching the kubelet's SIGTERM
and exiting cleanly. An OOMKill would read exit code **137**, Reason `OOMKilled`.
The probe got there first; had the probe been more patient, the kernel would have
killed it and the exit code would say so.

The monitoring blind spot is the interesting part: **the metric that would have
shown the 200 MB spike is served by the process the spike takes down.** At a 15 s
scrape interval, a process that misses two or three scrapes while it is being
killed leaves a gap where the peak should be. Only an out-of-process exporter
(cAdvisor, node exporter, kube-state-metrics) can record memory while the
application is unable to serve.

## The reset

    pulse_post "/fault/reset"

The allocation lives in `memory_hog`; a restart clears it too. The pod came back
Ready inside one scrape interval (5 s or less, given the 10 s probe period).

## Lesson

**A self-instrumented process cannot report its own death.** Every metric in this
lab comes from `/metrics` inside the container, so the moment the container is the
thing failing, the data stops. That is not a flaw in the dashboard — it is a
property of the design, and it is why production stacks put memory and restart
counts in the kubelet's own exporters rather than trusting the app to describe
itself.

Second: the limit is not the failure threshold people imagine. The pod died at
~47 MiB observed, well under 256Mi, because the probe's one-second deadline is a
much tighter constraint than the memory limit. **The tightest limit wins, and here
it was time, not memory.**
