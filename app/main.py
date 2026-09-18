import queue
import threading
import time
import random



from fastapi import FastAPI, Response, Query
from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST

app = FastAPI()
job_queue = queue.Queue()

fault_state = {
    "slow_ms": 0,
    "error_rate": 0,
    "cpu_seconds": 0,
    "memory_mb": 0,
}
jobs_received_total = Counter("jobs_received_total", "Total jobs accepted")
jobs_processed_total = Counter("jobs_processed_total", "Total jobs finished")
jobs_failed_total = Counter("jobs_failed_total", "Total jobs failed", ["reason"])
queue_depth = Gauge("queue_depth", "Jobs waiting in queue")
worker_busy = Gauge("worker_busy", "Is the worker processing a job (1) or idle (0)")
job_processing_seconds = Histogram("job_processing_seconds", "Time spent processing a job")

@app.get("/healthz")
def healthz():
    
    return {"status": "ok"}

 

@app.get("/readyz")
def readyz():
    if worker_thread.is_alive():
        return {"status": "ready"}
    return Response(
        status_code=503,
        content='{"status":"not ready"}',
        media_type="application/json",
    )

@app.get("/")
def root():
    return {"service": "pulse"}
 
@app.post("/jobs")
def add_jobs(count: int = Query(..., ge=0, le=1000)):
    for i in range(count):
        job_queue.put(i)
    jobs_received_total.inc(count)
    queue_depth.set(job_queue.qsize())
    return {"added": count}

@app.get("/state")
def state():
    return {"queue_depth": job_queue.qsize()}

@app.get("/metrics")
def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.post("/fault/slow")
def fault_slow(ms: int = Query(..., ge=0, le=10000)):
    fault_state["slow_ms"] = ms
    return {"slow_ms": ms}

@app.post("/fault/error")
def fault_error(rate: int = Query(..., ge=0, le=100)):
    fault_state["error_rate"] = rate
    return {"error_rate": rate}

    
def worker():
    while True:
        job = job_queue.get()
        worker_busy.set(1)
        with job_processing_seconds.time():
            time.sleep(0.5 + fault_state["slow_ms"] / 1000)
        worker_busy.set(0)
        if random.randint(1, 100) <= fault_state["error_rate"]:
            jobs_failed_total.labels(reason="fault").inc()
        else:
            jobs_processed_total.inc()
        queue_depth.set(job_queue.qsize())
        job_queue.task_done()
        
def burn_cpu(seconds: int):
    end_time = time.time() + seconds
    while time.time() < end_time:
        pass

@app.post("/fault/cpu")
def fault_cpu(seconds: int = Query(..., ge=0, le=30)):
    fault_state["cpu_seconds"] = seconds
    threading.Thread(target=burn_cpu, args=(seconds,), daemon=True).start()
    return {"cpu_seconds": seconds}    

memory_hog = []

@app.post("/fault/memory")
def fault_memory(mb: int = Query(..., ge=0, le=200)):
    memory_hog.append(bytearray(mb * 1024 * 1024))
    return {"memory_mb": mb}    

@app.post("/fault/reset")
def fault_reset():
    fault_state["slow_ms"] = 0
    fault_state["error_rate"] = 0
    fault_state["cpu_seconds"] = 0
    fault_state["memory_mb"] = 0
    memory_hog.clear()
    return {"status": "reset"}
        
worker_thread = threading.Thread(target=worker, daemon=True)
worker_thread.start()