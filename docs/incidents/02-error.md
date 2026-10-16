# Incident 02: errors

_Status: not started. Same recipe as `01-slow.md` — induce it, screenshot before and after, fill this in._

## Symptom

_(What changed from baseline: which panel moved, from what to what. Did the queue drain faster or slower than the slow run? Note that no job got slower — only some failed.)_

## The call

    pulse_post "/fault/reset"
    pulse_post "/jobs?count=100"          # baseline first, if you want a comparison
    pulse_post "/fault/error?rate=50"
    pulse_post "/jobs?count=100"

## What the dashboard showed

_(Peak throughput, peak failure rate, whether queue depth behaved differently from the slow run. Take the exact figure from Prometheus, not from the panel average — say which query you used.)_

Screenshots: `02-error-before-p1..p4` and `02-error-after-p1..p4`.

## Root cause

_(Expected: `/fault/error?rate=50` fails half the jobs by design. Remember `jobs_failed_total{reason="fault"}` is exported only after its first use — if the panel was empty before this run, say so and say why.)_

## The reset

    pulse_post "/fault/reset"

## Lesson

_(Candidate: this is the one fault an error-rate alert WOULD catch — the inverse of incident 01. Also worth recording: did throughput stay flat while failures rose, and what does that say about alerting on throughput alone?)_
