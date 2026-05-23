import os
import uuid
import asyncio
import logging

# Load environment variables from .env file if present
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
if os.path.exists(env_path):
    with open(env_path, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip().strip('"').strip("'")

from typing import Dict, Optional, Callable
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

# Set of run IDs that have been requested to stop
stopped_runs = set()

# Track active runs to their targeted device IDs
active_runs_devices: Dict[str, str] = {}


class PlayRequest(BaseModel):
    device_id: str
    apk_name: str
    package_name: str
    instructions: str
    max_steps: Optional[int] = 50


@app.get("/api/emulators")
def get_emulators():
    """Lists currently connected Android emulators/devices with busy/idle status."""
    devices = fleet_manager.list_devices()
    result = []
    busy_devices = set(active_runs_devices.values())
    for d in devices:
        details = fleet_manager.get_device_details(d)
        details["status"] = "busy" if d in busy_devices else "idle"
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


async def run_play_task_wrapper(
    run_id: str,
    device_id: str,
    apk_path: str,
    package_name: str,
    instructions: str,
    max_steps: int,
    push_log_event: Callable
):
    active_runs_devices[run_id] = device_id
    try:
        await run_agent_play_loop(
            device_id=device_id,
            apk_path=apk_path,
            package_name=package_name,
            instructions=instructions,
            run_id=run_id,
            fleet_manager=fleet_manager,
            telemetry_collector=telemetry_collector,
            logs_callback=push_log_event,
            max_steps=max_steps,
            is_stopped_callback=lambda: run_id in stopped_runs,
        )
    finally:
        if run_id in active_runs_devices:
            del active_runs_devices[run_id]


@app.post("/api/play")
def start_play_run(req: PlayRequest, background_tasks: BackgroundTasks):
    """Launches an autonomous play run on a specific device."""
    apk_path = os.path.join(BUILDS_DIR, req.apk_name)
    if not os.path.exists(apk_path):
        raise HTTPException(
            status_code=404, detail="APK build file not found on server."
        )

    target_device = req.device_id
    redirect_msg = ""

    # Check if target device is currently in progress
    busy_devices = set(active_runs_devices.values())
    if target_device in busy_devices:
        logger.info(f"Requested device {target_device} is busy. Finding idle or creating new emulator...")
        
        # 1. Search for another connected device/emulator that is idle
        all_devices = fleet_manager.list_devices()
        idle_devices = [d for d in all_devices if d not in busy_devices]
        
        if idle_devices:
            target_device = idle_devices[0]
            redirect_msg = f"Device {req.device_id} was busy. Auto-routed to idle device {target_device}."
            logger.info(redirect_msg)
        else:
            # 2. No idle devices, dynamically create/boot a new mock emulator!
            target_device = fleet_manager.create_mock_device()
            redirect_msg = f"Device {req.device_id} was busy. Dynamically booted and targeted new mock emulator {target_device}."
            logger.info(redirect_msg)

    run_id = f"run_{uuid.uuid4().hex[:8]}"

    # Create SSE queue for this run
    active_queues[run_id] = asyncio.Queue()

    # SSE logging callback pushed onto async queue
    def push_log_event(data: dict):
        if run_id in active_queues:
            loop = asyncio.get_event_loop()
            loop.call_soon_threadsafe(active_queues[run_id].put_nowait, data)

    # Launch loop in FastAPI background tasks via our wrapper to manage active state
    background_tasks.add_task(
        run_play_task_wrapper,
        run_id=run_id,
        device_id=target_device,
        apk_path=apk_path,
        package_name=req.package_name,
        instructions=req.instructions,
        max_steps=req.max_steps,
        push_log_event=push_log_event,
    )

    return {
        "status": "started", 
        "run_id": run_id, 
        "device_id": target_device,
        "message": redirect_msg
    }


@app.post("/api/play/stop")
def stop_play_run(run_id: str):
    """Stops an active autonomous play run, with force-stop fallback for dead on-disk runs."""
    # Check if active in memory
    if run_id in active_queues:
        stopped_runs.add(run_id)
        logger.info(f"Stop signal sent to active run session: {run_id}")
        return {"status": "success", "message": "Stop signal sent to active run session."}

    # If not active in memory, it might be an orphaned/dead run on disk.
    # Let's force-stop it by updating its on-disk configuration!
    import json
    run_dir = os.path.join("runs", run_id)
    config_path = os.path.join(run_dir, "run_config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                config_data = json.load(f)
            
            if config_data.get("status") == "playing":
                config_data["status"] = "stopped"
                with open(config_path, "w") as f:
                    json.dump(config_data, f, indent=2)
                
                # Write final terminated event to telemetry summary if exists
                telemetry_path = os.path.join(run_dir, "telemetry_summary.json")
                telemetry_data = []
                if os.path.exists(telemetry_path):
                    try:
                        with open(telemetry_path, "r") as f:
                            telemetry_data = json.load(f)
                    except Exception:
                        pass
                
                from datetime import datetime
                final_event = {
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "emulator_id": config_data.get("device_id", "unknown"),
                    "run_id": run_id,
                    "package_name": config_data.get("package_name", "unknown"),
                    "step_index": 999,
                    "screenshot": "",
                    "agent_reasoning": "Simulation run force-stopped / cancelled by user.",
                    "actions_taken": [],
                    "action_summary": "Session terminated.",
                    "logs": "Force-stopped by user request.",
                }
                telemetry_data.append(final_event)
                with open(telemetry_path, "w") as f:
                    json.dump(telemetry_data, f, indent=2)

                logger.info(f"Force-stopped orphaned/dead run session on disk: {run_id}")
                return {"status": "success", "message": "Force-stopped dead/orphaned run on disk."}
        except Exception as e:
            logger.error(f"Failed to force-stop orphaned run {run_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to force-stop: {str(e)}")

    raise HTTPException(
        status_code=404, detail="Run session not active or found on disk."
    )


@app.get("/api/runs")
def list_runs():
    """Lists all historic runs by scanning the runs directory and reading their configs."""
    import json
    runs_dir = "runs"
    results = []
    if os.path.exists(runs_dir):
        for d in os.listdir(runs_dir):
            d_path = os.path.join(runs_dir, d)
            if os.path.isdir(d_path):
                config_path = os.path.join(d_path, "run_config.json")
                if os.path.exists(config_path):
                    try:
                       with open(config_path, "r") as f:
                           results.append(json.load(f))
                    except Exception as e:
                       logger.error(f"Failed to read config for run {d}: {e}")
    # Sort by timestamp descending (newest runs first)
    results.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return {"runs": results}


@app.get("/api/runs/{run_id}")
def get_run_details(run_id: str):
    """Gets full configuration, telemetry steps, and logcats of a specific historic run."""
    import json
    run_dir = os.path.join("runs", run_id)
    if not os.path.exists(run_dir) or not os.path.isdir(run_dir):
        raise HTTPException(status_code=404, detail="Run not found.")
    
    config_data = {}
    config_path = os.path.join(run_dir, "run_config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                config_data = json.load(f)
        except Exception as e:
            logger.error(f"Failed to read run config for {run_id}: {e}")
    else:
        config_data = {"run_id": run_id, "status": "unknown"}

    telemetry_data = []
    telemetry_path = os.path.join(run_dir, "telemetry_summary.json")
    if os.path.exists(telemetry_path):
        try:
            with open(telemetry_path, "r") as f:
                telemetry_data = json.load(f)
        except Exception as e:
            logger.error(f"Failed to read telemetry for {run_id}: {e}")

    logcat_content = ""
    logcat_path = os.path.join(run_dir, "device_logcat.log")
    if os.path.exists(logcat_path):
        try:
            with open(logcat_path, "r") as f:
                logcat_content = f.read()
        except Exception as e:
            logger.error(f"Failed to read device logcat for {run_id}: {e}")

    return {
        "config": config_data,
        "telemetry": telemetry_data,
        "logs": logcat_content
    }


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
            # Cleanup queue and stopped run status
            if run_id in active_queues:
                del active_queues[run_id]
            if run_id in stopped_runs:
                stopped_runs.remove(run_id)

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


# Mount static runs and frontend directories
app.mount("/runs", StaticFiles(directory="runs"), name="runs")

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

