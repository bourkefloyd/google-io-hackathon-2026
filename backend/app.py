import os
import uuid
import asyncio
import logging
from typing import Dict, Optional
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from fleet_manager import FleetManager
from agent_runner import run_agent_play_loop
from ingestion import TelemetryCollector

# Setup directories
BUILDS_DIR = "builds"
os.makedirs(BUILDS_DIR, exist_ok=True)
os.makedirs("runs", exist_ok=True)

logger = logging.getLogger("app")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Local Simulated Android Player Fleet API")

# Enable CORS for local web requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize core services
fleet_manager = FleetManager()
telemetry_collector = TelemetryCollector()

# Global dictionary to hold active run SSE message queues
active_queues: Dict[str, asyncio.Queue] = {}


class PlayRequest(BaseModel):
    device_id: str
    apk_name: str
    package_name: str
    instructions: str
    max_steps: Optional[int] = 15


@app.get("/api/emulators")
def get_emulators():
    """Lists currently connected Android emulators/devices."""
    devices = fleet_manager.list_devices()
    result = []
    for d in devices:
        details = fleet_manager.get_device_details(d)
        result.append(details)
    return {"devices": result}


@app.post("/api/upload")
async def upload_apk(apk: UploadFile = File(...)):
    """Uploads an APK file and saves it locally, parsing its package name."""
    if not apk.filename.endswith(".apk"):
        raise HTTPException(status_code=400, detail="Uploaded file is not an APK.")

    file_path = os.path.join(BUILDS_DIR, apk.filename)
    try:
        with open(file_path, "wb") as f:
            content = await apk.read()
            f.write(content)
        logger.info(f"Saved uploaded APK build to: {file_path}")

        # Parse APK details to get package name
        apk_details = fleet_manager.get_apk_details(file_path)
        package_name = apk_details.get("package") if apk_details else None

        return {
            "status": "success",
            "apk_name": apk.filename,
            "path": file_path,
            "package_name": package_name,
        }
    except Exception as e:
        logger.error(f"Failed to upload APK: {e}")
        raise HTTPException(status_code=500, detail=f"APK write error: {str(e)}")


@app.post("/api/play")
def start_play_run(req: PlayRequest, background_tasks: BackgroundTasks):
    """Launches an autonomous play run on a specific device."""
    apk_path = os.path.join(BUILDS_DIR, req.apk_name)
    if not os.path.exists(apk_path):
        raise HTTPException(
            status_code=404, detail="APK build file not found on server."
        )

    run_id = f"run_{uuid.uuid4().hex[:8]}"

    # Create SSE queue for this run
    active_queues[run_id] = asyncio.Queue()

    # SSE logging callback pushed onto async queue
    def push_log_event(data: dict):
        if run_id in active_queues:
            loop = asyncio.get_event_loop()
            loop.call_soon_threadsafe(active_queues[run_id].put_nowait, data)

    # Launch loop in FastAPI background tasks
    background_tasks.add_task(
        run_agent_play_loop,
        device_id=req.device_id,
        apk_path=apk_path,
        package_name=req.package_name,
        instructions=req.instructions,
        run_id=run_id,
        fleet_manager=fleet_manager,
        telemetry_collector=telemetry_collector,
        logs_callback=push_log_event,
        max_steps=req.max_steps,
    )

    return {"status": "started", "run_id": run_id}


@app.get("/api/events")
async def stream_run_events(run_id: str):
    """SSE endpoint to stream real-time logs, screenshots, and reasoning updates."""
    if run_id not in active_queues:
        raise HTTPException(
            status_code=404, detail="Run session not active or completed."
        )

    queue = active_queues[run_id]

    async def sse_generator():
        try:
            while True:
                # Wait for next event update
                data = await queue.get()
                yield f"data: {import_json_dumps(data)}\n\n"

                # If session finished, close SSE connection after pushing final packet
                if data.get("status") in ["completed", "failed"]:
                    break
        except asyncio.CancelledError:
            logger.info(f"SSE client disconnected from run {run_id}")
        finally:
            # Cleanup queue
            if run_id in active_queues:
                del active_queues[run_id]

    def import_json_dumps(d):
        import json

        return json.dumps(d)

    return StreamingResponse(sse_generator(), media_type="text/event-stream")


@app.get("/api/telemetry")
def get_telemetry_history():
    """Fetches the latest recorded gameplay timeline events."""
    events = telemetry_collector.get_events(limit=150)
    # Strip heavy screenshots for fast dashboard table list queries
    stripped = []
    for e in events:
        stripped.append(
            {
                "timestamp": e.get("timestamp"),
                "emulator_id": e.get("emulator_id"),
                "package_name": e.get("package_name"),
                "step_index": e.get("step_index"),
                "action_summary": e.get("action_summary"),
                "has_screenshot": bool(e.get("screenshot")),
                "has_logs": bool(e.get("logs")),
            }
        )
    return {"events": stripped}


@app.delete("/api/telemetry")
def clear_telemetry():
    """Clears local timeseries events file."""
    telemetry_collector.clear_local_events()
    return {"status": "success", "message": "Telemetry event log cleared."}


# Mount static frontend build
# Ensure frontend files exist or fallback to API serving
FRONTEND_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "frontend")
)
if os.path.exists(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
else:

    @app.get("/")
    def index_fallback():
        return {
            "status": "ok",
            "message": "Simulated player backend running. Frontend directory missing.",
        }
