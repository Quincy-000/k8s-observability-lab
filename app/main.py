import queue
import threading
import time

from fastapi import FastAPI

app = FastAPI()
job_queue = queue.Queue()
 

@app.get("/healthz")
def healthz():
    return {"status": "ok"}

@app.get("/readyz")
def readyz():
    if worker_thread.is_alive():
        return {"status": "ready"}
    return {"status": "not ready"}

@app.get("/")
def root():
    return {"service": "pulse"}

@app.post("/jobs")
def add_jobs(count: int):
    for i in range(count):
        job_queue.put(i)
    return {"added": count}

@app.get("/state")
def state():
    return {"queue_depth": job_queue.qsize()}

def worker():
    while True:
        job = job_queue.get()
        time.sleep(0.5)
        job_queue.task_done()
        
worker_thread = threading.Thread(target=worker, daemon=True)
worker_thread.start()