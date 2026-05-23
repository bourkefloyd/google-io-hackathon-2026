import os
import asyncio
import base64
import logging
from datetime import datetime
from typing import Callable, List, Dict, Any

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
):
    """Orchestrates the entire visual playing loop for a simulated player."""
    run_dir = os.path.join("runs", run_id)
    os.makedirs(run_dir, exist_ok=True)

    try:
        # Step 1: Install & Prepare
        logs_callback({"status": "starting", "message": "Installing APK build..."})
        if not fleet_manager.install_apk(device_id, apk_path):
            logs_callback({"status": "failed", "message": "Failed to install APK."})
            return

        # Clear logcats for clean buffer telemetry
        fleet_manager.clear_logcat(device_id)

        logs_callback({"status": "starting", "message": "Launching application..."})
        if not fleet_manager.launch_app(device_id, package_name):
            logs_callback(
                {"status": "failed", "message": "Failed to launch application."}
            )
            return

        await asyncio.sleep(4.0)  # Let app load

        # Step 2: Initialize tools and AGY Agent
        session_tools = DeviceAgentTools(device_id, fleet_manager)

        # Mock mode fallback if Antigravity SDK is not fully wired or GEMINI_API_KEY is not configured
        if not AGY_AVAILABLE or not os.getenv("GEMINI_API_KEY"):
            logger.warning(
                "google-antigravity SDK not found or GEMINI_API_KEY not configured. Running in MOCK agent playback mode."
            )
            await run_mock_play_loop(
                device_id,
                run_dir,
                session_tools,
                telemetry_collector,
                logs_callback,
                max_steps,
            )
            return

        logs_callback(
            {
                "status": "playing",
                "message": "Booting Google Antigravity autonomous play agent...",
            }
        )

        config = LocalAgentConfig(
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
                "You inspect the game via screenshot frames and execute relative inputs. Always think step-by-step."
            ),
        )

        async with Agent(config=config) as agent:
            # Warm up prompt
            startup_prompt = (
                f"Begin playing the game now. You are simulating a player. The instructions are: '{instructions}'.\n"
                "Please output your reasoning and execute your initial action sequence."
            )
            response = await agent.chat(startup_prompt)
            logger.info(f"Agent startup response: {await response.text()}")

            for step in range(max_steps):
                if session_tools.session_completed:
                    logger.info("Session completed by agent request.")
                    break

                logs_callback(
                    {
                        "status": "playing",
                        "message": f"Evaluating frame step {step + 1}/{max_steps}...",
                    }
                )

                # Take visual screenshot
                screenshot_filename = (
                    f"step_{step}_{int(datetime.utcnow().timestamp())}.png"
                )
                screenshot_path = os.path.join(run_dir, screenshot_filename)
                if not fleet_manager.take_screenshot(device_id, screenshot_path):
                    logs_callback(
                        {
                            "status": "playing",
                            "message": "Warning: screenshot capture failed, retrying...",
                        }
                    )
                    await asyncio.sleep(2.0)
                    continue

                # Convert to base64 for real-time frontend streaming
                with open(screenshot_path, "rb") as image_file:
                    base64_screenshot = base64.b64encode(image_file.read()).decode(
                        "utf-8"
                    )

                # Clear previous recorded actions to isolate this step's events
                session_tools.recorded_actions = []

                # Send screenshot to agent to evaluate next moves
                image = Image.from_file(screenshot_path)
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
                reasoning = (
                    "".join(thoughts) if thoughts else await agent_response.text()
                )

                # Fetch actions executed during the tool calls of this turn
                actions_taken = session_tools.recorded_actions
                action_summary = (
                    "; ".join([a["description"] for a in actions_taken])
                    if actions_taken
                    else "No actions performed (observing)"
                )

                # Create structured telemetry log event for timeseries
                event_data = {
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "emulator_id": device_id,
                    "run_id": run_id,
                    "package_name": package_name,
                    "step_index": step + 1,
                    "screenshot": base64_screenshot,
                    "agent_reasoning": reasoning,
                    "actions_taken": actions_taken,
                    "action_summary": action_summary,
                    "logs": None,
                }
                telemetry_collector.record_event(event_data)

                # Push real-time visual streaming update to dashboard
                logs_callback(
                    {
                        "status": "playing",
                        "step": step + 1,
                        "max_steps": max_steps,
                        "screenshot": base64_screenshot,
                        "reasoning": reasoning,
                        "action": action_summary,
                        "message": f"Step {step + 1}: {action_summary}",
                    }
                )

                # Short buffer between loops
                await asyncio.sleep(2.0)

        # Step 3: Session End Telemetry & Cleanups
        logs_callback(
            {"status": "finishing", "message": "Stopping app and dumping logcats..."}
        )
        fleet_manager.force_stop_app(device_id, package_name)

        # Retrieve logs and send final completion event
        logcat_data = fleet_manager.dump_logcat(device_id)

        final_event = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "emulator_id": device_id,
            "run_id": run_id,
            "package_name": package_name,
            "step_index": 999,  # code for session end
            "screenshot": "",
            "agent_reasoning": f"Session completed. Final Outcome: {session_tools.completion_reason or 'Max steps reached'}",
            "actions_taken": [],
            "action_summary": "Session terminated.",
            "logs": logcat_data,
        }
        telemetry_collector.record_event(final_event)

        logs_callback(
            {
                "status": "completed",
                "message": f"Successfully completed. Logs size: {len(logcat_data)} bytes.",
                "logs": logcat_data[
                    :5000
                ],  # Send first 5000 characters to frontend log window
            }
        )

    except Exception as e:
        logger.error(f"Error running agent loop on {device_id}: {e}")
        logs_callback({"status": "failed", "message": f"Agent crashed: {str(e)}"})


async def run_mock_play_loop(
    device_id: str,
    run_dir: str,
    session_tools: DeviceAgentTools,
    telemetry_collector: TelemetryCollector,
    logs_callback: Callable[[Dict[str, Any]], None],
    max_steps: int,
):
    """Fallback playback simulator if google-antigravity SDK python package is not fully initialized."""
    import random

    logs_callback(
        {
            "status": "playing",
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

    for step in range(max_steps):
        logs_callback(
            {
                "status": "playing",
                "message": f"Evaluating frame step {step + 1}/{max_steps}...",
            }
        )

        screenshot_path = os.path.join(
            run_dir, f"step_{step}_{int(datetime.utcnow().timestamp())}.png"
        )
        session_tools.fleet_manager.take_screenshot(device_id, screenshot_path)

        with open(screenshot_path, "rb") as img:
            base64_screenshot = base64.b64encode(img.read()).decode("utf-8")

        session_tools.recorded_actions = []

        # Pick a mock action
        action_item = random.choice(mock_actions)
        action_item["run"]()

        actions_taken = session_tools.recorded_actions
        action_summary = action_item["desc"]
        reasoning = f"Visual analysis detects gameplay frame. Decided action: {action_summary} to achieve instructions."

        event_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "emulator_id": device_id,
            "run_id": session_tools.device_id,
            "package_name": "com.unity.simulated_player",
            "step_index": step + 1,
            "screenshot": base64_screenshot,
            "agent_reasoning": reasoning,
            "actions_taken": actions_taken,
            "action_summary": action_summary,
            "logs": None,
        }
        telemetry_collector.record_event(event_data)

        logs_callback(
            {
                "status": "playing",
                "step": step + 1,
                "max_steps": max_steps,
                "screenshot": base64_screenshot,
                "reasoning": reasoning,
                "action": action_summary,
                "message": f"Step {step + 1}: {action_summary}",
            }
        )

        await asyncio.sleep(3.0)

    logs_callback(
        {"status": "finishing", "message": "Stopping app and dumping logcats..."}
    )
    logcat_data = session_tools.fleet_manager.dump_logcat(device_id)

    final_event = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "emulator_id": device_id,
        "run_id": session_tools.device_id,
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
            "status": "completed",
            "message": f"Completed. Logcat size: {len(logcat_data)} bytes.",
            "logs": logcat_data[:5000],
        }
    )
