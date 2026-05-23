// DOM Constants
const elDropzone = document.getElementById("dropzone");
const elApkInput = document.getElementById("apk-uploader");
const elFilename = document.getElementById("upload-filename");
const elDeviceSelect = document.getElementById("device-selector");
const elRefreshDevices = document.getElementById("btn-refresh-devices");
const elPackageName = document.getElementById("package-name");
const elMaxSteps = document.getElementById("max-steps");
const elStepsVal = document.getElementById("steps-val");
const elInstructions = document.getElementById("play-instructions");
const elLaunchBtn = document.getElementById("btn-launch-fleet");
const elFleetList = document.getElementById("fleet-list");
const elViewportPlaceholder = document.getElementById("viewport-placeholder");
const elScreenGrab = document.getElementById("screen-grab");
const elCoordinateOverlay = document.getElementById("coordinate-overlay");
const elThoughtsBox = document.getElementById("thoughts-box");
const elCommandBox = document.getElementById("command-box");
const elStepBadge = document.getElementById("step-badge");
const elTelemetryBody = document.getElementById("telemetry-body");
const elLogcatConsole = document.getElementById("logcat-console");
const elClearTelemetry = document.getElementById("btn-clear-telemetry");

let selectedApkName = "";
let activeEventSource = null;
let devicesCache = [];

// Tab Panels Switching
document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
        document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
        btn.classList.add("active");
        document.getElementById(btn.dataset.tab).classList.add("active");
    });
});

// Max Steps Slider label listener
elMaxSteps.addEventListener("input", (e) => {
    elStepsVal.innerText = `${e.target.value} steps`;
});

// Check Server Status & Fetch Connected Devices on Startup
async function checkStatusAndDevices() {
    try {
        const res = await fetch("/api/emulators");
        const statusIndicator = document.getElementById("server-status");
        if (res.ok) {
            statusIndicator.className = "status-indicator online";
            statusIndicator.querySelector(".indicator-text").innerText = "Backend Connected";
            
            const data = await res.json();
            populateDevices(data.devices);
        } else {
            statusIndicator.className = "status-indicator offline";
            statusIndicator.querySelector(".indicator-text").innerText = "Backend Error";
        }
    } catch (e) {
        console.error("Failed to connect to backend server: ", e);
        const statusIndicator = document.getElementById("server-status");
        statusIndicator.className = "status-indicator offline";
        statusIndicator.querySelector(".indicator-text").innerText = "Backend Disconnected";
    }
}

function populateDevices(devices) {
    devicesCache = devices || [];
    elDeviceSelect.innerHTML = "";
    if (!devices || devices.length === 0) {
        const opt = document.createElement("option");
        opt.value = "";
        opt.innerText = "-- No Devices Detected --";
        elDeviceSelect.appendChild(opt);
        elLaunchBtn.disabled = true;
        elLaunchBtn.classList.remove("pulse");
        updateFleetListUI([]);
        return;
    }

    devices.forEach(d => {
        const opt = document.createElement("option");
        opt.value = d.id;
        const icon = d.type === "physical" ? "📱" : "🤖";
        opt.innerText = `${icon} ${d.name} (${d.resolution})`;
        elDeviceSelect.appendChild(opt);
    });

    if (selectedApkName) {
        elLaunchBtn.disabled = false;
        elLaunchBtn.classList.add("pulse");
    }
    
    updateFleetListUI(devices);
}

function updateFleetListUI(devices, activeRunId = null, runStatus = "idle") {
    elFleetList.innerHTML = "";
    if (devices.length === 0) {
        elFleetList.innerHTML = `
            <div class="empty-state">
                <p>No active devices connected. Open Android Studio AVD Manager or plug in a device.</p>
            </div>
        `;
        return;
    }

    devices.forEach(d => {
        const statusText = activeRunId ? runStatus : "idle";
        const badgeClass = activeRunId ? runStatus.toLowerCase() : "idle";
        
        const isEmulator = d.type === "emulator" || (d.name && d.name.toLowerCase().includes("virtual")) || d.id.includes("mock");
        const deviceIcon = isEmulator ? "🤖" : "📱";
        const typeLabel = isEmulator ? "Virtual Device" : "Physical Device";
        
        const card = document.createElement("div");
        card.className = "device-item-card";
        card.innerHTML = `
            <div class="device-info">
                <h4>${deviceIcon} ${d.name || "Android Device"}</h4>
                <p>Serial: ${d.id} | Size: ${d.resolution || "Unknown"} | Type: ${typeLabel}</p>
            </div>
            <span class="device-badge ${badgeClass}">${statusText}</span>
        `;
        elFleetList.appendChild(card);
    });
}

elRefreshDevices.addEventListener("click", checkStatusAndDevices);

// Drag & Drop APK File Uploader
elDropzone.addEventListener("click", () => elApkInput.click());

elDropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    elDropzone.classList.add("dragover");
});

elDropzone.addEventListener("dragleave", () => {
    elDropzone.classList.remove("dragover");
});

elDropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    elDropzone.classList.remove("dragover");
    if (e.dataTransfer.files.length > 0) {
        handleApkUpload(e.dataTransfer.files[0]);
    }
});

elApkInput.addEventListener("change", (e) => {
    if (e.target.files.length > 0) {
        handleApkUpload(e.target.files[0]);
    }
});

async function handleApkUpload(file) {
    if (!file.name.endsWith(".apk")) {
        alert("Please upload a valid Android build .apk file.");
        return;
    }

    elFilename.innerText = `Uploading ${file.name}...`;
    elFilename.style.color = "var(--warning)";

    const formData = new FormData();
    formData.append("apk", file);

    try {
        const res = await fetch("/api/upload", {
            method: "POST",
            body: formData
        });
        
        if (res.ok) {
            const data = await res.json();
            selectedApkName = data.apk_name;
            elFilename.innerText = `Uploaded: ${data.apk_name}`;
            elFilename.style.color = "var(--success)";
            
            // Auto-populate package name (bundle) from uploaded APK
            if (data.package_name) {
                elPackageName.value = data.package_name;
                console.log("Automatically updated package name from APK:", data.package_name);
            }
            
            // Enable primary launch button if emulator is selected
            if (elDeviceSelect.value) {
                elLaunchBtn.disabled = false;
                elLaunchBtn.classList.add("pulse");
            }
        } else {
            const err = await res.json();
            elFilename.innerText = `Upload Failed: ${err.detail || "Error"}`;
            elFilename.style.color = "var(--danger)";
        }
    } catch (e) {
        console.error("APK upload error:", e);
        elFilename.innerText = "Connection Failed during upload.";
        elFilename.style.color = "var(--danger)";
    }
}

// Visual Taps Coordinate Render Overlay
function renderTapOnOverlay(relX, relY) {
    elCoordinateOverlay.innerHTML = ""; // Clear old tap dots
    
    const tapDot = document.createElement("div");
    tapDot.className = "tap-indicator";
    tapDot.style.left = `${relX * 100}%`;
    tapDot.style.top = `${relY * 100}%`;
    
    elCoordinateOverlay.appendChild(tapDot);
}

// Start Autonomous Play Fleet
elLaunchBtn.addEventListener("click", async () => {
    const deviceId = elDeviceSelect.value;
    const packageName = elPackageName.value.trim() || "com.unity.examplegame";
    const instructions = elInstructions.value.trim() || "Play game as a player.";
    const maxSteps = parseInt(elMaxSteps.value);

    if (!deviceId || !selectedApkName) return;

    // Reset replay view
    elViewportPlaceholder.classList.add("hidden");
    elScreenGrab.classList.add("hidden");
    elCoordinateOverlay.innerHTML = "";
    elThoughtsBox.innerHTML = "<span class='dimmed'>Play agent starting... Warmup prompt fired.</span>";
    elCommandBox.innerHTML = "<code>Connecting to device logcat telemetry...</code>";
    elStepBadge.innerText = "starting";
    elStepBadge.className = "badge playing";
    
    elLaunchBtn.disabled = true;
    elLaunchBtn.querySelector(".btn-text").innerText = "Executing gameplay...";
    
    try {
        const res = await fetch("/api/play", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                device_id: deviceId,
                apk_name: selectedApkName,
                package_name: packageName,
                instructions: instructions,
                max_steps: maxSteps
            })
        });

        if (res.ok) {
            const data = await res.json();
            const runId = data.run_id;
            
            // Connect Server-Sent Events (SSE) log stream
            if (activeEventSource) activeEventSource.close();
            
            activeEventSource = new EventSource(`/api/events?run_id=${runId}`);
            
            activeEventSource.onmessage = (event) => {
                const packet = JSON.parse(event.data);
                handlePlayUpdate(packet, deviceId);
            };

            activeEventSource.onerror = (e) => {
                console.error("SSE Stream connection error, closing.", e);
                activeEventSource.close();
                resetLaunchButtonState();
            };
        } else {
            const err = await res.json();
            elThoughtsBox.innerHTML = `<span class='dimmed' style='color: var(--danger)'>Failed to start run: ${err.detail || "Server error"}</span>`;
            resetLaunchButtonState();
        }
    } catch (e) {
        console.error("Launch session error:", e);
        elThoughtsBox.innerHTML = "<span class='dimmed' style='color: var(--danger)'>Connection failed starting run.</span>";
        resetLaunchButtonState();
    }
});

function resetLaunchButtonState() {
    elLaunchBtn.disabled = false;
    elLaunchBtn.querySelector(".btn-text").innerText = "Launch Simulated Player";
}

// Process Real-time Gameplay telemetry packet from SSE
function handlePlayUpdate(packet, deviceId) {
    const status = packet.status;
    
    // Update Badge
    elStepBadge.innerText = status;
    elStepBadge.className = `badge ${status}`;
    
    // Query cached device properties to avoid hardcoding labels
    const device = devicesCache.find(d => d.id === deviceId) || {
        id: deviceId,
        name: deviceId.includes("mock") ? "Simulated Pixel 6 Pro" : `Android Device (${deviceId})`,
        resolution: "Active Session",
        type: deviceId.includes("mock") || deviceId.includes("emulator") ? "emulator" : "physical"
    };
    
    // Update Active fleet UI lists
    updateFleetListUI([device], packet.run_id, status);

    if (packet.message) {
        elThoughtsBox.innerHTML = `<span>${packet.message}</span>`;
    }

    // Step gameplay loop packets
    if (status === "playing" && packet.screenshot) {
        elScreenGrab.src = `data:image/png;base64,${packet.screenshot}`;
        elScreenGrab.classList.remove("hidden");
        elViewportPlaceholder.classList.add("hidden");
        
        elStepBadge.innerText = `Step ${packet.step}/${packet.max_steps}`;

        if (packet.reasoning) {
            elThoughtsBox.innerHTML = `<span><strong>Step ${packet.step}:</strong> ${packet.reasoning}</span>`;
        }

        if (packet.action) {
            elCommandBox.innerHTML = `<code>${packet.action}</code>`;
        } else {
            elCommandBox.innerHTML = "<code>Observing visual state...</code>";
        }
        
        // Scan for taps/swipes coordinates inside recorded actions to render visually
        elCoordinateOverlay.innerHTML = ""; // reset overlay
        if (packet.action && packet.action.includes("Tapped position")) {
            // Parse coordinate e.g. Tapped position (0.5, 0.72)
            const matches = packet.action.match(/\(([^)]+)\)/);
            if (matches && matches[1]) {
                const coords = matches[1].split(",");
                const relX = parseFloat(coords[0].strip ? coords[0].strip() : coords[0]);
                const relY = parseFloat(coords[1].strip ? coords[1].strip() : coords[1]);
                renderTapOnOverlay(relX, relY);
            }
        }
        
        // Reload telemetry database log table
        loadTelemetryEvents();
    }

    if (status === "completed") {
        elThoughtsBox.innerHTML = `<span style="color: var(--success); font-weight: 600;">✅ Play session completed successfully! APK stopped. Logcat compiled.</span>`;
        elCommandBox.innerHTML = "<code>adb shell am force-stop</code>";
        
        if (packet.logs) {
            elLogcatConsole.innerText = packet.logs;
        } else {
            elLogcatConsole.innerText = "No logcat buffer captured.";
        }
        
        activeEventSource.close();
        resetLaunchButtonState();
        loadTelemetryEvents();
    }

    if (status === "failed") {
        elThoughtsBox.innerHTML = `<span style="color: var(--danger); font-weight: 600;">❌ Session failed: ${packet.message}</span>`;
        activeEventSource.close();
        resetLaunchButtonState();
        loadTelemetryEvents();
    }
}

// Fetch Telemetry history from backend database
async function loadTelemetryEvents() {
    try {
        const res = await fetch("/api/telemetry");
        if (res.ok) {
            const data = await res.json();
            renderTelemetryTable(data.events);
        }
    } catch (e) {
        console.error("Failed to load telemetry timeseries logs:", e);
    }
}

function renderTelemetryTable(events) {
    elTelemetryBody.innerHTML = "";
    
    if (!events || events.length === 0) {
        elTelemetryBody.innerHTML = `
            <tr>
                <td colspan="7" class="center-text dimmed">No event timeseries collected yet.</td>
            </tr>
        `;
        return;
    }

    // Render latest first (reverse order)
    events.reverse().forEach(e => {
        const tr = document.createElement("tr");
        
        // Format timestamp
        const time = e.timestamp ? e.timestamp.split("T")[1].substring(0, 8) : "--:--:--";
        
        tr.innerHTML = `
            <td><code>${time}</code></td>
            <td><code>${e.emulator_id}</code></td>
            <td><code>${e.package_name}</code></td>
            <td><span class="badge-tag gcp">${e.step_index === 999 ? "END" : `Step ${e.step_index}`}</span></td>
            <td>${e.action_summary}</td>
            <td><span class="badge-tag ${e.has_screenshot ? 'yes' : 'dimmed'}">${e.has_screenshot ? 'Captured' : 'None'}</span></td>
            <td><span class="badge-tag ${e.has_logs ? 'yes' : 'dimmed'}">${e.has_logs ? 'Dumped' : 'None'}</span></td>
        `;
        elTelemetryBody.appendChild(tr);
    });
}

// Clear local timeseries logs
elClearTelemetry.addEventListener("click", async () => {
    if (confirm("Are you sure you want to delete the local telemetry JSONL event file? This cannot be undone.")) {
        try {
            const res = await fetch("/api/telemetry", { method: "DELETE" });
            if (res.ok) {
                loadTelemetryEvents();
                elLogcatConsole.innerText = "Waiting for game session logcat dump... (Logs will compile and appear here at session end)";
            }
        } catch (e) {
            console.error("Failed to clear telemetry database:", e);
        }
    }
});

// Init on load
checkStatusAndDevices();
loadTelemetryEvents();
