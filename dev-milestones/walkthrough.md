# Simulated Player Telemetry Fleet Implementation Walkthrough

This document summarizes the files, systems, and telemetry pipelines built to support your JEPA 2 ML timeseries model training using simulated Android players.

---

## What We Built

We designed and implemented a **full-stack local simulated player orchestrator**:
1. **Frontend Web Dashboard (`frontend/`)**:
   - Modern glassmorphic dark-themed visual console built with pure semantic HTML5 and custom Vanilla CSS.
   - Real-time Server-Sent Events (SSE) logger that streams emulator state frames, active screenshot grabs, and agent reasoning.
   - Click/tap vector mapping overlays that render visual coordinate points directly on top of the emulator screenshots.
   - Monospace logcat terminal debugger to read dumped engine logs instantly.
2. **FastAPI Ingestion Backend (`backend/app.py`)**:
   - Fast upload endpoint for build APKs.
   - Device managers that interface with the `adb` CLI to check dimensions, resolutes, and running states.
   - SSE connection broker that maintains real-time updates for active players.
   - Timeseries event log APIs.
3. **ADB Fleet Orchestrator (`backend/fleet_manager.py`)**:
   - Low-level ADB control layers with zero third-party wrappers dependencies.
   - Relative normalized coordinate mapping: translates visual coordinates `[0.0 to 1.0]` into pixel boundaries matched perfectly to the target emulator's screen size.
   - logcat buffers controls: flushes device log logs on session startup (`adb logcat -c`) and dumps all logs at completion (`adb logcat -d`).
4. **Google Antigravity autonomous play agent (`backend/agent_runner.py`)**:
   - Multimodal visual play agent powered by the **Google Antigravity SDK**.
   - screenshot grab loops: captures frames, translates coordinates, executes taps/swipes/text inputs, and handles delays.
   - Action sequencing macros: allows the agent to execute a chain of several ADB commands back-to-back in a single turn, maximizing play speed.
   - Fallback Simulator Mode: runs dry-run playing simulations with active telemetry reporting if GCP credentials are not set or during testing.
5. **Telemetry ingestion pipelines (`backend/ingestion.py`)**:
   - Dual Ingestion Modes: writes telemetry events directly to standard GCP Pub/Sub topics if variables are configured, falling back automatically to local timeseries databases (`backend/data/gameplay_events.jsonl`) to support local testing.
6. **Automation & Bootstrap (`run.sh`)**:
   - All-in-one bash launcher script that sets up the virtualenv, updates pip, installs dependencies, handles local Antigravity `.whl` files, and starts Uvicorn.

---

## Directory Layout & File Links

Here are the files created in your workspace:

- [README.md](file:///Users/bourkefloydiv/projects/google-io-hackathon-2026/README.md) — All-in-one setup guide and production GCP guidelines.
- [run.sh](file:///Users/bourkefloydiv/projects/google-io-hackathon-2026/run.sh) — Virtualenv bootstrap and Uvicorn server launcher.
- [backend/requirements.txt](file:///Users/bourkefloydiv/projects/google-io-hackathon-2026/backend/requirements.txt) — relaxed package requirements to allow fast wheel compilation.
- [backend/fleet_manager.py](file:///Users/bourkefloydiv/projects/google-io-hackathon-2026/backend/fleet_manager.py) — Low-level ADB tapping, resolution, and logcat buffer controls.
- [backend/ingestion.py](file:///Users/bourkefloydiv/projects/google-io-hackathon-2026/backend/ingestion.py) — Local timeseries writer and GCP Pub/Sub publisher.
- [backend/agent_runner.py](file:///Users/bourkefloydiv/projects/google-io-hackathon-2026/backend/agent_runner.py) — Visual Antigravity playing agent with macro sequencing and logcat dumping.
- [backend/app.py](file:///Users/bourkefloydiv/projects/google-io-hackathon-2026/backend/app.py) — FastAPI routing server and SSE client broker.
- [frontend/index.html](file:///Users/bourkefloydiv/projects/google-io-hackathon-2026/frontend/index.html) — Elegant dashboard markup.
- [frontend/style.css](file:///Users/bourkefloydiv/projects/google-io-hackathon-2026/frontend/style.css) — Custom premium glassmorphism dark-mode CSS styles.
- [frontend/app.js](file:///Users/bourkefloydiv/projects/google-io-hackathon-2026/frontend/app.js) — SSE client, file uploader, and coordinate overlay renderer.

---

## How Visual Relative Grid Tapping Works

Unity 3D games render on a single canvas, rendering layout trees useless. Here is how our player agent solves this:
1. **Screen Frame Grab**: `fleet_manager` takes a screenshot and names it by step index.
2. **Vision Analysis**: Gemini analyzes the screenshot and decides the relative tap position on a scale from `0.0` to `1.0`.
3. **Relative Mapping**:
   ```python
   def execute_tap(self, device_id: str, rel_x: float, rel_y: float) -> str:
       res = self.get_device_resolution(device_id)
       abs_x = int(rel_x * res["width"])
       abs_y = int(rel_y * res["height"])
       cmd = ["adb", "-s", device_id, "shell", "input", "tap", str(abs_x), str(abs_y)]
       self.run_cmd(cmd)
   ```
4. **Telemetry Logging**: Writes the timestamp, relative coordinates, absolute adb commands, and base64 screenshot into the JSONL/PubSub record.

---

## Logcat Collection Workflow

Deep device and engine logcats are extracted seamlessly:
1. **Clearing**: When the play session starts, the orchestrator issues:
   ```bash
   adb -s <device_id> logcat -c
   ```
2. **Dumping**: At the final session turn, the orchestrator issues:
   ```bash
   adb -s <device_id> logcat -d
   ```
3. **Ingestion**: The full string dump of logs is saved as the final item in the timeseries sequence under the `"logs"` field, and is populated in the terminal console in your browser!
