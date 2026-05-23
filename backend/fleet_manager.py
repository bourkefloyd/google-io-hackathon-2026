import subprocess
import os
import re
import logging
from typing import List, Dict, Optional

logger = logging.getLogger("fleet_manager")
logging.basicConfig(level=logging.INFO)


class FleetManager:
    def __init__(self):
        # Maps apk_path -> parsed details to optimize install checks
        self._apk_details_cache: Dict[str, Dict[str, str]] = {}

    def get_device_details(self, device_id: str) -> Dict[str, str]:
        """Gets device model, brand, type (emulator/physical), and resolution."""
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
        """Runs 'adb devices' and parses connected emulator and physical device serials."""
        if not self.is_adb_available():
            logger.warning(
                "Android Platform Tools (adb) not found in system PATH. Returning empty active fleet."
            )
            return []

        res = self.run_cmd(["adb", "devices"])
        devices = []
        if res.returncode == 0:
            for line in res.stdout.strip().split("\n")[1:]:
                if not line.strip():
                    continue
                parts = line.split()
                if len(parts) >= 2 and parts[1] == "device":
                    devices.append(parts[0])
        else:
            logger.error(f"Failed to list devices via adb: {res.stderr}")

        return devices

    def get_device_resolution(self, device_id: str) -> Dict[str, int]:
        """Gets screen size in pixels using adb shell wm size."""
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
        logger.info(f"Ensuring device {device_id} stays awake, waking up screen, and dismissing keyguard.")
        self.run_cmd(["adb", "-s", device_id, "shell", "svc", "power", "stayon", "true"])
        self.run_cmd(["adb", "-s", device_id, "shell", "input", "keyevent", "224"])
        self.run_cmd(["adb", "-s", device_id, "shell", "wm", "dismiss-keyguard"])

    def force_stop_app(self, device_id: str, package_name: str) -> None:
        """Kills the app."""
        self.run_cmd(
            ["adb", "-s", device_id, "shell", "am", "force-stop", package_name]
        )

    def clear_logcat(self, device_id: str) -> None:
        """Clears logcat buffer."""
        logger.info(f"Clearing logcat buffer on {device_id}...")
        self.run_cmd(["adb", "-s", device_id, "logcat", "-c"])

    def dump_logcat(self, device_id: str) -> str:
        """Dumps current logcat buffer in memory."""
        logger.info(f"Dumping logcat from {device_id}...")
        res = self.run_cmd(["adb", "-s", device_id, "logcat", "-d"])
        return res.stdout

    def take_screenshot(self, device_id: str, output_path: str, max_steps: int = 50) -> bool:
        """Saves device screenshot directly to output_path using piping."""
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
        # Sanitize spaces for adb shell input text
        sanitized = text.replace(" ", "%s")
        cmd = ["adb", "-s", device_id, "shell", "input", "text", sanitized]
        self.run_cmd(cmd)
        return f"adb shell input text '{text}'"

    def execute_keyevent(self, device_id: str, key_code: int) -> str:
        """Sends key event (e.g. back button = 4, home button = 3)."""
        cmd = ["adb", "-s", device_id, "shell", "input", "keyevent", str(key_code)]
        self.run_cmd(cmd)
        return f"adb shell input keyevent {key_code}"
