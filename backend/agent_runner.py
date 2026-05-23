import os
import asyncio
import base64
import logging
from datetime import datetime
from typing import Callable, List, Dict, Any, Optional

from fleet_manager import FleetManager
from ingestion import TelemetryCollector

# Antigravity imports
try:
    from google.antigravity import Agent, LocalAgentConfig
    from google.antigravity.types import Image

    AGY_AVAILABLE = True
except ImportError:
    AGY_AVAILABLE = False

logger = logging.getLogger("agent_runner")


def resize_screenshot(input_path: str, output_path: str, max_dimension: int = 384) -> bool:
    """Resizes the screenshot at input_path preserving the aspect ratio
    such that its maximum dimension is max_dimension. Saves the result to output_path.
    """
    try:
        from PIL import Image as PILImage
        with PILImage.open(input_path) as img:
            width, height = img.size
            if max(width, height) <= max_dimension:
                img.save(output_path, "PNG")
                return True
            
            if width > height:
                new_width = max_dimension
                new_height = int(height * (max_dimension / width))
            else:
                new_height = max_dimension
                new_width = int(width * (max_dimension / height))
            
            resample_filter = getattr(PILImage, "Resampling", PILImage).LANCZOS
            resized_img = img.resize((new_width, new_height), resample_filter)
            resized_img.save(output_path, "PNG")
            logger.info(f"Generated LLM-optimized screenshot: resized from {width}x{height} to {new_width}x{new_height}")
            return True
    except Exception as e:
        logger.error(f"Failed to resize screenshot: {e}")
        return False


class DeviceAgentTools:
    """Bounded tools registered with the Google Antigravity Agent per device session."""

    def __init__(self, device_id: str, fleet_manager: FleetManager):
        self.device_id = device_id
        self.fleet_manager = fleet_manager
        self.recorded_actions = []
        self.session_completed = False
        self.completion_reason = ""

    def tap(self, x: float, y: float) -> str:
        """Taps on the screen using normalized relative coordinates from 0.0 to 1.0.

        Args:
            x: The relative X coordinate, e.g. 0.5 for center.
            y: The relative Y coordinate, e.g. 0.5 for center.
        """
        cmd = self.fleet_manager.execute_tap(self.device_id, x, y)
        action_desc = f"Tapped position ({x}, {y})"
        self.recorded_actions.append(
            {
                "type": "tap",
                "params": {"x": x, "y": y},
                "adb_command": cmd,
                "description": action_desc,
            }
        )
        return f"SUCCESS: {action_desc} via command: {cmd}"

    def swipe(
        self, x1: float, y1: float, x2: float, y2: float, duration_ms: int = 300
    ) -> str:
        """Swipes on the screen from a start coordinate to an end coordinate.

        Args:
            x1: The start relative X coordinate (0.0 to 1.0).
            y1: The start relative Y coordinate (0.0 to 1.0).
            x2: The end relative X coordinate (0.0 to 1.0).
            y2: The end relative Y coordinate (0.0 to 1.0).
            duration_ms: The swipe duration in milliseconds (default 300).
        """
        cmd = self.fleet_manager.execute_swipe(
            self.device_id, x1, y1, x2, y2, duration_ms
        )
        action_desc = f"Swiped from ({x1}, {y1}) to ({x2}, {y2})"
        self.recorded_actions.append(
            {
                "type": "swipe",
                "params": {
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                    "duration_ms": duration_ms,
                },
                "adb_command": cmd,
                "description": action_desc,
            }
        )
        return f"SUCCESS: {action_desc} via command: {cmd}"

    def type_text(self, text: str) -> str:
        """Enters text input into the currently focused text field.

        Args:
            text: The alphanumeric text string to type.
        """
        cmd = self.fleet_manager.execute_text(self.device_id, text)
        action_desc = f"Typed text: '{text}'"
        self.recorded_actions.append(
            {
                "type": "text",
                "params": {"text": text},
                "adb_command": cmd,
                "description": action_desc,
            }
        )
        return f"SUCCESS: {action_desc} via command: {cmd}"

    def go_back(self) -> str:
        """Sends the Android BACK keyevent to navigate backward in the app."""
        cmd = self.fleet_manager.execute_keyevent(self.device_id, 4)
        action_desc = "Pressed Back Button"
        self.recorded_actions.append(
            {
                "type": "back",
                "params": {},
                "adb_command": cmd,
                "description": action_desc,
            }
        )
        return f"SUCCESS: {action_desc} via command: {cmd}"

    def wait_seconds(self, seconds: float) -> str:
        """Pauses gameplay for animations or assets loading to complete.

        Args:
            seconds: Time to sleep in seconds, e.g. 2.0.
        """
        logger.info(f"Sleeping for {seconds}s...")
        # Since this tool runs in the async agent loop, we sleep synchronously or block
        import time

        time.sleep(seconds)
        action_desc = f"Waited for {seconds} seconds"
        self.recorded_actions.append(
            {
                "type": "wait",
                "params": {"seconds": seconds},
                "adb_command": f"sleep {seconds}",
                "description": action_desc,
            }
        )
        return f"SUCCESS: {action_desc}"

    def execute_macro_sequence(self, actions_list: List[Dict[str, Any]]) -> str:
        """Executes a list/sequence of multiple actions back-to-back without waiting for a new screenshot.
        This is useful to speed up menu transitions and navigation paths.

        Args:
            actions_list: A list of action dictionaries, e.g.
                         [{"type": "tap", "x": 0.5, "y": 0.8}, {"type": "wait", "seconds": 2.0}, {"type": "tap", "x": 0.1, "y": 0.4}]
                         Supported action types in the dictionary are 'tap' (requires 'x', 'y'), 'swipe' (requires 'x1', 'y1', 'x2', 'y2', optional 'duration_ms'), 'text' (requires 'text'), 'back', 'wait' (requires 'seconds').
        """
        results = []
        for action in actions_list:
            act_type = action.get("type")
            try:
                if act_type == "tap":
                    res = self.tap(action["x"], action["y"])
                elif act_type == "swipe":
                    res = self.swipe(
                        action["x1"],
                        action["y1"],
                        action["x2"],
                        action["y2"],
                        action.get("duration_ms", 300),
                    )
                elif act_type == "text":
                    res = self.type_text(action["text"])
                elif act_type == "back":
                    res = self.go_back()
                elif act_type == "wait":
                    res = self.wait_seconds(action["seconds"])
                else:
                    res = f"ERROR: Unknown macro action type '{act_type}'"
                results.append(res)
            except Exception as e:
                err_msg = f"ERROR in macro '{act_type}': {e}"
                logger.error(err_msg)
                results.append(err_msg)

        return f"Executed macro sequence: {'; '.join(results)}"

    def complete_session(self, comment: str) -> str:
        """Call this tool when the gameplay instructions have been completed, or when the agent is stuck/cannot proceed.

        Args:
            comment: Detailed explanation of the outcome (e.g. 'Successfully beat Level 1' or 'Stuck on ads screen').
        """
        self.session_completed = True
        self.completion_reason = comment
        return f"Session marked as finished. Reason: {comment}"


async def run_agent_play_loop(
    device_id: str,
    apk_path: str,
    package_name: str,
    instructions: str,
    run_id: str,
    fleet_manager: FleetManager,
    telemetry_collector: TelemetryCollector,
    logs_callback: Callable[[Dict[str, Any]], None],
    max_steps: int = 15,
    is_stopped_callback: Optional[Callable[[], bool]] = None,
):
    """Orchestrates the entire visual playing loop for a simulated player."""
    import json
    run_dir = os.path.join("runs", run_id)
    os.makedirs(run_dir, exist_ok=True)

    # Initialize and persist run_config.json
    run_config = {
        "run_id": run_id,
        "device_id": device_id,
        "apk_name": os.path.basename(apk_path),
        "package_name": package_name,
        "instructions": instructions,
        "max_steps": max_steps,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "status": "playing"
    }
    with open(os.path.join(run_dir, "run_config.json"), "w") as f:
        json.dump(run_config, f, indent=2)

    telemetry_events = []
    last_logcat_len = 0
    logcat_filepath = os.path.join(run_dir, "device_logcat.log")

    session_tools = DeviceAgentTools(device_id, fleet_manager)

    # Start background log streaming task
    async def log_streamer():
        try:
            while not session_tools.session_completed:
                logcat_data = fleet_manager.dump_logcat(device_id)
                with open(logcat_filepath, "w") as lf:
                    lf.write(logcat_data)
                logs_callback({
                    "status": "playing",
                    "logs_update": logcat_data,
                })
                await asyncio.sleep(5.0)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in background log streamer: {e}")

    log_task = None

    try:
        # Keep the target device awake, wake up the screen, and dismiss keyguard
        fleet_manager.keep_device_awake(device_id)

        # Step 1: Install & Prepare
        logs_callback({"status": "starting", "state": "installing", "message": "Installing APK build..."})
        if not fleet_manager.install_apk(device_id, apk_path):
            logs_callback({"status": "failed", "message": "Failed to install APK."})
            run_config["status"] = "failed"
            with open(os.path.join(run_dir, "run_config.json"), "w") as f:
                json.dump(run_config, f, indent=2)
            return

        # Clear logcats for clean buffer telemetry
        fleet_manager.clear_logcat(device_id)

        # Start the background logs streaming task
        log_task = asyncio.create_task(log_streamer())

        logs_callback({"status": "starting", "state": "launching", "message": "Launching application..."})
        if not fleet_manager.launch_app(device_id, package_name):
            logs_callback(
                {"status": "failed", "message": "Failed to launch application."}
            )
            run_config["status"] = "failed"
            with open(os.path.join(run_dir, "run_config.json"), "w") as f:
                json.dump(run_config, f, indent=2)
            return

        await asyncio.sleep(3.0)  # Let app load

        # Mock mode fallback if Antigravity SDK is not fully wired or GEMINI_API_KEY is not configured
        if not AGY_AVAILABLE or not os.getenv("GEMINI_API_KEY"):
            logger.warning(
                "google-antigravity SDK not found or GEMINI_API_KEY not configured. Running in MOCK agent playback mode."
            )
            # Stop log task before entering mock loop which spins up its own log streamer
            if log_task and not log_task.done():
                log_task.cancel()
                try:
                    await log_task
                except asyncio.CancelledError:
                    pass
            await run_mock_play_loop(
                device_id=device_id,
                apk_path=apk_path,
                package_name=package_name,
                instructions=instructions,
                run_id=run_id,
                run_dir=run_dir,
                session_tools=session_tools,
                telemetry_collector=telemetry_collector,
                logs_callback=logs_callback,
                max_steps=max_steps,
                is_stopped_callback=is_stopped_callback,
            )
            return

        logs_callback(
            {
                "status": "playing",
                "state": "thinking",
                "message": "Booting Google Antigravity autonomous play agent...",
            }
        )

        from google.antigravity.types import GeminiConfig, ModelConfig, ModelEntry, GenerationConfig, ThinkingLevel

        gemini_config = GeminiConfig(
            models=ModelConfig(
                default=ModelEntry(
                    name="gemini-3.5-flash",
                    generation=GenerationConfig(
                        thinking_level=ThinkingLevel.MINIMAL
                    )
                )
            )
        )

        from google.antigravity.hooks import policy

        config = LocalAgentConfig(
            gemini_config=gemini_config,
            policies=[policy.allow_all()],
            tools=[
                session_tools.tap,
                session_tools.swipe,
                session_tools.type_text,
                session_tools.go_back,
                session_tools.wait_seconds,
                session_tools.execute_macro_sequence,
                session_tools.complete_session,
            ],
            system_instructions=(
                f"You are playing an Android game ({package_name}) on device {device_id} based on goals: {instructions}.\n"
                "You inspect the game via screenshot frames and execute relative inputs. Always think step-by-step.\n"
                "IMPORTANT: You must use the provided tools (tap, swipe, wait_seconds, execute_macro_sequence, complete_session) to interact with the game screen. Do not just observe and explain what you would do; you must actually invoke the tools to perform actions on the screen!\n"
                "For faster execution, if there are multiple standard actions needed to transition screens or menus quickly, prefer using the execute_macro_sequence tool."
            ),
        )

        async with Agent(config=config) as agent:


            for step in range(max_steps):
                step_start_time = datetime.utcnow()
                step_start_logcat_len = len(fleet_manager.dump_logcat(device_id))

                # 1. Check for cooperative cancellation
                if is_stopped_callback and is_stopped_callback():
                    logger.info(f"Play run {run_id} received stop/cancellation signal.")
                    session_tools.session_completed = True
                    session_tools.completion_reason = "Stopped by user request"
                    run_config["status"] = "stopped"
                    with open(os.path.join(run_dir, "run_config.json"), "w") as f:
                        json.dump(run_config, f, indent=2)
                    logs_callback({"status": "failed", "message": "Play session stopped by user request."})
                    break

                if session_tools.session_completed:
                    logger.info("Session completed by agent request.")
                    break

                # 2. Update status and capture screenshot
                logs_callback(
                    {
                        "status": "playing",
                        "state": "screenshotting",
                        "step": step + 1,
                        "max_steps": max_steps,
                        "message": f"Step {step + 1}/{max_steps}: Capturing game screenshot...",
                    }
                )

                screenshot_filename = (
                    f"step_{step}_{int(datetime.utcnow().timestamp())}.png"
                )
                screenshot_path = os.path.join(run_dir, screenshot_filename)
                if not fleet_manager.take_screenshot(device_id, screenshot_path):
                    logs_callback(
                        {
                            "status": "playing",
                            "state": "waiting",
                            "message": "Warning: screenshot capture failed, retrying...",
                        }
                    )
                    await asyncio.sleep(1.0)
                    continue

                # Generate LLM resized screenshot
                screenshot_llm_filename = screenshot_filename.replace(".png", "_llm.png")
                screenshot_llm_path = os.path.join(run_dir, screenshot_llm_filename)
                resize_screenshot(screenshot_path, screenshot_llm_path, max_dimension=384)

                # Convert both to base64 for real-time frontend streaming
                with open(screenshot_path, "rb") as image_file:
                    base64_screenshot = base64.b64encode(image_file.read()).decode(
                        "utf-8"
                    )

                base64_screenshot_llm = ""
                if os.path.exists(screenshot_llm_path):
                    with open(screenshot_llm_path, "rb") as image_file:
                        base64_screenshot_llm = base64.b64encode(image_file.read()).decode(
                            "utf-8"
                        )

                # Stream the screenshot IMMEDIATELY to the frontend with state "thinking"
                logs_callback(
                    {
                        "status": "playing",
                        "state": "thinking",
                        "step": step + 1,
                        "max_steps": max_steps,
                        "screenshot": base64_screenshot,
                        "screenshot_llm": base64_screenshot_llm,
                        "message": f"Step {step + 1}/{max_steps}: Evaluating frame and deciding inputs...",
                    }
                )

                # Clear previous recorded actions to isolate this step's events
                session_tools.recorded_actions = []

                # Send RESIZED screenshot to agent to evaluate next moves (reduces visual token cost & latency)
                image = Image.from_file(screenshot_llm_path)
                agent_response = await agent.chat(
                    [
                        f"Step {step + 1}: Here is the current screen frame. Decide and execute actions.",
                        image,
                    ]
                )

                # Extract agent reasoning / thoughts
                thoughts = []
                async for thought in agent_response.thoughts:
                    thoughts.append(thought)
                
                # Consuming the main text response is CRITICAL to trigger and complete tool execution in the SDK!
                text_response = await agent_response.text()
                
                thought_str = "".join(thoughts).strip()
                text_str = text_response.strip()

                if thought_str and text_str:
                    reasoning = f"**Thinking Process**\n{thought_str}\n\n**Action Decision**\n{text_str}"
                elif thought_str:
                    reasoning = f"**Thinking Process**\n{thought_str}"
                else:
                    reasoning = text_str if text_str else "No reasoning available."

                # Fetch actions executed during the tool calls of this turn
                actions_taken = []
                async for tool_call in agent_response.tool_calls:
                    name = tool_call.name
                    args = tool_call.args or {}
                    
                    if name == "tap":
                        desc = f"Tapped position ({args.get('x')}, {args.get('y')})"
                    elif name == "swipe":
                        desc = f"Swiped from ({args.get('x1')}, {args.get('y1')}) to ({args.get('x2')}, {args.get('y2')})"
                    elif name == "wait_seconds":
                        desc = f"Waited for {args.get('seconds')} seconds"
                    elif name == "type_text":
                        desc = f"Typed text: '{args.get('text')}'"
                    elif name == "go_back":
                        desc = "Pressed Back Button"
                    elif name == "complete_session":
                        desc = f"Session marked as finished. Reason: {args.get('comment')}"
                    elif name == "execute_macro_sequence":
                        desc = "Executed macro sequence"
                    else:
                        desc = f"Executed tool: {name}"
                        
                    actions_taken.append({
                        "type": name,
                        "params": args,
                        "description": desc,
                        "adb_command": f"adb shell input tap {int(args.get('x', 0) * 1080)} {int(args.get('y', 0) * 2400)}" if name == "tap" else ""
                    })
                
                if not actions_taken:
                    actions_taken = session_tools.recorded_actions

                action_summary = (
                    "; ".join([a["description"] for a in actions_taken])
                    if actions_taken
                    else "No actions performed (observing)"
                )

                # Segment logcat logs dynamically for this step
                step_end_time = datetime.utcnow()
                step_duration = (step_end_time - step_start_time).total_seconds()

                current_logcat = fleet_manager.dump_logcat(device_id)
                step_logs = current_logcat[step_start_logcat_len:]

                # Create structured telemetry log event with both high-res and low-res versions
                event_data = {
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "emulator_id": device_id,
                    "run_id": run_id,
                    "package_name": package_name,
                    "step_index": step + 1,
                    "start_time": step_start_time.isoformat() + "Z",
                    "duration": round(step_duration, 2),
                    "screenshot": base64_screenshot,
                    "screenshot_path": f"/runs/{run_id}/{screenshot_filename}",
                    "screenshot_llm": base64_screenshot_llm,
                    "screenshot_llm_path": f"/runs/{run_id}/{screenshot_llm_filename}",
                    "agent_reasoning": reasoning,
                    "actions_taken": actions_taken,
                    "action_summary": action_summary,
                    "logs": step_logs,
                    "has_screenshot": True,
                    "has_logs": bool(step_logs)
                }
                telemetry_collector.record_event(event_data)

                # Persist step telemetry incrementally on disk
                telemetry_events.append(event_data)
                with open(os.path.join(run_dir, "telemetry_summary.json"), "w") as tf:
                    json.dump(telemetry_events, tf, indent=2)

                # Push real-time visual streaming update to dashboard
                logs_callback(
                    {
                        "status": "playing",
                        "state": "acting" if actions_taken else "waiting",
                        "step": step + 1,
                        "max_steps": max_steps,
                        "start_time": step_start_time.isoformat() + "Z",
                        "duration": round(step_duration, 2),
                        "screenshot": base64_screenshot,
                        "screenshot_llm": base64_screenshot_llm,
                        "reasoning": reasoning,
                        "action": action_summary,
                        "actions_taken": actions_taken,
                        "message": f"Step {step + 1}: {action_summary}",
                    }
                )

                # Short dynamic buffer between loops
                await asyncio.sleep(0.8)

        # Step 3: Session End Telemetry & Cleanups
        logs_callback(
            {"status": "finishing", "state": "waiting", "message": "Stopping app and dumping logcats..."}
        )
        fleet_manager.force_stop_app(device_id, package_name)

        # Stop background streamer and dump final logs
        if log_task and not log_task.done():
            log_task.cancel()
            try:
                await log_task
            except asyncio.CancelledError:
                pass

        logcat_data = fleet_manager.dump_logcat(device_id)
        with open(logcat_filepath, "w") as lf:
            lf.write(logcat_data)

        # Update final run_config
        is_stopped = run_config.get("status") == "stopped"
        run_config["status"] = "stopped" if is_stopped else "completed"
        with open(os.path.join(run_dir, "run_config.json"), "w") as f:
            json.dump(run_config, f, indent=2)

        final_event = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "emulator_id": device_id,
            "run_id": run_id,
            "package_name": package_name,
            "step_index": 999,  # session end
            "screenshot": "",
            "agent_reasoning": f"Session completed. Final Outcome: {session_tools.completion_reason or 'Max steps reached'}",
            "actions_taken": [],
            "action_summary": "Session terminated.",
            "logs": logcat_data,
        }
        telemetry_collector.record_event(final_event)

        logs_callback(
            {
                "status": "completed" if not is_stopped else "failed",
                "message": f"Successfully completed. Logs size: {len(logcat_data)} bytes." if not is_stopped else "Play session stopped by user.",
                "logs": logcat_data[:10000],
            }
        )

    except Exception as e:
        logger.error(f"Error running agent loop on {device_id}: {e}")
        run_config["status"] = "failed"
        import traceback
        run_config["error"] = str(e)
        run_config["traceback"] = traceback.format_exc()
        with open(os.path.join(run_dir, "run_config.json"), "w") as f:
            json.dump(run_config, f, indent=2)
        logs_callback({"status": "failed", "message": f"Agent crashed: {str(e)}"})
        
        if log_task and not log_task.done():
            log_task.cancel()


async def run_mock_play_loop(
    device_id: str,
    apk_path: str,
    package_name: str,
    instructions: str,
    run_id: str,
    run_dir: str,
    session_tools: DeviceAgentTools,
    telemetry_collector: TelemetryCollector,
    logs_callback: Callable[[Dict[str, Any]], None],
    max_steps: int,
    is_stopped_callback: Optional[Callable[[], bool]] = None,
):
    """Fallback playback simulator with cancellation, config, and timeline support."""
    import random
    import json

    run_config = {
        "run_id": run_id,
        "device_id": device_id,
        "apk_name": os.path.basename(apk_path),
        "package_name": "com.unity.simulated_player",
        "instructions": instructions,
        "max_steps": max_steps,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "status": "playing"
    }
    with open(os.path.join(run_dir, "run_config.json"), "w") as f:
        json.dump(run_config, f, indent=2)

    telemetry_events = []
    last_logcat_len = 0
    logcat_filepath = os.path.join(run_dir, "device_logcat.log")

    logs_callback(
        {
            "status": "playing",
            "state": "thinking",
            "message": "Booted Player In Mock Agent Mode (ADB Telemetry Ingestion Active)",
        }
    )

    mock_actions = [
        {
            "desc": "Tapped relative coordinate (0.5, 0.72) (Start Button)",
            "run": lambda: session_tools.tap(0.5, 0.72),
        },
        {
            "desc": "Swiped left to scroll menu",
            "run": lambda: session_tools.swipe(0.8, 0.5, 0.2, 0.5, 400),
        },
        {
            "desc": "Tapped relative coordinate (0.3, 0.44) (Select Level 1)",
            "run": lambda: session_tools.tap(0.3, 0.44),
        },
        {
            "desc": "Tapped relative coordinate (0.5, 0.5) (Quickplay Play)",
            "run": lambda: session_tools.tap(0.5, 0.5),
        },
        {
            "desc": "Pressed Back Button to exit ads popup",
            "run": lambda: session_tools.go_back(),
        },
        {
            "desc": "Waited 2.0s for level loading",
            "run": lambda: session_tools.wait_seconds(2.0),
        },
    ]

    # Background log streamer for mock
    async def mock_log_streamer():
        try:
            while not session_tools.session_completed:
                logcat_data = session_tools.fleet_manager.dump_logcat(device_id)
                with open(logcat_filepath, "w") as lf:
                    lf.write(logcat_data)
                logs_callback({
                    "status": "playing",
                    "logs_update": logcat_data,
                })
                await asyncio.sleep(5.0)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in mock log streamer: {e}")

    log_task = asyncio.create_task(mock_log_streamer())

    try:
        # Keep the target device awake, wake up the screen, and dismiss keyguard
        session_tools.fleet_manager.keep_device_awake(device_id)

        for step in range(max_steps):
            step_start_time = datetime.utcnow()
            step_start_logcat_len = len(session_tools.fleet_manager.dump_logcat(device_id))

            # Check for cancellation
            if is_stopped_callback and is_stopped_callback():
                logger.info(f"Mock run {run_id} received stop signal.")
                session_tools.session_completed = True
                session_tools.completion_reason = "Stopped by user request"
                run_config["status"] = "stopped"
                with open(os.path.join(run_dir, "run_config.json"), "w") as f:
                    json.dump(run_config, f, indent=2)
                logs_callback({"status": "failed", "message": "Mock session stopped by user request."})
                break

            logs_callback(
                {
                    "status": "playing",
                    "state": "screenshotting",
                    "step": step + 1,
                    "max_steps": max_steps,
                    "message": f"Step {step + 1}/{max_steps}: Capturing visual frame...",
                }
            )

            screenshot_filename = f"step_{step}_{int(datetime.utcnow().timestamp())}.png"
            screenshot_path = os.path.join(run_dir, screenshot_filename)
            session_tools.fleet_manager.take_screenshot(device_id, screenshot_path)

            # Generate LLM resized screenshot
            screenshot_llm_filename = screenshot_filename.replace(".png", "_llm.png")
            screenshot_llm_path = os.path.join(run_dir, screenshot_llm_filename)
            resize_screenshot(screenshot_path, screenshot_llm_path, max_dimension=384)

            with open(screenshot_path, "rb") as img:
                base64_screenshot = base64.b64encode(img.read()).decode("utf-8")

            base64_screenshot_llm = ""
            if os.path.exists(screenshot_llm_path):
                with open(screenshot_llm_path, "rb") as img:
                    base64_screenshot_llm = base64.b64encode(img.read()).decode("utf-8")

            # Stream screenshot immediately
            logs_callback(
                {
                    "status": "playing",
                    "state": "thinking",
                    "step": step + 1,
                    "max_steps": max_steps,
                    "screenshot": base64_screenshot,
                    "screenshot_llm": base64_screenshot_llm,
                    "message": f"Step {step + 1}/{max_steps}: Thinking about board strategy...",
                }
            )

            await asyncio.sleep(1.0) # simulate gemini thinking (briefly)

            session_tools.recorded_actions = []

            # Pick a mock action
            action_item = random.choice(mock_actions)
            action_item["run"]()

            actions_taken = session_tools.recorded_actions
            action_summary = action_item["desc"]
            reasoning = f"**Analyzing board state**\nVisual analysis detects gameplay frame. Decided action: {action_summary} to achieve instructions.\n\n**Action detail**\nExecuting relative input parameters dynamically."

            # Segment mock logcat logs
            step_end_time = datetime.utcnow()
            step_duration = (step_end_time - step_start_time).total_seconds()

            current_logcat = session_tools.fleet_manager.dump_logcat(device_id)
            step_logs = current_logcat[step_start_logcat_len:]

            event_data = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "emulator_id": device_id,
                "run_id": run_id,
                "package_name": "com.unity.simulated_player",
                "step_index": step + 1,
                "start_time": step_start_time.isoformat() + "Z",
                "duration": round(step_duration, 2),
                "screenshot": base64_screenshot,
                "screenshot_path": f"/runs/{run_id}/{screenshot_filename}",
                "screenshot_llm": base64_screenshot_llm,
                "screenshot_llm_path": f"/runs/{run_id}/{screenshot_llm_filename}",
                "agent_reasoning": reasoning,
                "actions_taken": actions_taken,
                "action_summary": action_summary,
                "logs": step_logs,
                "has_screenshot": True,
                "has_logs": bool(step_logs)
            }
            telemetry_collector.record_event(event_data)

            telemetry_events.append(event_data)
            with open(os.path.join(run_dir, "telemetry_summary.json"), "w") as tf:
                json.dump(telemetry_events, tf, indent=2)

            logs_callback(
                {
                    "status": "playing",
                    "state": "acting",
                    "step": step + 1,
                    "max_steps": max_steps,
                    "start_time": step_start_time.isoformat() + "Z",
                    "duration": round(step_duration, 2),
                    "screenshot": base64_screenshot,
                    "screenshot_llm": base64_screenshot_llm,
                    "reasoning": reasoning,
                    "action": action_summary,
                    "message": f"Step {step + 1}: {action_summary}",
                }
            )

            await asyncio.sleep(1.0)

        # Cleanups
        logs_callback(
            {"status": "finishing", "state": "waiting", "message": "Stopping app and dumping logcats..."}
        )

        if log_task and not log_task.done():
            log_task.cancel()
            try:
                await log_task
            except asyncio.CancelledError:
                pass

        logcat_data = session_tools.fleet_manager.dump_logcat(device_id)
        with open(logcat_filepath, "w") as lf:
            lf.write(logcat_data)

        # Update final run_config
        is_stopped = run_config.get("status") == "stopped"
        run_config["status"] = "stopped" if is_stopped else "completed"
        with open(os.path.join(run_dir, "run_config.json"), "w") as f:
            json.dump(run_config, f, indent=2)

        final_event = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "emulator_id": device_id,
            "run_id": run_id,
            "package_name": "com.unity.simulated_player",
            "step_index": 999,
            "screenshot": "",
            "agent_reasoning": "Mock gameplay simulation completed successfully.",
            "actions_taken": [],
            "action_summary": "Session terminated.",
            "logs": logcat_data,
        }
        telemetry_collector.record_event(final_event)

        logs_callback(
            {
                "status": "completed" if not is_stopped else "failed",
                "message": "Completed. Logcat size: " + str(len(logcat_data)) + " bytes." if not is_stopped else "Mock session stopped by user.",
                "logs": logcat_data[:10000],
            }
        )

    except Exception as e:
        logger.error(f"Error in mock agent loop: {e}")
        run_config["status"] = "failed"
        import traceback
        run_config["error"] = str(e)
        run_config["traceback"] = traceback.format_exc()
        with open(os.path.join(run_dir, "run_config.json"), "w") as f:
            json.dump(run_config, f, indent=2)
        logs_callback({"status": "failed", "message": f"Mock crashed: {str(e)}"})
        
        if log_task and not log_task.done():
            log_task.cancel()

