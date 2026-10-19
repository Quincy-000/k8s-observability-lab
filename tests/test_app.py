"""Tests for the Pulse job-queue app.

The app starts a background worker at import time, so every test works on
*deltas* of the Prometheus counters rather than absolute values -- the counters
are process-wide and survive between tests.
"""

import os
import sys
import time

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

import main  # noqa: E402

client = TestClient(main.app)


def sample(name, labels=""):
    """Read one value out of the /metrics exposition text."""
    for line in client.get("/metrics").text.splitlines():
        if line.startswith(f"{name}{labels} "):
            return float(line.rsplit(" ", 1)[1])
    return 0.0


def counters():
    return {
        "received": sample("jobs_received_total"),
        "processed": sample("jobs_processed_total"),
        "failed": sample("jobs_failed_total", '{reason="fault"}'),
    }


def queue_depth():
    return client.get("/state").json()["queue_depth"]


def wait_until_idle(finished_target, timeout=20.0):
    """Block until `finished_target` jobs have left the queue, then return."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if queue_depth() == 0 and finished_target <= 0:
            return
        time.sleep(0.05)
    raise AssertionError(f"queue did not drain within {timeout}s")


def wait_for_finished(before, expected, timeout=25.0):
    """Wait until processed + failed has risen by `expected`."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        now = counters()
        done = (now["processed"] - before["processed"]) + (now["failed"] - before["failed"])
        if done >= expected:
            return done
        time.sleep(0.05)
    raise AssertionError(f"only {done} of {expected} jobs finished within {timeout}s")


@pytest.fixture(autouse=True)
def clean_state():
    client.post("/fault/reset")
    yield
    client.post("/fault/reset")


# --- health and static -------------------------------------------------------

def test_healthz_returns_ok():
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_readyz_is_ready_when_worker_is_alive():
    r = client.get("/readyz")
    assert r.status_code == 200
    assert r.json() == {"status": "ready"}


def test_root_serves_the_dashboard_page():
    r = client.get("/")
    assert r.status_code == 200
    assert "html" in r.headers["content-type"]


# --- the queue itself --------------------------------------------------------

def test_jobs_are_accepted_and_processed():
    before = counters()
    r = client.post("/jobs?count=5")
    assert r.status_code == 200
    assert r.json() == {"added": 5}
    assert counters()["received"] - before["received"] == 5

    finished = wait_for_finished(before, 5)
    assert finished >= 5
    assert queue_depth() == 0


def test_zero_jobs_is_allowed_and_changes_nothing():
    before = counters()
    r = client.post("/jobs?count=0")
    assert r.status_code == 200
    assert counters()["received"] == before["received"]


@pytest.mark.parametrize("count", [1001, -1])
def test_job_count_outside_range_is_rejected(count):
    assert client.post(f"/jobs?count={count}").status_code == 422


# --- faults ------------------------------------------------------------------

def test_error_fault_fails_every_job_at_full_rate():
    client.post("/fault/error?rate=100")
    before = counters()
    client.post("/jobs?count=3")
    wait_for_finished(before, 3)

    after = counters()
    assert after["failed"] - before["failed"] == 3
    assert after["processed"] - before["processed"] == 0


def test_slow_fault_increases_job_duration():
    client.post("/fault/slow?ms=400")
    before = counters()
    started = time.time()
    client.post("/jobs?count=2")
    wait_for_finished(before, 2)
    elapsed = time.time() - started

    # 2 jobs x (0.5s base + 0.4s fault) = 1.8s; allow slack for scheduling.
    assert elapsed >= 1.5


def test_cpu_fault_rejects_a_second_burn_while_running():
    assert client.post("/fault/cpu?seconds=2").status_code == 200
    assert client.post("/fault/cpu?seconds=2").status_code == 429


def test_memory_cap_is_enforced():
    assert client.post("/fault/memory?mb=200").status_code == 200
    assert client.post("/fault/memory?mb=1").status_code == 429


def test_reset_clears_the_error_fault():
    client.post("/fault/error?rate=100")
    client.post("/fault/reset")

    before = counters()
    client.post("/jobs?count=2")
    wait_for_finished(before, 2)

    after = counters()
    assert after["failed"] == before["failed"]
    assert after["processed"] - before["processed"] == 2


def test_reset_returns_ok():
    r = client.post("/fault/reset")
    assert r.status_code == 200
    assert r.json() == {"status": "reset"}


# --- metrics -----------------------------------------------------------------

def test_metrics_exposes_the_panels_the_dashboard_reads():
    body = client.get("/metrics").text
    for name in (
        "jobs_received_total",
        "jobs_processed_total",
        "jobs_failed_total",
        "queue_depth",
        "worker_busy",
        "job_processing_seconds",
    ):
        assert name in body, f"{name} missing from /metrics"
