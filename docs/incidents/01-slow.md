# Incident 01: slow jobs

## Symptom

Under the same 100-job load, throughput fell to about a third of normal and
each job took about three times longer. The queue peaked at 94, as it did at
baseline, but it emptied much more slowly. No job failed.

## The call

    pulse_post "/fault/slow?ms=1000"
    pulse_post "/jobs?count=100"

`pulse_post` is a shell function that sends a POST to the app from inside the
pod, using `kubectl exec`. Before the baseline run I cleared all faults with
`pulse_post "/fault/reset"`.

## What the dashboard showed

Same 100 jobs, 15-minute range, 5-second refresh.

| | Baseline | Slow fault |
|---|---|---|
| Peak queue depth | about 93 | 94 |
| Peak throughput | about 1.7 ops/s | 0.618 ops/s |
| Average job duration | about 510 ms (settled) | 1.738 s |

The 1.738 s is exact. I took it from Prometheus over the whole run:

    increase(job_processing_seconds_sum[10m]) / increase(job_processing_seconds_count[10m])

evaluated at 00:14. A second query, `increase(job_processing_seconds_count[10m])`,
returned 100.84, so the window held only the slow run. The dashboard panel
averages over 5 minutes, so it read a little differently (a plateau near 1.75 s).

CPU rose from about 7.5m cores at idle to about 46m cores during the run. The
limit is 250m. I did not find the cause of that rise.

Screenshots: `01-slow-before-p1..p4` and `01-slow-after-p1..p4`.

## Root cause

I injected it. `/fault/slow?ms=1000` adds 1000 ms to each job, so the expected
duration was 0.5 + 1.0 = 1.5 s. The measured average was 1.738 s, about 0.24 s
higher. At baseline the overhead was only 5 to 10 ms, so normal overhead does
not explain the gap. I did not find the cause. Slow Docker, probe timeouts and
swap use all showed up earlier in the cluster events, but I did not test them.

## The reset

    pulse_post "/fault/reset"

This clears every fault. The setting lives in the app's memory, so a pod
restart would clear it too. I did not time the recovery.

## Lesson

The slow fault raises no errors, so the Failures panel stays empty. An alert on
error rate would miss it. Throughput and job duration show it. Peak queue depth
alone also hides it, because the peak was the same in both runs. The difference
is how fast the queue empties. I also learned to check a dashboard average
against an exact query, and to record a gap I cannot explain instead of
inventing a cause.
