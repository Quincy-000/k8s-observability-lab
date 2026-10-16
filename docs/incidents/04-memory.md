# Incident 04: memory

_Status: not started. Same recipe as `01-slow.md`. Run this one last: it can OOMKill the pod, which is the strongest evidence in Phase 10 and needs the clearest write-up._

## Symptom

_(How the Memory panel moved, how much was held, and whether the pod survived. If it was killed, the restart shows as a fresh container and `Up` dips — capture both.)_

## The call

    pulse_post "/fault/reset"
    pulse_post "/fault/memory?mb=200"

## What the dashboard showed

_(Peak `process_resident_memory_bytes` against the 256Mi limit and the 64Mi request. State the numbers in MB, not in the raw byte count.)_

Screenshots: `04-memory-before-p1..p4` and `04-memory-after-p1..p4`.

## Root cause

_(Expected: the fault allocates and holds memory — 200 MB per call, 200 MB total, per the app's own cap. If the container was killed, get the reason from the cluster rather than guessing: `kubectl describe pod` (Last State) and `kubectl get events --sort-by=.lastTimestamp`. An OOMKill is exit code 137 with reason OOMKilled; a clean exit 0 is the probe path from incident 03. Report which one it was.)_

## The reset

    pulse_post "/fault/reset"

_(Releases the held memory. If the pod did restart, say how long it took to come back Ready.)_

## Lesson

_(Candidate: the difference between a memory _request_ and a memory _limit_, and what the kernel does when a process crosses the limit. Also: which panel would have told you fastest?)_
