import subprocess
import os
import re
import logging
from typing import List, Dict, Optional

logger = logging.getLogger("fleet_manager")
logging.basicConfig(level=logging.INFO)


class FleetManager:
    def __init__(self):
        # Maps device_id -> session metrics to generate responsive screenshots
        self._step_counters: Dict[str, int] = {}
        self._last_actions: Dict[str, str] = {}
        self._last_taps: Dict[str, Optional[tuple]] = {}
        self._last_swipes: Dict[str, Optional[tuple]] = {}
        self._apk_details_cache: Dict[str, Dict[str, str]] = {}

    def get_device_details(self, device_id: str) -> Dict[str, str]:
        """Gets device model, brand, type (emulator/physical), and resolution."""
        if "mock" in device_id:
            return {
                "id": device_id,
                "model": "Simulated Pixel 6 Pro",
                "brand": "Google",
                "type": "emulator",
                "resolution": "1080x1920",
                "name": "Simulated Pixel 6 Pro (mock)",
            }

        # Query model
        res_model = self.run_cmd(
            ["adb", "-s", device_id, "shell", "getprop", "ro.product.model"]
        )
        model = res_model.stdout.strip() if res_model.returncode == 0 else ""
        if not model:
            model = "Android Device"

        # Query brand
        res_brand = self.run_cmd(
            ["adb", "-s", device_id, "shell", "getprop", "ro.product.brand"]
        )
        brand = (
            res_brand.stdout.strip().capitalize() if res_brand.returncode == 0 else ""
        )

        # Query hardware to determine if emulator
        res_hw = self.run_cmd(
            ["adb", "-s", device_id, "shell", "getprop", "ro.hardware"]
        )
        hw = res_hw.stdout.strip().lower() if res_hw.returncode == 0 else ""

        is_emulator = "emulator" in device_id.lower() or any(
            x in hw for x in ["goldfish", "ranchu", "gsi", "virtual"]
        )
        device_type = "emulator" if is_emulator else "physical"

        # Query resolution
        res = self.get_device_resolution(device_id)
        resolution_str = f"{res['width']}x{res['height']}"

        # Build elegant user-facing name
        if is_emulator:
            name = f"Android Virtual Device ({model})"
        else:
            brand_prefix = (
                f"{brand} "
                if brand and not model.lower().startswith(brand.lower())
                else ""
            )
            name = f"{brand_prefix}{model} ({device_id})"

        return {
            "id": device_id,
            "model": model,
            "brand": brand,
            "type": device_type,
            "resolution": resolution_str,
            "name": name,
        }

    @staticmethod
    def run_cmd(args: List[str], timeout: float = 30.0) -> subprocess.CompletedProcess:
        """Helper to run shell command safely, catching FileNotFoundError gracefully."""
        try:
            return subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as e:
            logger.error(f"Command timed out: {' '.join(args)}")
            raise e
        except FileNotFoundError:
            logger.warning(
                f"System command not found: '{args[0]}'. Ensuring safety by returning command-not-found completion process."
            )
            return subprocess.CompletedProcess(
                args=args,
                returncode=127,
                stdout="",
                stderr=f"sh: {args[0]}: command not found",
            )

    @classmethod
    def is_adb_available(cls) -> bool:
        """Helper to check if Android ADB CLI is installed and configured in the system PATH."""
        try:
            res = subprocess.run(
                ["adb", "--version"], capture_output=True, text=True, timeout=2.0
            )
            return res.returncode == 0
        except FileNotFoundError:
            return False

    def list_devices(self) -> List[str]:
        """Runs 'adb devices' and parses connected emulator serials, falling back to simulated mock pixel devices."""
        if not self.is_adb_available():
            logger.warning(
                "Android Platform Tools (adb) not found in system PATH. Fallback to Simulated Mock Emulator active."
            )
            return ["emulator-5554-mock"]

        res = self.run_cmd(["adb", "devices"])
        if res.returncode != 0:
            logger.error(f"Failed to list devices: {res.stderr}")
            return ["emulator-5554-mock"]

        devices = []
        # Parse output like:
        # List of devices attached
        # emulator-5554	device
        for line in res.stdout.strip().split("\n")[1:]:
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                devices.append(parts[0])

        if not devices:
            logger.info(
                "No physical or virtual devices connected via ADB. Instantiating local Simulated Mock Emulator."
            )
            return ["emulator-5554-mock"]

        return devices

    def get_device_resolution(self, device_id: str) -> Dict[str, int]:
        """Gets screen size in pixels using adb shell wm size."""
        if "mock" in device_id:
            return {"width": 1080, "height": 1920}

        res = self.run_cmd(["adb", "-s", device_id, "shell", "wm", "size"])
        if res.returncode != 0:
            logger.warning(
                f"Could not get resolution for {device_id}, defaulting to 1080x1920: {res.stderr}"
            )
            return {"width": 1080, "height": 1920}

        # Output format: "Physical size: 1080x1920"
        match = re.search(r"(\d+)x(\d+)", res.stdout)
        if match:
            return {"width": int(match.group(1)), "height": int(match.group(2))}
        return {"width": 1080, "height": 1920}

    def get_apk_details(self, apk_path: str) -> Optional[Dict[str, str]]:
        """Parses package name and version information from the APK."""
        if not os.path.exists(apk_path):
            return None
        if hasattr(self, "_apk_details_cache") and apk_path in self._apk_details_cache:
            return self._apk_details_cache[apk_path]
        try:
            from pyaxmlparser import APK

            apk = APK(apk_path)
            details = {
                "package": apk.package,
                "version_name": apk.version_name,
                "version_code": apk.version_code,
            }
            if not hasattr(self, "_apk_details_cache"):
                self._apk_details_cache = {}
            self._apk_details_cache[apk_path] = details
            return details
        except Exception as e:
            logger.error(f"Failed to parse APK details from {apk_path}: {e}")
            return None

    def get_installed_package_details(
        self, device_id: str, package_name: str
    ) -> Optional[Dict[str, str]]:
        """Gets installed package details (versionName, versionCode) from the device."""
        if "mock" in device_id:
            # For mock/simulated play runs, return matching details for the default package
            if package_name == "com.unity.simulated_player":
                return {"version_name": "1.0", "version_code": "1"}
            return None

        res = self.run_cmd(
            ["adb", "-s", device_id, "shell", "dumpsys", "package", package_name]
        )
        if res.returncode != 0 or not res.stdout:
            return None

        version_code = None
        version_name = None

        for line in res.stdout.splitlines():
            line = line.strip()
            if line.startswith("versionCode="):
                match = re.search(r"versionCode=(\d+)", line)
                if match:
                    version_code = match.group(1)
            elif line.startswith("versionName="):
                version_name = line.split("=", 1)[1].strip()

        if version_code or version_name:
            return {"version_name": version_name, "version_code": version_code}
        return None

    def install_apk(self, device_id: str, apk_path: str) -> bool:
        """Installs the provided APK on the specific device, only if not already installed with the same version."""
        if "mock" in device_id:
            logger.info(
                f"[MOCK ADB] Simulating APK install for path: {apk_path} on target: {device_id}"
            )
            self._step_counters[device_id] = 0
            self._last_actions[device_id] = "Simulated APK Installed Successfully"
            self._last_taps[device_id] = None
            self._last_swipes[device_id] = None
            return True

        if not os.path.exists(apk_path):
            logger.error(f"APK file not found: {apk_path}")
            return False

        # Parse APK details
        apk_details = self.get_apk_details(apk_path)
        if apk_details and apk_details.get("package"):
            package_name = apk_details["package"]
            apk_version_code = str(apk_details.get("version_code") or "")
            apk_version_name = str(apk_details.get("version_name") or "")

            installed_details = self.get_installed_package_details(
                device_id, package_name
            )
            if installed_details:
                inst_version_code = str(installed_details.get("version_code") or "")
                inst_version_name = str(installed_details.get("version_name") or "")

                logger.info(
                    f"Package {package_name} is installed on {device_id}. APK version: {apk_version_name} ({apk_version_code}), Installed version: {inst_version_name} ({inst_version_code})"
                )

                # If version code and version name match, skip installation!
                if (
                    apk_version_code == inst_version_code
                    and apk_version_name == inst_version_name
                ):
                    logger.info(
                        "APK version matches installed version. Skipping installation."
                    )
                    return True
                else:
                    logger.info("APK version mismatch. Re-installing package...")
            else:
                logger.info(
                    f"Package {package_name} is not installed on {device_id}. Installing..."
                )
        else:
            logger.warning(
                f"Could not parse APK details from {apk_path}. Proceeding with standard installation."
            )

        logger.info(f"Installing {apk_path} on device {device_id}...")
        res = self.run_cmd(["adb", "-s", device_id, "install", "-r", apk_path])
        if res.returncode != 0:
            logger.error(f"Failed to install APK: {res.stderr}")
            return False
        logger.info(f"Successfully installed APK on {device_id}.")
        return True

    def launch_app(
        self, device_id: str, package_name: str, activity_name: Optional[str] = None
    ) -> bool:
        """Launches the app. If activity_name is not provided, tries to resolve launcher activity."""
        if "mock" in device_id:
            logger.info(
                f"[MOCK ADB] Simulating application startup sequence for package: {package_name} on {device_id}"
            )
            self._last_actions[device_id] = f"Launched Game Package '{package_name}'"
            self._last_taps[device_id] = None
            self._last_swipes[device_id] = None
            return True

        if not activity_name:
            # Try to resolve main activity
            cmd = f"cmd package resolve-activity --brief {package_name} | tail -n 1"
            res = self.run_cmd(["adb", "-s", device_id, "shell", cmd])
            if res.returncode == 0 and "/" in res.stdout:
                activity_name = res.stdout.strip()
            else:
                # Fallback to monkey launch
                logger.info(
                    f"Could not resolve activity, launching {package_name} via monkey..."
                )
                monkey_res = self.run_cmd(
                    [
                        "adb",
                        "-s",
                        device_id,
                        "shell",
                        "monkey",
                        "-p",
                        package_name,
                        "-c",
                        "android.intent.category.LAUNCHER",
                        "1",
                    ]
                )
                return monkey_res.returncode == 0

        logger.info(f"Launching {activity_name} on {device_id}...")
        res = self.run_cmd(
            ["adb", "-s", device_id, "shell", "am", "start", "-n", activity_name]
        )
        return res.returncode == 0

    def keep_device_awake(self, device_id: str) -> None:
        """Keeps the physical or virtual device awake, wakes it up, and dismisses keyguard."""
        if "mock" in device_id:
            logger.info(f"[MOCK ADB] Simulating keeping device awake on {device_id}")
            return

        logger.info(f"Ensuring device {device_id} stays awake, waking up screen, and dismissing keyguard.")
        self.run_cmd(["adb", "-s", device_id, "shell", "svc", "power", "stayon", "true"])
        self.run_cmd(["adb", "-s", device_id, "shell", "input", "keyevent", "224"])
        self.run_cmd(["adb", "-s", device_id, "shell", "wm", "dismiss-keyguard"])

    def force_stop_app(self, device_id: str, package_name: str) -> None:
        """Kills the app."""
        if "mock" in device_id:
            logger.info(
                f"[MOCK ADB] Simulating application teardown for package: {package_name} on {device_id}"
            )
            self._last_actions[device_id] = f"Force-Stopped Game '{package_name}'"
            return

        self.run_cmd(
            ["adb", "-s", device_id, "shell", "am", "force-stop", package_name]
        )

    def clear_logcat(self, device_id: str) -> None:
        """Clears logcat buffer."""
        if "mock" in device_id:
            logger.info(
                f"[MOCK ADB] Clearing local simulated logcat buffer on {device_id}"
            )
            return

        logger.info(f"Clearing logcat buffer on {device_id}...")
        self.run_cmd(["adb", "-s", device_id, "logcat", "-c"])

    def dump_logcat(self, device_id: str) -> str:
        """Dumps current logcat buffer in memory."""
        if "mock" in device_id:
            logger.info(
                f"[MOCK ADB] Compiling and dumping gameplay logcats from {device_id}..."
            )
            return self.compile_mock_logcat()

        logger.info(f"Dumping logcat from {device_id}...")
        res = self.run_cmd(["adb", "-s", device_id, "logcat", "-d"])
        return res.stdout

    def take_screenshot(self, device_id: str, output_path: str) -> bool:
        """Saves device screenshot directly to output_path using piping."""
        if "mock" in device_id:
            # Increment steps and render a premium gorgeous mock screenshot dynamically using Pillow
            self._step_counters[device_id] = self._step_counters.get(device_id, 0) + 1
            return self.generate_mock_screenshot(device_id, output_path)

        try:
            # We use exec-out screencap -p to capture and transfer directly via stdout
            with open(output_path, "wb") as f:
                subprocess.run(
                    ["adb", "-s", device_id, "exec-out", "screencap", "-p"],
                    stdout=f,
                    stderr=subprocess.PIPE,
                    timeout=10.0,
                )
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                try:
                    from PIL import Image as PILImage
                    img = PILImage.open(output_path)
                    img.thumbnail((540, 1200))
                    img.save(output_path, "PNG")
                    logger.info(f"Optimized screenshot from device: size reduced to {os.path.getsize(output_path)//1024}KB")
                except Exception as ex:
                    logger.error(f"Failed to optimize screenshot: {ex}")
                return True
            return False
        except Exception as e:
            logger.error(f"Error capturing screenshot for {device_id}: {e}")
            return False

    def execute_tap(self, device_id: str, rel_x: float, rel_y: float) -> str:
        """Executes tap using relative normalized coordinates (0.0 to 1.0)."""
        res = self.get_device_resolution(device_id)
        abs_x = int(rel_x * res["width"])
        abs_y = int(rel_y * res["height"])

        if "mock" in device_id:
            logger.info(
                f"[MOCK ADB] Tapped coordinates: normalized=({rel_x:.2f}, {rel_y:.2f}), absolute=({abs_x}, {abs_y})"
            )
            self._last_actions[device_id] = (
                f"Executed Tap Action at ({rel_x:.2f}, {rel_y:.2f})"
            )
            self._last_taps[device_id] = (rel_x, rel_y)
            self._last_swipes[device_id] = None
            return f"adb shell input tap {abs_x} {abs_y}"

        cmd = ["adb", "-s", device_id, "shell", "input", "tap", str(abs_x), str(abs_y)]
        self.run_cmd(cmd)
        return f"adb shell input tap {abs_x} {abs_y}"

    def execute_swipe(
        self,
        device_id: str,
        rel_x1: float,
        rel_y1: float,
        rel_x2: float,
        rel_y2: float,
        duration_ms: int = 300,
    ) -> str:
        """Executes swipe using relative normalized coordinates (0.0 to 1.0)."""
        res = self.get_device_resolution(device_id)
        abs_x1 = int(rel_x1 * res["width"])
        abs_y1 = int(rel_y1 * res["height"])
        abs_x2 = int(rel_x2 * res["width"])
        abs_y2 = int(rel_y2 * res["height"])

        if "mock" in device_id:
            logger.info(
                f"[MOCK ADB] Swiped from ({rel_x1:.2f}, {rel_y1:.2f}) to ({rel_x2:.2f}, {rel_y2:.2f})"
            )
            self._last_actions[device_id] = (
                f"Executed Swipe from ({rel_x1:.2f}, {rel_y1:.2f}) to ({rel_x2:.2f}, {rel_y2:.2f})"
            )
            self._last_taps[device_id] = None
            self._last_swipes[device_id] = (rel_x1, rel_y1, rel_x2, rel_y2)
            return f"adb shell input swipe {abs_x1} {abs_y1} {abs_x2} {abs_y2} {duration_ms}"

        cmd = [
            "adb",
            "-s",
            device_id,
            "shell",
            "input",
            "swipe",
            str(abs_x1),
            str(abs_y1),
            str(abs_x2),
            str(abs_y2),
            str(duration_ms),
        ]
        self.run_cmd(cmd)
        return (
            f"adb shell input swipe {abs_x1} {abs_y1} {abs_x2} {abs_y2} {duration_ms}"
        )

    def execute_text(self, device_id: str, text: str) -> str:
        """Enters text input."""
        if "mock" in device_id:
            logger.info(
                f"[MOCK ADB] Inputting text telemetry: '{text}' on device: {device_id}"
            )
            self._last_actions[device_id] = f"Input Text string: '{text}'"
            self._last_taps[device_id] = None
            self._last_swipes[device_id] = None
            return f"adb shell input text '{text}'"

        # Sanitize spaces for adb shell input text
        sanitized = text.replace(" ", "%s")
        cmd = ["adb", "-s", device_id, "shell", "input", "text", sanitized]
        self.run_cmd(cmd)
        return f"adb shell input text '{text}'"

    def execute_keyevent(self, device_id: str, key_code: int) -> str:
        """Sends key event (e.g. back button = 4, home button = 3)."""
        if "mock" in device_id:
            logger.info(
                f"[MOCK ADB] Dispatched Keyevent: {key_code} on device: {device_id}"
            )
            self._last_actions[device_id] = (
                f"Dispatched keyevent {key_code} (Back/Home)"
            )
            self._last_taps[device_id] = None
            self._last_swipes[device_id] = None
            return f"adb shell input keyevent {key_code}"

        cmd = ["adb", "-s", device_id, "shell", "input", "keyevent", str(key_code)]
        self.run_cmd(cmd)
        return f"adb shell input keyevent {key_code}"

    def compile_mock_logcat(self) -> str:
        """Compiles a highly realistic Android & Unity game engine logcat stream."""
        from datetime import datetime

        now = datetime.now().strftime("%m-%d %H:%M:%S.%f")[:-3]
        log_lines = [
            f"{now}  1200  1230 I ActivityManager: Start proc com.unity.simulated_player for activity com.unity.simulated_player/com.unity3d.player.UnityPlayerActivity",
            f"{now}  1200  1245 D dalvikvm: Late-enabling CheckJNI",
            f"{now}  1200  1230 I AndroidRuntime: Calling main entry com.unity.simulated_player",
            f"{now}  1200  1250 I Unity   :  [Version] Unity Engine v2022.3.12f1 (arm64)",
            f"{now}  1200  1250 I Unity   :  [OS] Android OS 12 / API-31",
            f"{now}  1200  1250 I Unity   :  [Device] Simulated Google Pixel 6 Pro",
            f"{now}  1200  1250 I Unity   :  [Graphics] Vulkan API initialized successfully",
            f"{now}  1200  1250 I Unity   : ScreenManager: Window size 1080x1920",
            f"{now}  1200  1252 D Unity   : GL_OES_EGL_image GL_OES_EGL_image_external GL_OES_EGL_sync GL_OES_vertex_half_float",
            f"{now}  1200  1250 I Unity   : [PlayerFleetTelemetry] Initializing telemetry ingestion loop...",
            f"{now}  1200  1250 I Unity   : [PlayerFleetTelemetry] Local endpoint: http://localhost:8000/api/telemetry",
            f"{now}  1200  1255 I Unity   : LoadScene: Loading level 'Scene_MainMenu' in background...",
            f"{now}  1200  1260 I Unity   : SceneLoad: Scene_MainMenu loaded in 0.42 seconds",
            f"{now}  1200  1260 D Unity   : [UI] Loaded main menu layout successfully. StartButton: Active, SettingsButton: Active",
            f"{now}  1200  1265 I Unity   : [PlayerTelemetry] Action received: Tapped start button (0.5, 0.72)",
            f"{now}  1200  1270 I Unity   : LoadScene: Loading level 'Scene_Level1_Gameplay'...",
            f"{now}  1200  1275 I Unity   : SceneLoad: Scene_Level1_Gameplay loaded in 1.18 seconds",
            f"{now}  1200  1280 I Unity   : [UI] Initializing level 1 board. Total matching tiles: 64",
            f"{now}  1200  1285 I Unity   : [Gameplay] Player made tile match! Coordinates: (3, 4) with (3, 5). Score +150",
            f"{now}  1200  1290 I Unity   : [Gameplay] Spawned replacement tiles. Current board state: STABLE",
            f"{now}  1200  1295 I Unity   : [Gameplay] Player tapped coordinate (0.3, 0.44). Action valid.",
            f"{now}  1200  1300 W Unity   : [AdSDK] Failed to load interstitial ad: Ad request timed out.",
            f"{now}  1200  1305 I Unity   : [Gameplay] Match detected at (1, 2). Cascade chain reaction. Score +450",
            f"{now}  1200  1310 I Unity   : [PlayerTelemetry] Goal criteria evaluated: Match puzzle level complete!",
            f"{now}  1200  1315 I Unity   : [PlayerFleetTelemetry] Pushing final game stats payload. Bytes: 1048",
            f"{now}  1200  1320 I ActivityManager: Killing 1200:com.unity.simulated_player/u0a112 (adj 900): force stop",
        ]
        return "\n".join(log_lines)

    def generate_mock_screenshot(self, device_id: str, output_path: str) -> bool:
        """Generates a premium visual screenshot for the simulated game using Pillow."""
        try:
            from PIL import (
                Image as PILImage,
                ImageDraw as PILImageDraw,
                ImageFont as PILImageFont,
            )

            width, height = 1080, 1920
            # Create premium canvas background
            img = PILImage.new("RGB", (width, height), "#1A0B2E")
            draw = PILImageDraw.Draw(img)

            # 1. Horizontal vertical gradient backdrop (#1A0B2E to obsidian #0A0413)
            for y in range(height):
                r = int(0x1A + (0x0A - 0x1A) * y / height)
                g = int(0x0B + (0x04 - 0x0B) * y / height)
                b = int(0x2E + (0x13 - 0x2E) * y / height)
                draw.line([(0, y), (width, y)], fill=(r, g, b))

            # 2. Draw modern background radial circles
            draw.ellipse((-200, 300, 600, 1100), fill=None, outline="#3D1A60", width=4)
            draw.ellipse((600, 800, 1300, 1500), fill=None, outline="#2A1045", width=3)
            draw.ellipse((-300, 1200, 400, 1900), fill=None, outline="#1E0B33", width=5)

            # 3. Dynamic Font Ingestion with deep mac system safety fallbacks
            try:
                font_title = PILImageFont.truetype(
                    "/System/Library/Fonts/Helvetica.ttc", 48
                )
                font_subtitle = PILImageFont.truetype(
                    "/System/Library/Fonts/Helvetica.ttc", 36
                )
                font_body = PILImageFont.truetype(
                    "/System/Library/Fonts/Helvetica.ttc", 28
                )
                font_small = PILImageFont.truetype(
                    "/System/Library/Fonts/Helvetica.ttc", 22
                )
            except Exception:
                try:
                    font_title = PILImageFont.truetype("Arial.ttf", 48)
                    font_subtitle = PILImageFont.truetype("Arial.ttf", 36)
                    font_body = PILImageFont.truetype("Arial.ttf", 28)
                    font_small = PILImageFont.truetype("Arial.ttf", 22)
                except Exception:
                    font_title = PILImageFont.load_default()
                    font_subtitle = font_title
                    font_body = font_title
                    font_small = font_title

            # Collect metrics
            step = self._step_counters.get(device_id, 0)
            score = step * 150 + 250
            last_action = self._last_actions.get(device_id, "System Boot / Game Launch")

            # 4. Header Glossy Glassmorphic Dashboard
            draw.rounded_rectangle(
                (80, 80, 1000, 300),
                radius=24,
                fill="#2E164ACC",
                outline="#5B2E8C",
                width=3,
            )
            draw.text(
                (120, 110),
                "🏆 JEPA METADATA INGESTION BOARD",
                fill="#E2D4F0",
                font=font_subtitle,
            )
            draw.text((120, 170), f"SCORE: {score}", fill="#FFD700", font=font_title)
            draw.text((700, 170), f"STEP: {step}/15", fill="#00FFCC", font=font_title)
            draw.text(
                (120, 240),
                "Status: Telemetry Connected (Local SDK Mode)",
                fill="#8BC34A",
                font=font_small,
            )

            # 5. Play Board Panel Grid (6x6)
            board_left, board_top = 130, 420
            cell_size, spacing = 110, 30

            draw.rounded_rectangle(
                (100, 390, 980, 1260),
                radius=20,
                fill="#130822CC",
                outline="#421C6F",
                width=2,
            )

            for row in range(6):
                for col in range(6):
                    c_left = board_left + col * (cell_size + spacing)
                    c_top = board_top + row * (cell_size + spacing)
                    c_right = c_left + cell_size
                    c_bottom = c_top + cell_size

                    draw.rounded_rectangle(
                        (c_left, c_top, c_right, c_bottom),
                        radius=10,
                        fill="#23123A",
                        outline="#3C1F5C",
                    )

                    piece_type = (row * 3 + col * 7) % 4
                    cx = c_left + cell_size // 2
                    cy = c_top + cell_size // 2
                    r = 30

                    if piece_type == 0:
                        draw.ellipse(
                            (cx - r, cy - r, cx + r, cy + r),
                            fill="#FF2E93",
                            outline="#FFA0C5",
                            width=2,
                        )
                    elif piece_type == 1:
                        draw.rounded_rectangle(
                            (cx - r, cy - r, cx + r, cy + r),
                            radius=8,
                            fill="#00E676",
                            outline="#B9F6CA",
                            width=2,
                        )
                    elif piece_type == 2:
                        draw.polygon(
                            [(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)],
                            fill="#FFEA00",
                            outline="#FFFF8D",
                            width=2,
                        )
                    elif piece_type == 3:
                        draw.polygon(
                            [
                                (cx, cy - r),
                                (cx + r - 10, cy + r),
                                (cx - r + 10, cy + r),
                            ],
                            fill="#00E5FF",
                            outline="#80DEEA",
                            width=2,
                        )

            # 6. Interactive Active Game Screen Banner
            draw.rounded_rectangle(
                (200, 1320, 880, 1450),
                radius=35,
                fill="#4A154B",
                outline="#FF2E93",
                width=3,
            )
            draw.text(
                (370, 1360),
                "🎮 MOCK PLAYER FLEET ACTIVE",
                fill="#FFFFFF",
                font=font_subtitle,
            )

            # 7. Ingestion Debug Console
            draw.rounded_rectangle(
                (80, 1520, 1000, 1840),
                radius=16,
                fill="#050209",
                outline="#00E5FF",
                width=2,
            )
            draw.text(
                (120, 1550),
                "SYSTEM LOG MONITOR (ADB SIMULATION)",
                fill="#00E5FF",
                font=font_small,
            )
            draw.text(
                (120, 1610),
                f"Device ID:     {device_id}",
                fill="#B2EBF2",
                font=font_body,
            )
            draw.text(
                (120, 1670),
                f"Action Queue:  {last_action}",
                fill="#B2EBF2",
                font=font_body,
            )

            dot_color = "#FF2E93" if step % 2 == 0 else "#00FFCC"
            draw.ellipse((930, 1550, 950, 1570), fill=dot_color)

            # 8. Interactive Telemetry Click Coordinates Rendering
            last_tap = self._last_taps.get(device_id)
            last_swipe = self._last_swipes.get(device_id)

            if last_tap:
                tx, ty = last_tap
                abs_x, abs_y = int(tx * width), int(ty * height)

                # concentric glowing rings
                draw.ellipse(
                    (abs_x - 70, abs_y - 70, abs_x + 70, abs_y + 70),
                    fill=None,
                    outline="#FF5722",
                    width=2,
                )
                draw.ellipse(
                    (abs_x - 40, abs_y - 40, abs_x + 40, abs_y + 40),
                    fill=None,
                    outline="#FF9800",
                    width=4,
                )
                draw.ellipse(
                    (abs_x - 15, abs_y - 15, abs_x + 15, abs_y + 15), fill="#FFEB3B"
                )

                # dynamic coordinate overlay box
                draw.rounded_rectangle(
                    (abs_x + 30, abs_y - 75, abs_x + 250, abs_y - 25),
                    radius=6,
                    fill="#E65100",
                    outline="#FFFFFF",
                )
                draw.text(
                    (abs_x + 50, abs_y - 65),
                    f"TAP ({tx:.2f}, {ty:.2f})",
                    fill="#FFFFFF",
                    font=font_small,
                )

            if last_swipe:
                x1, y1, x2, y2 = last_swipe
                ax1, ay1 = int(x1 * width), int(y1 * height)
                ax2, ay2 = int(x2 * width), int(y2 * height)

                draw.ellipse(
                    (ax1 - 20, ay1 - 20, ax1 + 20, ay1 + 20),
                    fill="#4CAF50",
                    outline="#FFFFFF",
                    width=2,
                )
                draw.line((ax1, ay1, ax2, ay2), fill="#00E5FF", width=8)
                draw.ellipse(
                    (ax2 - 20, ay2 - 20, ax2 + 20, ay2 + 20),
                    fill="#FF5722",
                    outline="#FFFFFF",
                    width=2,
                )

                draw.rounded_rectangle(
                    (ax2 + 30, ay2 - 30, ax2 + 330, ay2 + 20),
                    radius=6,
                    fill="#006064",
                    outline="#FFFFFF",
                )
                draw.text(
                    (ax2 + 50, ay2 - 20),
                    f"SWIPE TO ({x2:.2f}, {y2:.2f})",
                    fill="#FFFFFF",
                    font=font_small,
                )

            img.save(output_path, "PNG")
            return os.path.exists(output_path) and os.path.getsize(output_path) > 0
        except Exception as e:
            logger.error(f"Error drawing mock screenshot: {e}", exc_info=True)
            return False
