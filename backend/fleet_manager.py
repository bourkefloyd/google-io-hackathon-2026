import subprocess
import os
import re
import logging
import asyncio
import shutil
from typing import List, Dict, Optional, Any

logger = logging.getLogger("fleet_manager")
logging.basicConfig(level=logging.INFO)


class FleetManager:
    def __init__(self):
        # Maps apk_path -> parsed details to optimize install checks
        self._apk_details_cache: Dict[str, Dict[str, str]] = {}
        self._device_last_resolution: Dict[str, Dict[str, int]] = {}
        
        # Simulated Fallback Devices Database
        self.enable_simulated_devices = True
        self.simulated_devices: Dict[str, Dict[str, Any]] = {
            "emulator-5554-mock": {
                "id": "emulator-5554-mock",
                "model": "Simulated Pixel 6 Pro",
                "brand": "Google",
                "type": "emulator",
                "resolution": "1080x1920",
                "name": "Simulated Pixel 6 Pro (mock)",
                "state": "online",  # online, offline, booting
            }
        }

    def get_sdk_tool_path(self, tool_name: str) -> Optional[str]:
        """Auto-detects path of Android SDK command line tools on macOS."""
        # 1. Check if tool is directly in PATH
        path_tool = shutil.which(tool_name)
        if path_tool:
            return path_tool

        # 2. Check standard macOS Android SDK path
        home = os.path.expanduser("~")
        sdk_path = os.path.join(home, "Library/Android/sdk")
        
        if tool_name == "emulator":
            candidate = os.path.join(sdk_path, "emulator/emulator")
            if os.path.exists(candidate):
                return candidate
        elif tool_name in ["avdmanager", "sdkmanager"]:
            # Check cmdline-tools latest first, then tools fallback
            candidates = [
                os.path.join(sdk_path, "cmdline-tools/latest/bin", tool_name),
                os.path.join(sdk_path, "tools/bin", tool_name),
            ]
            for c in candidates:
                if os.path.exists(c):
                    return c
                    
        return None

    def is_sdk_available(self) -> bool:
        """Checks if native Android SDK & AVD tools are installed on the system."""
        return self.get_sdk_tool_path("emulator") is not None

    def list_avds(self) -> List[str]:
        """Lists configured local Android Virtual Devices (AVDs) via emulator CLI."""
        emulator_path = self.get_sdk_tool_path("emulator")
        if not emulator_path:
            return []
        try:
            res = subprocess.run(
                [emulator_path, "-list-avds"],
                capture_output=True,
                text=True,
                timeout=5.0
            )
            if res.returncode == 0:
                return [line.strip() for line in res.stdout.strip().split("\n") if line.strip()]
        except Exception as e:
            logger.error(f"Failed to list native AVDs: {e}")
        return []

    def start_emulator(self, device_id: str) -> bool:
        """Boots a physical emulator (AVD) or transitions a simulated device state."""
        if device_id in self.simulated_devices:
            # Simulated Device Boot sequence (offline -> booting -> online)
            dev = self.simulated_devices[device_id]
            if dev["state"] == "online":
                return True
                
            dev["state"] = "booting"
            logger.info(f"[SIMULATOR] Booting mock device: {device_id}...")
            
            # Fire-and-forget background task to transition state to online in 4 seconds
            async def transition_state():
                await asyncio.sleep(4.0)
                if dev["state"] == "booting":
                    dev["state"] = "online"
                    logger.info(f"[SIMULATOR] Mock device is now Online: {device_id}")

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(transition_state())
            except Exception:
                # Fallback if no active event loop
                dev["state"] = "online"
            return True

        # Real AVD Boot sequence
        emulator_path = self.get_sdk_tool_path("emulator")
        if not emulator_path:
            logger.error("Cannot boot native AVD: emulator CLI tool not found.")
            return False
            
        logger.info(f"Launching native Android Virtual Device: '{device_id}' in background...")
        try:
            # Start emulator in detached background process redirecting output to /dev/null
            subprocess.Popen(
                [emulator_path, "-avd", device_id, "-no-snapshot-load"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            return True
        except Exception as e:
            logger.error(f"Error launching native emulator {device_id}: {e}")
            return False

    def stop_emulator(self, device_id: str) -> bool:
        """Powers off a running emulator (AVD) or transitions a simulated device state."""
        if device_id in self.simulated_devices:
            self.simulated_devices[device_id]["state"] = "offline"
            logger.info(f"[SIMULATOR] Powered off mock device: {device_id}")
            return True

        # For running real AVD emulators, shut down cleanly via adb emu kill
        logger.info(f"Shutting down native emulator device {device_id}...")
        res = self.run_cmd(["adb", "-s", device_id, "emu", "kill"])
        if res.returncode == 0:
            return True
            
        # Fallback to kill-server command or PID termination if emu kill fails
        res_kill = self.run_cmd(["adb", "-s", device_id, "shell", "reboot", "-p"])
        return res_kill.returncode == 0

    def create_emulator(self, name: str, model: str, brand: str, resolution: str, is_simulated: bool) -> Optional[str]:
        """Creates a new real AVD configuration (if SDK is available) or a dynamic simulated device."""
        if is_simulated or not self.is_sdk_available():
            # Provision a dynamic simulated mock device
            existing_nums = []
            for d in self.simulated_devices:
                match = re.search(r"emulator-(\d+)-mock", d)
                if match:
                    existing_nums.append(int(match.group(1)))
            next_num = max(existing_nums) + 1 if existing_nums else 5554
            new_id = f"emulator-{next_num}-mock"
            
            clean_name = name.strip() if name.strip() else f"Simulated {model}"
            self.simulated_devices[new_id] = {
                "id": new_id,
                "model": model,
                "brand": brand,
                "type": "emulator",
                "resolution": resolution,
                "name": f"{clean_name} (mock)",
                "state": "offline"
            }
            logger.info(f"Provisioned new simulated fallback device in database: {new_id}")
            return new_id

        # Provision a real AVD
        avdmanager_path = self.get_sdk_tool_path("avdmanager")
        if not avdmanager_path:
            logger.error("avdmanager SDK tool not found in paths. Cannot provision native AVD.")
            return None
            
        logger.info(f"Provisioning native AVD '{name}' using avdmanager...")
        # Note: AVD creation usually requires a system image. We leverage a default profile.
        cmd = [
            avdmanager_path, "create", "avd",
            "-n", name,
            "-k", "system-images;android-31;google_apis;arm64-v8a",
            "--force"
        ]
        res = self.run_cmd(cmd)
        if res.returncode == 0:
            logger.info(f"Successfully provisioned native AVD '{name}'!")
            return name
        logger.error(f"Failed to create native AVD: {res.stderr}")
        return None

    def get_device_details(self, device_id: str) -> Dict[str, str]:
        """Gets device model, brand, type (emulator/physical), and resolution."""
        # Check simulated database
        if device_id in self.simulated_devices:
            dev = self.simulated_devices[device_id]
            return {
                "id": device_id,
                "model": dev["model"],
                "brand": dev["brand"],
                "type": "emulator",
                "resolution": dev["resolution"],
                "name": dev["name"],
                "state": dev["state"],
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
            # Query AVD name from telnet console if possible to match booted emulators to their created names
            avd_name = ""
            res_avd = self.run_cmd(["adb", "-s", device_id, "emu", "avd", "name"])
            if res_avd.returncode == 0 and res_avd.stdout.strip():
                lines = [line.strip() for line in res_avd.stdout.strip().splitlines() if line.strip() and line.strip().lower() != "ok"]
                if lines:
                    avd_name = lines[0]
            
            if avd_name:
                name = f"AVD: {avd_name} ({model})"
            else:
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
            "state": "online"  # Real connected devices are online by definition
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
        """Runs 'adb devices' and parses connected emulator and physical device serials."""
        devices = []
        if self.is_adb_available():
            res = self.run_cmd(["adb", "devices"])
            if res.returncode == 0:
                for line in res.stdout.strip().split("\n")[1:]:
                    if not line.strip():
                        continue
                    parts = line.split()
                    if len(parts) >= 2 and parts[1] == "device":
                        devices.append(parts[0])
            else:
                logger.error(f"Failed to list devices via adb: {res.stderr}")

        # Integrate online simulated fallback devices
        if self.enable_simulated_devices:
            for d, metadata in self.simulated_devices.items():
                if metadata["state"] == "online" and d not in devices:
                    devices.append(d)

        return devices

    def get_device_resolution(self, device_id: str) -> Dict[str, int]:
        """Gets screen size in pixels using adb shell wm size."""
        if device_id in self.simulated_devices:
            res_str = self.simulated_devices[device_id]["resolution"]
            w, h = res_str.split("x")
            return {"width": int(w), "height": int(h)}

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
        if device_id in self.simulated_devices:
            # Simulated device skip check details
            return {"version_name": "1.0", "version_code": "1"}

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
        if device_id in self.simulated_devices:
            logger.info(f"[SIMULATOR] Simulating installation of APK {apk_path} on {device_id}...")
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
        if device_id in self.simulated_devices:
            logger.info(f"[SIMULATOR] Launched package '{package_name}' on {device_id}.")
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
        if device_id in self.simulated_devices:
            return
        logger.info(f"Ensuring device {device_id} stays awake, waking up screen, and dismissing keyguard.")
        self.run_cmd(["adb", "-s", device_id, "shell", "svc", "power", "stayon", "true"])
        self.run_cmd(["adb", "-s", device_id, "shell", "input", "keyevent", "224"])
        self.run_cmd(["adb", "-s", device_id, "shell", "wm", "dismiss-keyguard"])

    def force_stop_app(self, device_id: str, package_name: str) -> None:
        """Kills the app."""
        if device_id in self.simulated_devices:
            logger.info(f"[SIMULATOR] Force-stopped package '{package_name}' on {device_id}.")
            return
        self.run_cmd(
            ["adb", "-s", device_id, "shell", "am", "force-stop", package_name]
        )

    def clear_logcat(self, device_id: str) -> None:
        """Clears logcat buffer."""
        if device_id in self.simulated_devices:
            return
        logger.info(f"Clearing logcat buffer on {device_id}...")
        self.run_cmd(["adb", "-s", device_id, "logcat", "-c"])

    def dump_logcat(self, device_id: str) -> str:
        """Dumps current logcat buffer in memory."""
        if device_id in self.simulated_devices:
            # Dynamic high fidelity logs compilation for mock device running user APK details
            from datetime import datetime
            now = datetime.now().strftime("%m-%d %H:%M:%S.%f")[:-3]
            pkg = "com.android.testing"
            log_lines = [
                f"{now}  1200  1230 I ActivityManager: Start proc {device_id} for package {pkg}",
                f"{now}  1200  1245 D dalvikvm: Late-enabling CheckJNI",
                f"{now}  1200  1250 I Unity   : [PlayerFleetTelemetry] Initializing telemetry ingestion loop...",
                f"{now}  1200  1250 I Unity   : ScreenManager: Window size {self.get_device_resolution(device_id)['width']}x{self.get_device_resolution(device_id)['height']}",
                f"{now}  1200  1255 I Unity   : Loading gameplay assets in background...",
                f"{now}  1200  1260 I Unity   : [Gameplay] Player is making real visual progress targeting user instructions.",
                f"{now}  1200  1320 I ActivityManager: Killing com.android.testing (adj 900): force stop",
            ]
            return "\n".join(log_lines)

        logger.info(f"Dumping logcat from {device_id}...")
        res = self.run_cmd(["adb", "-s", device_id, "logcat", "-d"])
        return res.stdout

    def take_screenshot(self, device_id: str, output_path: str, max_steps: int = 50) -> bool:
        """Saves device screenshot directly to output_path using piping."""
        if device_id in self.simulated_devices:
            # Generate a gorgeous high-fidelity dynamic mock game screenshot mapping selected AVD resolution
            try:
                from PIL import Image as PILImage, ImageDraw as PILImageDraw
                res = self.get_device_resolution(device_id)
                w, h = res["width"], res["height"]
                img = PILImage.new("RGB", (w, h), "#0F0B1E")
                draw = PILImageDraw.Draw(img)
                # Drawing concentric grid dots
                for x in range(0, w, 80):
                    for y in range(0, h, 80):
                        draw.ellipse((x-2, y-2, x+2, y+2), fill="#29204A")
                draw.rounded_rectangle((60, 60, w-60, 180), radius=16, fill="#2C1D4D", outline="#00FFCC", width=2)
                draw.ellipse((w//2-50, h//2-50, w//2+50, h//2+50), fill="#FF007F")
                img.save(output_path, "PNG")
                self._device_last_resolution[device_id] = {"width": w, "height": h}
                return True
            except Exception as e:
                logger.error(f"Error drawing simulated screenshot: {e}")
                return False

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
                    # Cache the actual dynamic screenshot size before thumbnailing to support rotated landscape screens
                    self._device_last_resolution[device_id] = {"width": img.width, "height": img.height}
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
        res = self._device_last_resolution.get(device_id)
        if not res:
            res = self.get_device_resolution(device_id)
        abs_x = int(rel_x * res["width"])
        abs_y = int(rel_y * res["height"])

        if device_id in self.simulated_devices:
            logger.info(f"[SIMULATOR] execute_tap relative=({rel_x}, {rel_y}) absolute=({abs_x}, {abs_y})")
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
        res = self._device_last_resolution.get(device_id)
        if not res:
            res = self.get_device_resolution(device_id)
        abs_x1 = int(rel_x1 * res["width"])
        abs_y1 = int(rel_y1 * res["height"])
        abs_x2 = int(rel_x2 * res["width"])
        abs_y2 = int(rel_y2 * res["height"])

        if device_id in self.simulated_devices:
            logger.info(f"[SIMULATOR] execute_swipe from=({rel_x1}, {rel_y1}) to=({rel_x2}, {rel_y2})")
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
        if device_id in self.simulated_devices:
            logger.info(f"[SIMULATOR] execute_text text='{text}'")
            return f"adb shell input text '{text}'"

        # Sanitize spaces for adb shell input text
        sanitized = text.replace(" ", "%s")
        cmd = ["adb", "-s", device_id, "shell", "input", "text", sanitized]
        self.run_cmd(cmd)
        return f"adb shell input text '{text}'"

    def execute_keyevent(self, device_id: str, key_code: int) -> str:
        """Sends key event (e.g. back button = 4, home button = 3)."""
        if device_id in self.simulated_devices:
            logger.info(f"[SIMULATOR] execute_keyevent key={key_code}")
            return f"adb shell input keyevent {key_code}"

        cmd = ["adb", "-s", device_id, "shell", "input", "keyevent", str(key_code)]
        self.run_cmd(cmd)
        return f"adb shell input keyevent {key_code}"
