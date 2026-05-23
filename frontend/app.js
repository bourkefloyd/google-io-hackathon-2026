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
const elStopBtn = document.getElementById("btn-stop-run");
const elFleetList = document.getElementById("fleet-list");
const elViewportPlaceholder = document.getElementById("viewport-placeholder");
const elScreenGrab = document.getElementById("screen-grab");
const elScreenGrabLlm = document.getElementById("screen-grab-llm");
const elDualViewports = document.getElementById("dual-viewports");
const elCoordinateOverlay = document.getElementById("coordinate-overlay");
const elThoughtsBox = document.getElementById("thoughts-box");
const elCommandBox = document.getElementById("command-box");
const elStepBadge = document.getElementById("step-badge");
const elStateBadge = document.getElementById("state-badge");
const elTelemetryBody = document.getElementById("telemetry-body");
const elLogcatConsole = document.getElementById("logcat-console");
const elClearTelemetry = document.getElementById("btn-clear-telemetry");
const elRunSelect = document.getElementById("run-selector");
const elTimelineScrubber = document.getElementById("timeline-scrubber");
const elTimelineStepLabel = document.getElementById("timeline-step-label");
const elTimelineStatusDesc = document.getElementById("timeline-status-desc");
const elBtnPrevStep = document.getElementById("btn-prev-step");
const elBtnNextStep = document.getElementById("btn-next-step");

let selectedApkName = "";
let activeEventSource = null;
let devicesCache = [];
let activeRunId = null;
let isHistoricalMode = false;
let activeRunEvents = [];
let historicRunEvents = [];
let selectedStepIndex = -1;

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

// Timeline range scrubber drag listener
elTimelineScrubber.addEventListener("input", (e) => {
    const val = parseInt(e.target.value);
    selectTimelineStep(val - 1);
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

function updateFleetListUI(devices, activeRun = null, runStatus = "idle") {
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
        const statusText = activeRun ? runStatus : "idle";
        const badgeClass = activeRun ? runStatus.toLowerCase() : "idle";
        
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

    // Reset session selector to active
    elRunSelect.value = "active";
    isHistoricalMode = false;
    toggleFormInputs(false);

    // Reset replay view and events
    activeRunEvents = [];
    elViewportPlaceholder.classList.add("hidden");
    if (elDualViewports) elDualViewports.classList.add("hidden");
    elScreenGrab.classList.add("hidden");
    if (elScreenGrabLlm) elScreenGrabLlm.classList.add("hidden");
    elCoordinateOverlay.innerHTML = "";
    elThoughtsBox.innerHTML = "<span class='dimmed'>Play agent starting... Warmup prompt fired.</span>";
    elCommandBox.innerHTML = "<code>Connecting to device logcat telemetry...</code>";
    elStepBadge.innerText = "starting";
    elStepBadge.className = "badge playing";
    
    elStateBadge.innerText = "booting";
    elStateBadge.className = "badge-tag state-tag thinking";
    
    elLaunchBtn.disabled = true;
    elLaunchBtn.querySelector(".btn-text").innerText = "Executing gameplay...";
    
    elStopBtn.disabled = false;
    elStopBtn.classList.remove("hidden");

    if (elTimelineScrubber) {
        elTimelineScrubber.min = 1;
        elTimelineScrubber.max = 1;
        elTimelineScrubber.value = 1;
        elTimelineScrubber.disabled = true;
    }
    if (elTimelineStepLabel) elTimelineStepLabel.innerText = "Starting...";
    if (elTimelineStatusDesc) elTimelineStatusDesc.innerText = "Waiting for step 1 frame...";

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
            activeRunId = data.run_id;
            
            // Connect Server-Sent Events (SSE) log stream
            if (activeEventSource) activeEventSource.close();
            
            activeEventSource = new EventSource(`/api/events?run_id=${activeRunId}`);
            
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

// Stop Running Fleet Play
elStopBtn.addEventListener("click", async () => {
    if (!activeRunId) return;
    elStopBtn.disabled = true;
    elStopBtn.querySelector(".btn-text").innerText = "Stopping...";
    try {
        const res = await fetch(`/api/play/stop?run_id=${activeRunId}`, {
            method: "POST"
        });
        if (res.ok) {
            console.log("Stop signal sent successfully.");
        }
    } catch (e) {
        console.error("Failed to send stop signal:", e);
    }
});

function resetLaunchButtonState() {
    elLaunchBtn.disabled = false;
    elLaunchBtn.querySelector(".btn-text").innerText = "Launch Simulated Player";
    elStopBtn.disabled = true;
    elStopBtn.classList.add("hidden");
    elStopBtn.querySelector(".btn-text").innerText = "Stop Run";
    toggleFormInputs(true);
    listHistoricRuns(); // Refresh historic runs dropdown
}

function toggleFormInputs(enabled) {
    elDeviceSelect.disabled = !enabled;
    elRefreshDevices.disabled = !enabled;
    elPackageName.disabled = !enabled;
    elMaxSteps.disabled = !enabled;
    elInstructions.disabled = !enabled;
    elDropzone.style.pointerEvents = enabled ? "auto" : "none";
}

// Process Real-time Gameplay telemetry packet from SSE
function handlePlayUpdate(packet, deviceId) {
    const status = packet.status;
    
    // Update Badge
    elStepBadge.innerText = status;
    elStepBadge.className = `badge ${status}`;
    
    if (packet.state) {
        elStateBadge.innerText = packet.state;
        elStateBadge.className = `badge-tag state-tag ${packet.state}`;
    }
    
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

    // Capture logs updates dynamically streamed from backend
    if (packet.logs_update) {
        elLogcatConsole.innerText = packet.logs_update;
        return;
    }

    // Step gameplay loop packets
    if (status === "playing" && packet.step) {
        // Find if this step is already recorded, or insert it
        let existingEvent = activeRunEvents.find(e => e.step_index === packet.step);
        if (!existingEvent) {
            existingEvent = {
                step_index: packet.step,
                start_time: packet.start_time || "",
                duration: packet.duration !== undefined ? packet.duration : undefined,
                screenshot: packet.screenshot || "",
                screenshot_path: packet.screenshot_path || "",
                screenshot_llm: packet.screenshot_llm || "",
                screenshot_llm_path: packet.screenshot_llm_path || "",
                agent_reasoning: packet.reasoning || "",
                actions_taken: packet.action && packet.action.includes("Tapped") ? [{type: "tap", params: {x: 0, y: 0}}] : [],
                action_summary: packet.action || "",
                logs: ""
            };
            activeRunEvents.push(existingEvent);
        } else {
            if (packet.start_time) existingEvent.start_time = packet.start_time;
            if (packet.duration !== undefined) existingEvent.duration = packet.duration;
            if (packet.screenshot) existingEvent.screenshot = packet.screenshot;
            if (packet.screenshot_path) existingEvent.screenshot_path = packet.screenshot_path;
            if (packet.screenshot_llm) existingEvent.screenshot_llm = packet.screenshot_llm;
            if (packet.screenshot_llm_path) existingEvent.screenshot_llm_path = packet.screenshot_llm_path;
            if (packet.reasoning) existingEvent.agent_reasoning = packet.reasoning;
            if (packet.action) existingEvent.action_summary = packet.action;
        }

        // Render current visual timeline
        renderTimeline(activeRunEvents, "playing");
        
        // Select the active step node
        const activeNodeIndex = activeRunEvents.length - 1;
        selectTimelineStep(activeNodeIndex);

        // Highlight selected node
        setTimeout(() => {
            const nodes = document.querySelectorAll(".timeline-node");
            if (nodes[activeNodeIndex]) {
                nodes.forEach(n => n.classList.remove("selected"));
                nodes[activeNodeIndex].classList.add("selected");
            }
        }, 100);

        // Reload telemetry database log table
        loadTelemetryEvents();
    }

    if (status === "completed") {
        elThoughtsBox.innerHTML = `<span style="color: var(--success); font-weight: 600;">✅ Play session completed successfully! APK stopped. Logcat compiled.</span>`;
        elCommandBox.innerHTML = "<code>adb shell am force-stop</code>";
        
        if (packet.logs) {
            elLogcatConsole.innerText = packet.logs;
        }
        
        elStateBadge.innerText = "completed";
        elStateBadge.className = "badge-tag state-tag completed";
        
        if (activeEventSource) activeEventSource.close();
        resetLaunchButtonState();
        loadTelemetryEvents();
    }

    if (status === "failed") {
        elThoughtsBox.innerHTML = `<span style="color: var(--danger); font-weight: 600;">❌ Session failed: ${packet.message}</span>`;
        
        elStateBadge.innerText = "stopped";
        elStateBadge.className = "badge-tag state-tag failed";
        
        if (activeEventSource) activeEventSource.close();
        resetLaunchButtonState();
        loadTelemetryEvents();
    }
}

// -------------------------------------------------------------
// Interactive Timeline and Structured Reasoning Parser Logic
// -------------------------------------------------------------

function renderTimeline(events, currentStatus = "completed") {
    if (!events || events.length === 0) {
        if (elTimelineScrubber) {
            elTimelineScrubber.min = 1;
            elTimelineScrubber.max = 1;
            elTimelineScrubber.value = 1;
            elTimelineScrubber.disabled = true;
        }
        if (elTimelineStepLabel) elTimelineStepLabel.innerText = "No steps";
        if (elTimelineStatusDesc) elTimelineStatusDesc.innerText = "System Idle";
        if (elBtnPrevStep && elBtnNextStep) {
            elBtnPrevStep.disabled = true;
            elBtnNextStep.disabled = true;
        }
        selectedStepIndex = -1;
        return;
    }
    
    // Set scrubber min, max, value
    if (elTimelineScrubber) {
        elTimelineScrubber.min = 1;
        elTimelineScrubber.max = events.length;
        elTimelineScrubber.disabled = false;
        
        // Default to the latest step if out of bounds
        if (selectedStepIndex < 0 || selectedStepIndex >= events.length) {
            selectedStepIndex = events.length - 1;
        }
        elTimelineScrubber.value = selectedStepIndex + 1;
    }
    
    const ev = events[selectedStepIndex];
    if (elTimelineStepLabel) {
        elTimelineStepLabel.innerText = `Step ${selectedStepIndex + 1} of ${events.length} (${currentStatus})`;
    }
    if (elTimelineStatusDesc && ev) {
        elTimelineStatusDesc.innerText = ev.action_summary || "No action recorded (observing)";
    }
}

function selectTimelineStep(index) {
    const events = isHistoricalMode ? historicRunEvents : activeRunEvents;
    if (!events || index >= events.length || index < 0) return;
    
    selectedStepIndex = index;
    const ev = events[index];
    
    // 1. Update Screenshot Grab (Dynamic base64 or static served path URL)
    let hasScreenshot = false;
    if (ev.screenshot) {
        elScreenGrab.src = `data:image/png;base64,${ev.screenshot}`;
        elScreenGrab.classList.remove("hidden");
        hasScreenshot = true;
    } else if (ev.screenshot_path) {
        // Load fast static image from server
        elScreenGrab.src = ev.screenshot_path;
        elScreenGrab.classList.remove("hidden");
        hasScreenshot = true;
    } else {
        elScreenGrab.src = "";
        elScreenGrab.classList.add("hidden");
    }

    // Update LLM Screenshot Grab (scaled visual input)
    if (ev.screenshot_llm) {
        elScreenGrabLlm.src = `data:image/png;base64,${ev.screenshot_llm}`;
        elScreenGrabLlm.classList.remove("hidden");
    } else if (ev.screenshot_llm_path) {
        elScreenGrabLlm.src = ev.screenshot_llm_path;
        elScreenGrabLlm.classList.remove("hidden");
    } else {
        // Fallback to main screenshot if LLM specific version doesn't exist
        if (hasScreenshot) {
            elScreenGrabLlm.src = elScreenGrab.src;
            elScreenGrabLlm.classList.remove("hidden");
        } else {
            elScreenGrabLlm.src = "";
            elScreenGrabLlm.classList.add("hidden");
        }
    }

    // Dynamically scale the LLM image relative to the full size image (not scaled up)
    if (hasScreenshot && elScreenGrabLlm) {
        const imgFull = new Image();
        imgFull.src = elScreenGrab.src;
        imgFull.onload = () => {
            const fullH = imgFull.naturalHeight || 1200;
            const imgLlm = new Image();
            imgLlm.src = elScreenGrabLlm.src;
            imgLlm.onload = () => {
                const llmH = imgLlm.naturalHeight || 384;
                const ratio = llmH / fullH;
                const calculatedHeight = Math.round(420 * ratio);
                elScreenGrabLlm.style.height = `${calculatedHeight}px`;
            };
        };
    }

    // Toggle viewport visibility layout states
    if (hasScreenshot) {
        elViewportPlaceholder.classList.add("hidden");
        if (elDualViewports) elDualViewports.classList.remove("hidden");
    } else {
        elViewportPlaceholder.classList.remove("hidden");
        if (elDualViewports) elDualViewports.classList.add("hidden");
    }
    
    // 2. Parse and render Structured Reasoning Cards
    renderStructuredReasoning(ev.agent_reasoning);
    
    // 3. Render coordinate tap dot overlay
    elCoordinateOverlay.innerHTML = "";
    if (ev.action_summary && ev.action_summary.includes("Tapped position")) {
        const matches = ev.action_summary.match(/\(([^)]+)\)/);
        if (matches && matches[1]) {
            const coords = matches[1].split(",");
            const relX = parseFloat(coords[0]);
            const relY = parseFloat(coords[1]);
            if (!isNaN(relX) && !isNaN(relY)) {
                renderTapOnOverlay(relX, relY);
            }
        }
    }
    
    // 4. Update action commands box
    elCommandBox.innerHTML = `<code>${ev.action_summary || "No actions performed (observing)"}</code>`;
    
    // 5. Update timeline status scrubber and labels
    if (elTimelineScrubber) {
        elTimelineScrubber.value = index + 1;
    }
    if (elTimelineStepLabel) {
        let labelText = `Step ${index + 1} of ${events.length}`;
        if (ev.duration !== undefined) {
            labelText += ` (${ev.duration}s)`;
        }
        elTimelineStepLabel.innerText = labelText;
    }
    if (elTimelineStatusDesc) {
        elTimelineStatusDesc.innerText = ev.action_summary || "No action recorded (observing)";
    }
    
    // 6. Update step-specific logs
    if (ev.logs) {
        elLogcatConsole.innerText = ev.logs;
    } else {
        elLogcatConsole.innerText = "No step-specific logcat output captured for this step.";
    }
    
    // 7. Update Prev/Next button states
    if (elBtnPrevStep && elBtnNextStep) {
        elBtnPrevStep.disabled = index <= 0;
        elBtnNextStep.disabled = index >= events.length - 1;
    }
}

function renderStructuredReasoning(reasoningText) {
    elThoughtsBox.innerHTML = "";
    if (!reasoningText) {
        elThoughtsBox.innerHTML = `<span class="dimmed">No agent thoughts recorded.</span>`;
        return;
    }
    
    const sections = parseReasoning(reasoningText);
    if (sections.length === 0) {
        elThoughtsBox.innerHTML = `<span>${reasoningText}</span>`;
        return;
    }
    
    sections.forEach(s => {
        const card = document.createElement("div");
        card.className = "reasoning-card";
        
        const header = document.createElement("div");
        header.className = "reasoning-header";
        header.innerHTML = `
            <span class="reasoning-header-title">💡 ${s.title}</span>
            <span class="reasoning-header-icon">▼</span>
        `;
        
        const content = document.createElement("div");
        content.className = "reasoning-content";
        content.innerHTML = s.content.join("<br><br>");
        
        header.addEventListener("click", () => {
            card.classList.toggle("collapsed");
        });
        
        card.appendChild(header);
        card.appendChild(content);
        elThoughtsBox.appendChild(card);
    });
}

function parseReasoning(reasoningText) {
    if (!reasoningText) return [];
    
    const lines = reasoningText.split('\n');
    const sections = [];
    let currentSection = { title: "Overview Analysis", content: [] };
    
    for (let line of lines) {
        line = line.trim();
        if (!line) continue;
        
        // Match bold titles like **Title** or **Title:** or markdown header ### Title
        const boldMatch = line.match(/^\*\*(.*?)\*\*$/) || line.match(/^\*\*(.*?)\*\*:\s*(.*)$/) || line.match(/^(?:###|##|#)\s*(.*)$/);
        
        if (boldMatch) {
            if (currentSection.title || currentSection.content.length > 0) {
                sections.push(currentSection);
            }
            const title = (boldMatch[1] || '').replace(/:$/, '').trim();
            const initialText = boldMatch[2] ? [boldMatch[2].trim()] : [];
            currentSection = { title: title, content: initialText };
        } else {
            currentSection.content.push(line);
        }
    }
    if (currentSection.title || currentSection.content.length > 0) {
        sections.push(currentSection);
    }
    
    return sections.filter(s => s.content.length > 0);
}

// -------------------------------------------------------------
// History Manager & Past Runs Selector API Logic
// -------------------------------------------------------------

async function listHistoricRuns() {
    try {
        const res = await fetch("/api/runs");
        if (res.ok) {
            const data = await res.json();
            populateHistoricRunsSelector(data.runs);
        }
    } catch (e) {
        console.error("Failed to load historic runs list:", e);
    }
}

function populateHistoricRunsSelector(runs) {
    // Keep standard Active option
    elRunSelect.innerHTML = `
        <option value="active">🟢 Active Play Session</option>
    `;
    
    if (!runs || runs.length === 0) return;
    
    runs.forEach(r => {
        const opt = document.createElement("option");
        opt.value = r.run_id;
        
        const date = r.timestamp ? r.timestamp.split("T")[0] : "";
        const time = r.timestamp ? r.timestamp.split("T")[1].substring(0, 5) : "";
        const statusIcon = r.status === "completed" ? "✅" : (r.status === "stopped" ? "🛑" : "❌");
        
        opt.innerText = `${statusIcon} ${r.run_id} | ${r.apk_name || "Game"} | ${date} ${time} (${r.status})`;
        elRunSelect.appendChild(opt);
    });
}

// Session Selector Listener
elRunSelect.addEventListener("change", async (e) => {
    const val = e.target.value;
    if (val === "active") {
        isHistoricalMode = false;
        toggleFormInputs(true);
        clearTimelineDetails();
        
        // Re-render active run if exists
        renderTimeline(activeRunEvents, activeRunId ? "playing" : "completed");
        if (activeRunEvents.length > 0) {
            selectTimelineStep(activeRunEvents.length - 1);
        }
    } else {
        isHistoricalMode = true;
        toggleFormInputs(false);
        await loadHistoricRunDetails(val);
    }
});

async function loadHistoricRunDetails(runId) {
    if (elTimelineStepLabel) elTimelineStepLabel.innerText = "Loading...";
    if (elTimelineStatusDesc) elTimelineStatusDesc.innerText = "Loading historic run details...";
    try {
        const res = await fetch(`/api/runs/${runId}`);
        if (res.ok) {
            const data = await res.json();
            historicRunEvents = data.telemetry || [];
            
            // Render the full static timeline
            renderTimeline(historicRunEvents, data.config.status);
            
            // Load the first step by default
            if (historicRunEvents.length > 0) {
                selectTimelineStep(0);
            } else {
                clearTimelineDetails();
            }
            
            // Set status badges
            elStepBadge.innerText = data.config.status;
            elStepBadge.className = `badge ${data.config.status}`;
            
            elStateBadge.innerText = "historic";
            elStateBadge.className = "badge-tag state-tag idle";
            
            // Load final full logcat
            elLogcatConsole.innerText = data.logs || "No logs were captured for this past run.";
        } else {
            alert("Failed to fetch historic run metadata.");
        }
    } catch (e) {
        console.error("Failed to load historic run details:", e);
        if (elTimelineStatusDesc) elTimelineStatusDesc.innerText = "Error loading past run.";
    }
}

function clearTimelineDetails() {
    elViewportPlaceholder.classList.remove("hidden");
    if (elDualViewports) elDualViewports.classList.add("hidden");
    elScreenGrab.classList.add("hidden");
    elScreenGrab.src = "";
    if (elScreenGrabLlm) {
        elScreenGrabLlm.classList.add("hidden");
        elScreenGrabLlm.src = "";
    }
    elCoordinateOverlay.innerHTML = "";
    elThoughtsBox.innerHTML = "<span class='dimmed'>Replay viewport is idle. Select a step to inspect.</span>";
    elCommandBox.innerHTML = "<code>adb shell idle</code>";
    elStepBadge.innerText = "Idle";
    elStepBadge.className = "badge idle";
    elStateBadge.innerText = "idle";
    elStateBadge.className = "badge-tag state-tag idle";
    elLogcatConsole.innerText = "Waiting for game session logcat dump...";
    
    // Disable prev/next buttons on clear
    if (elBtnPrevStep && elBtnNextStep) {
        elBtnPrevStep.disabled = true;
        elBtnNextStep.disabled = true;
    }
    selectedStepIndex = -1;
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
    events.slice().reverse().forEach(e => {
        const tr = document.createElement("tr");
        
        // Format timestamp
        const time = e.timestamp ? e.timestamp.split("T")[1].substring(0, 8) : "--:--:--";
        
        tr.innerHTML = `
            <td><code>${time}</code></td>
            <td><code>${e.emulator_id}</code></td>
            <td><code>${e.package_name}</code></td>
            <td><span class="badge-tag gcp">${e.step_index === 999 ? "END" : `Step ${e.step_index}${e.duration !== undefined ? ` (${e.duration}s)` : ""}`}</span></td>
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

// Next / Prev Step Navigation Click Listeners
if (elBtnPrevStep) {
    elBtnPrevStep.addEventListener("click", () => {
        if (selectedStepIndex > 0) {
            selectTimelineStep(selectedStepIndex - 1);
        }
    });
}

if (elBtnNextStep) {
    elBtnNextStep.addEventListener("click", () => {
        const events = isHistoricalMode ? historicRunEvents : activeRunEvents;
        if (events && selectedStepIndex < events.length - 1) {
            selectTimelineStep(selectedStepIndex + 1);
        }
    });
}

// Init on load
checkStatusAndDevices();
loadTelemetryEvents();
listHistoricRuns();
