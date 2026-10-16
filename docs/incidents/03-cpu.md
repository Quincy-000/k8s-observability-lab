# Incident 03: CPU burn

_Status: not started. Same recipe as `01-slow.md`. This is the one most likely to make the pod restart itself — read the notes before you run it._

## Symptom

_(What the CPU panel showed and for how long. Watch the pod as well: `kubectl get pod -l app.kubernetes.io/name=pulse` — if the restart count climbs, this fault did something 01 and 02 did not.)_

## The call

    pulse_post "/fault/reset"
    pulse_post "/fault/cpu?seconds=30"

## What the dashboard showed

_(Peak cores on the `CPU (cores)` panel against the 250m limit — the burn is deliberately capped, so say whether it throttled rather than assuming. Also: did `Up` dip, and did `up{job="pulse"}` ever read 0?)_

Screenshots: `03-cpu-before-p1..p4` and `03-cpu-after-p1..p4`.

## Root cause

_(Expected: `/fault/cpu?seconds=30` burns a thread for 30 s; with a 250m limit the container is throttled, so the panel tops out below the burn's full demand. If the pod restarted, check `kubectl describe pod` — the kubelet's liveness probe is `timeout=1s, failure=3`, so a starved app that cannot answer `/healthz` within a second gets killed. That is a real finding about the probe settings, not about the fault.)_

## The reset

    pulse_post "/fault/reset"

_(The burn also stops on its own after `seconds`.)_

## Lesson

_(Candidate: a stress fault can look like an availability incident — and the liveness probe, not the fault, is what takes the pod down. Tie it to the probe values in `chart/templates/deployment.yaml`.)_
