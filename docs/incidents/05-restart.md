# Incident 05: the pod that was killed while healthy

_Observed across 2026-10-18, not induced on purpose. This is the finding that
came out of writing 02 and 04, and it is the one worth fixing._

## Symptom

The restart count kept climbing all evening: **8** restarts before the fault runs,
**11** after. Every termination carries the same line in the events:

    Container pulse failed liveness probe, will be restarted

Between restarts the application served traffic normally. It was never wedged,
never out of memory (peak observed 47 MiB against a 256Mi limit), and never
returned a 5xx because of a probe.

## What the cluster recorded

    kubectl describe pod -l app.kubernetes.io/name=pulse
      Liveness:   http-get http://:http/healthz delay=0s timeout=1s period=10s #success=1 #failure=3
      Readiness:  http-get http://:http/readyz  delay=0s timeout=1s period=10s #success=1 #failure=3
      Last State: Terminated
        Reason:   Completed
        Exit Code: 0

    kubectl get events --sort-by=.lastTimestamp | grep pulse
      Warning  Unhealthy  Liveness probe failed:  ... context deadline exceeded
      Warning  Unhealthy  Readiness probe failed: ... context deadline exceeded
      Normal   Killing    Container pulse failed liveness probe, will be restarted

**Exit code 0, not 137.** That distinction is the whole story: a `SIGKILL` from
the kernel (OOMKill) would read 137 and `Reason: OOMKilled`. Exit 0 with
`Reason: Completed` means the kubelet sent **SIGTERM** and uvicorn shut down
cleanly, as designed. Nothing was wrong with the process except that it was busy.

Probe failures were logged while the system was **idle** as well as during faults
— for example at ~21:35, with no fault armed, in the same window where the Memory
panel breaks and `up` reads 0 (recorded in `02-error.md`).

## Root cause

The liveness probe allows **one second** to answer `/healthz`, on a container
limited to **250m CPU** running a Python process with a single GIL. Any brief
pause — a `/metrics` scrape building the exposition, the error-fault branch, a
200 MB allocation, a garbage collection pass, host contention on a 2-vCPU minikube
— can push the response past that deadline. Three consecutive misses, thirty
seconds, and the kubelet kills a pod that was doing its job.

Liveness is meant to detect a **wedged** process. Here it is detecting a **busy**
one, which is the wrong question, and the cost is a restart loop that erases the
evidence: restarting also resets every counter, which is why incident 04's memory
spike could not be seen in any scrape.

## The fix

    livenessProbe:
      httpGet: { path: /healthz, port: http }
      timeoutSeconds: 3      # was 1
      periodSeconds: 10
      failureThreshold: 3
    readinessProbe:
      httpGet: { path: /readyz, port: http }
      timeoutSeconds: 1      # readiness may stay tight: failing it removes traffic, it does not kill
      periodSeconds: 10
      failureThreshold: 2

Rationale: readiness is the load-sensitive signal — failing it takes the pod out
of service, which is cheap and reversible. Liveness must be slower than the app's
worst legitimate pause, or it becomes a restart generator. Three seconds is still
far below the 30-second kill window and comfortably above the ~0.5 s median
processing time recorded in 01 and 02.

This is applied in Phase 11; the verification is in the next section.

## Phase 11: what changed when it was applied

Chart revision 2, pod `pulse-549c649674-jvswf`. Probes as the API reports them:

    Liveness:   timeout=3s period=10s #success=1 #failure=3
    Readiness:  timeout=1s period=10s #success=1 #failure=2

The same memory fault that killed the pod three times in incident 04 was re-run against
the new pod, with a warmed cluster and VS Code closed to free host memory.

    restarts after the fault:      1   (was 3)
    readiness:                     failed first — "dial tcp ... i/o timeout"
    liveness:                      failed — "context deadline exceeded"
    last termination:              Error, exit code 137

So the fix helped and did not cure. Readiness did its job and pulled the pod out of
service before liveness reached three strikes; when the container still had not answered
after the thirty-second window, the kubelet sent SIGKILL and the exit code is **137 with
reason `Error`** — not `OOMKilled`, because the kernel did not kill it, the kubelet did.

**Why one restart remains.** The host had 4.8 GiB of RAM, 69 MiB free, and a full 2 GiB
swap; the node had already flipped to `NotReady` six times in two and a half hours. Under
200 MB of allocation on a machine in that state, the Python process stops answering for
longer than three seconds — longer than thirty, in fact. No probe tuning fixes that. The
remaining option is host memory: close the editor, or run the fault at 100 MB, or give WSL
more RAM. That is an environment limit, recorded here rather than papered over with a
fourth timeout value.

## Lesson

**A threshold is a claim about your app, not a default to inherit.** One second
was inherited from an example. The lab's own numbers — median job 0.5 s, probes
occasionally over 1 s while idle — show it was never a safe value, and the cost was
eight restarts that looked like a mysterious instability until the event log was
read.

Second: **restarts destroy evidence.** Every restart resets the counters the
incidents depend on. A restart loop is therefore not just an availability problem;
it is a monitoring problem, and the first thing to fix is whatever is causing the
loop.
