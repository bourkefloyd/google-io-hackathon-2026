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
const elViewportTabs = document.getElementById("viewport-tabs");
const elCoordinateOverlay = document.getElementById("coordinate-overlay");
const elThoughtsBox = document.getElementById("thoughts-box");
const elCommandBox = document.getElementById("command-box");
const elStepBadge = document.getElementById("step-badge");
const elStateBadge = document.getElementById("state-badge");
const elTelemetryStepDetails = document.getElementById("telemetry-step-details");
const elLogcatConsole = document.getElementById("logcat-console");
const elClearTelemetry = document.getElementById("btn-clear-telemetry");
const elBtnFilterActive = document.getElementById("btn-filter-active");
const elBtnFilterHistoric = document.getElementById("btn-filter-historic");
const elTimelineScrubber = document.getElementById("timeline-scrubber");
const elTimelineStepLabel = document.getElementById("timeline-step-label");
const elTimelineStatusDesc = document.getElementById("timeline-status-desc");
const elBtnPrevStep = document.getElementById("btn-prev-step");
const elBtnNextStep = document.getElementById("btn-next-step");

const elBtnTabView = document.getElementById("btn-tab-view");
const elBtnTabCreate = document.getElementById("btn-tab-create");
const elTabContentView = document.getElementById("tab-content-view");
const elTabContentCreate = document.getElementById("tab-content-create");
const elRunsList = document.getElementById("runs-list");

let selectedApkName = "";
let devicesCache = [];
let runsData = {}; // maps runId -> { config: {}, events: [], logs: "" }
let activeEventSources = {}; // maps runId -> EventSource
let selectedRunId = "none";
let selectedStepIndex = -1;
let currentFilter = "active"; // active or historic

// Tab Panels Switching
document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
        document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
        btn.classList.add("active");
        document.getElementById(btn.dataset.tab).classList.add("active");
    });
});

// Left Panel Tab Switching
if (elBtnTabView && elBtnTabCreate && elTabContentView && elTabContentCreate) {
    elBtnTabView.addEventListener("click", () => {
        elBtnTabView.classList.add("active");
        elBtnTabView.classList.remove("pulse-notify");
        elBtnTabCreate.classList.remove("active");
        elTabContentView.classList.remove("hidden");
        elTabContentCreate.classList.add("hidden");
    });

    elBtnTabCreate.addEventListener("click", () => {
        elBtnTabCreate.classList.add("active");
        elBtnTabView.classList.remove("active");
        elTabContentCreate.classList.remove("hidden");
        elTabContentView.classList.add("hidden");
    });
}

// Active vs Historic runs list filter toggles
if (elBtnFilterActive && elBtnFilterHistoric) {
    elBtnFilterActive.addEventListener("click", () => {
        currentFilter = "active";
        elBtnFilterActive.classList.add("active");
        elBtnFilterHistoric.classList.remove("active");
        listHistoricRuns();
    });

    elBtnFilterHistoric.addEventListener("click", () => {
        currentFilter = "historic";
        elBtnFilterHistoric.classList.add("active");
        elBtnFilterActive.classList.remove("active");
        listHistoricRuns();
    });
}

// Viewport Tabs Switching (Replay vs LLM Vision)
let activeViewport = "replay";

document.querySelectorAll(".viewport-tab").forEach(btn => {
    btn.addEventListener("click", () => {
        activeViewport = btn.dataset.viewport;
        updateViewportToggles();
    });
});

function updateViewportToggles() {
    const elReplayWrapper = document.getElementById("wrapper-replay");
    const elLlmWrapper = document.getElementById("wrapper-llm");
    const tabReplay = document.querySelector('.viewport-tab[data-viewport="replay"]');
    const tabLlm = document.querySelector('.viewport-tab[data-viewport="llm"]');
    
    if (activeViewport === "replay") {
        if (elReplayWrapper) elReplayWrapper.classList.remove("hidden");
        if (elLlmWrapper) elLlmWrapper.classList.add("hidden");
        if (tabReplay) tabReplay.classList.add("active");
        if (tabLlm) tabLlm.classList.remove("active");
    } else {
        if (elReplayWrapper) elReplayWrapper.classList.add("hidden");
        if (elLlmWrapper) elLlmWrapper.classList.remove("hidden");
        if (tabReplay) tabReplay.classList.remove("active");
        if (tabLlm) tabLlm.classList.add("active");
    }
}

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
        const statusText = d.status === "busy" ? " (busy)" : "";
        opt.innerText = `${icon} ${d.name} (${d.resolution})${statusText}`;
        elDeviceSelect.appendChild(opt);
    });

    if (selectedApkName) {
        elLaunchBtn.disabled = false;
        elLaunchBtn.classList.add("pulse");
    }
    
    updateFleetListUI(devices);
}

function updateFleetListUI(devices) {
    elFleetList.innerHTML = "";
    if (!devices || devices.length === 0) {
        elFleetList.innerHTML = `
            <div class="empty-state">
                <p>No active devices connected. Open Android Studio AVD Manager or plug in a device.</p>
            </div>
        `;
        return;
    }

    devices.forEach(d => {
        const statusText = d.status || "idle";
        const badgeClass = statusText === "busy" ? "playing" : "idle";
        
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

    elLaunchBtn.disabled = true;
    elLaunchBtn.querySelector(".btn-text").innerText = "Launching...";

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
            const chosenDevice = data.device_id;
            
            if (data.message) {
                // Show dynamic auto-routing redirection message to user beautifully
                showToast("Play Fleet Auto-Route", data.message, "ℹ️");
            } else {
                showToast("Player Simulation Started", `Successfully launched session run_${runId.substring(0, 8)} on device ${chosenDevice}!`, "🚀");
            }

            // Create local state entry
            runsData[runId] = {
                config: {
                    run_id: runId,
                    device_id: chosenDevice,
                    apk_name: selectedApkName,
                    package_name: packageName,
                    instructions: instructions,
                    max_steps: maxSteps,
                    timestamp: new Date().toISOString(),
                    status: "playing"
                },
                events: [],
                logs: "Simulation starting..."
            };

            // Activate the Active runs filter toggle visually and programmatically
            if (elBtnFilterActive) {
                currentFilter = "active";
                elBtnFilterActive.classList.add("active");
                if (elBtnFilterHistoric) elBtnFilterHistoric.classList.remove("active");
            }

            // Add notification pulse to View Run tab if user is currently on the Create Run tab
            if (elBtnTabView && !elBtnTabView.classList.contains("active")) {
                elBtnTabView.classList.add("pulse-notify");
            }

            // Set selected run and display in the background
            selectRun(runId);

            // Connect SSE stream in background
            connectSSEForRun(runId);

            // Refresh fleet device monitor statuses
            checkStatusAndDevices();

        } else {
            const err = await res.json();
            showToast("Launch Failed", err.detail || "Server error starting simulation.", "❌");
        }
    } catch (e) {
        console.error("Launch session error:", e);
        alert("Connection failed starting simulation run.");
    } finally {
        resetLaunchButtonState();
    }
});

// Stop Running Fleet Play
elStopBtn.addEventListener("click", async () => {
    const runId = selectedRunId;
    if (!runId || runId === "none" || !runsData[runId]) return;

    const status = runsData[runId].config.status;
    if (status !== "playing" && status !== "starting") return;

    elStopBtn.disabled = true;
    elStopBtn.querySelector(".btn-text").innerText = "Stopping...";
    try {
        const res = await fetch(`/api/play/stop?run_id=${runId}`, {
            method: "POST"
        });
        if (res.ok) {
            console.log(`Stop signal sent to run ${runId} successfully.`);
            
            // Cleanly close EventSource if it's open
            if (activeEventSources[runId]) {
                activeEventSources[runId].close();
                delete activeEventSources[runId];
            }
            
            // Update local state to "stopped"
            if (runsData[runId]) {
                runsData[runId].config.status = "stopped";
            }
            
            // Refresh fleet device statuses to release the device immediately
            checkStatusAndDevices();
            
            // Refresh the runs list from backend (which will fetch the updated on-disk states)
            await listHistoricRuns();
            
            // Refresh the cockpit
            selectRun(runId);
        } else {
            const err = await res.json();
            alert(`Failed to stop run: ${err.detail || "Server error"}`);
            elStopBtn.disabled = false;
            elStopBtn.querySelector(".btn-text").innerText = "Stop Run";
        }
    } catch (e) {
        console.error("Failed to send stop signal:", e);
        elStopBtn.disabled = false;
        elStopBtn.querySelector(".btn-text").innerText = "Stop Run";
    }
});

function resetLaunchButtonState() {
    elLaunchBtn.disabled = false;
    elLaunchBtn.querySelector(".btn-text").innerText = "Launch Simulated Player";
    toggleFormInputs(true);
    listHistoricRuns(); // Refresh historic runs lists
}

function toggleFormInputs(enabled) {
    elDeviceSelect.disabled = !enabled;
    elRefreshDevices.disabled = !enabled;
    elPackageName.disabled = !enabled;
    elMaxSteps.disabled = !enabled;
    elInstructions.disabled = !enabled;
    elDropzone.style.pointerEvents = enabled ? "auto" : "none";
}

function connectSSEForRun(runId) {
    if (activeEventSources[runId]) {
        activeEventSources[runId].close();
    }

    const es = new EventSource(`/api/events?run_id=${runId}`);
    activeEventSources[runId] = es;

    es.onmessage = (event) => {
        const packet = JSON.parse(event.data);
        handlePlayUpdate(packet, runId);
    };

    es.onerror = (e) => {
        console.error(`SSE Stream error for run ${runId}, closing connection.`, e);
        es.close();
        delete activeEventSources[runId];
        
        // Wait briefly and verify if the run is still active on the backend before failing it
        setTimeout(async () => {
            await listHistoricRuns();
            if (runsData[runId] && runsData[runId].config.status === "playing") {
                console.log(`Run ${runId} is still active on backend. Reconnecting SSE...`);
                connectSSEForRun(runId);
            } else {
                // If it is no longer playing and wasn't marked completed/stopped, set to failed
                if (runsData[runId] && runsData[runId].config.status !== "completed" && runsData[runId].config.status !== "stopped") {
                    runsData[runId].config.status = "failed";
                    if (selectedRunId === runId) {
                        renderTimeline(runsData[runId].events, "failed");
                    }
                }
            }
        }, 1000);
    };
}

// Process Real-time Gameplay telemetry packet from SSE
function handlePlayUpdate(packet, runId) {
    const status = packet.status;
    
    if (!runsData[runId]) {
        runsData[runId] = {
            config: { run_id: runId, status: status },
            events: [],
            logs: ""
        };
    }

    runsData[runId].config.status = status;

    if (packet.message) {
        runsData[runId].logs = (runsData[runId].logs || "") + "\n" + packet.message;
        if (selectedRunId === runId) {
            elThoughtsBox.innerHTML = `<span>${packet.message}</span>`;
        }
    }

    if (packet.logs_update) {
        runsData[runId].logs = packet.logs_update;
        if (selectedRunId === runId) {
            elLogcatConsole.innerText = packet.logs_update;
        }
    }

    if (packet.logs) {
        runsData[runId].logs = packet.logs;
    }

    // Step gameplay loop packets
    if (status === "playing" && packet.step) {
        let events = runsData[runId].events;
        let existingEvent = events.find(e => e.step_index === packet.step);
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
                actions_taken: packet.actions_taken || [],
                action_summary: packet.action || "",
                logs: ""
            };
            events.push(existingEvent);
        } else {
            if (packet.start_time) existingEvent.start_time = packet.start_time;
            if (packet.duration !== undefined) existingEvent.duration = packet.duration;
            if (packet.screenshot) existingEvent.screenshot = packet.screenshot;
            if (packet.screenshot_path) existingEvent.screenshot_path = packet.screenshot_path;
            if (packet.screenshot_llm) existingEvent.screenshot_llm = packet.screenshot_llm;
            if (packet.screenshot_llm_path) existingEvent.screenshot_llm_path = packet.screenshot_llm_path;
            if (packet.reasoning) existingEvent.agent_reasoning = packet.reasoning;
            if (packet.action) existingEvent.action_summary = packet.action;
            if (packet.actions_taken) existingEvent.actions_taken = packet.actions_taken;
        }

        // If currently viewed, update the cockpit
        if (selectedRunId === runId) {
            renderTimeline(events, "playing");
            selectTimelineStep(events.length - 1);
        }
    }

    if (status === "completed" || status === "failed") {
        if (packet.logs) {
            runsData[runId].logs = packet.logs;
        }
        
        if (activeEventSources[runId]) {
            activeEventSources[runId].close();
            delete activeEventSources[runId];
        }

        listHistoricRuns(); // Refresh runs cards list

        if (selectedRunId === runId) {
            elStepBadge.innerText = status;
            elStepBadge.className = `badge ${status}`;
            
            if (status === "completed") {
                elThoughtsBox.innerHTML = `<span style="color: var(--success); font-weight: 600;">✅ Play session completed successfully! APK stopped. Logcat compiled.</span>`;
                elCommandBox.innerHTML = "<code>adb shell am force-stop</code>";
                elStateBadge.innerText = "completed";
                elStateBadge.className = "badge-tag state-tag completed";
            } else {
                elThoughtsBox.innerHTML = `<span style="color: var(--danger); font-weight: 600;">❌ Session failed / stopped by user request.</span>`;
                elStateBadge.innerText = "stopped";
                elStateBadge.className = "badge-tag state-tag failed";
            }

            if (runsData[runId].logs) {
                elLogcatConsole.innerText = runsData[runId].logs;
            }

            renderTimeline(runsData[runId].events, status);
        }

        // Refresh devices list
        checkStatusAndDevices();
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

// Selects and displays detail viewport for specific step of timeline
function selectTimelineStep(index) {
    const run = runsData[selectedRunId];
    if (!run) return;
    const events = run.events;
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
        if (elViewportTabs) elViewportTabs.classList.remove("hidden");
        updateViewportToggles();
    } else {
        elViewportPlaceholder.classList.remove("hidden");
        if (elDualViewports) elDualViewports.classList.add("hidden");
        if (elViewportTabs) elViewportTabs.classList.add("hidden");
    }
    
    // 2. Parse and render Structured Reasoning Cards
    renderStructuredReasoning(ev.agent_reasoning);
    
    // 3. Render coordinate tap dot overlay
    elCoordinateOverlay.innerHTML = "";
    let hasTapDot = false;
    if (ev.actions_taken && ev.actions_taken.length > 0) {
        ev.actions_taken.forEach(action => {
            if (action.type === "tap" && action.params) {
                const relX = parseFloat(action.params.x);
                const relY = parseFloat(action.params.y);
                if (!isNaN(relX) && !isNaN(relY)) {
                    renderTapOnOverlay(relX, relY);
                    hasTapDot = true;
                }
            }
        });
    }
    
    if (!hasTapDot && ev.action_summary && ev.action_summary.includes("Tapped position")) {
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
    
    // 8. Update Step Telemetry details
    renderStepTelemetry(ev);
    
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
            
            // Sync local runsData state with backend
            data.runs.forEach(r => {
                if (!runsData[r.run_id]) {
                    runsData[r.run_id] = {
                        config: r,
                        events: [],
                        logs: ""
                    };
                } else {
                    runsData[r.run_id].config = r;
                }
            });
            
            renderRunsListCards(data.runs);
        }
    } catch (e) {
        console.error("Failed to load historic runs list:", e);
    }
}

function renderRunsListCards(runs) {
    if (!elRunsList) return;
    elRunsList.innerHTML = "";
    
    // Filter runs based on Active vs Historic toggle filter
    const filteredRuns = runs.filter(r => {
        if (currentFilter === "active") {
            return r.status === "playing" || r.status === "starting";
        } else {
            return r.status !== "playing" && r.status !== "starting";
        }
    });

    if (filteredRuns.length === 0) {
        const emptyMsg = currentFilter === "active" 
            ? "No active simulated runs currently in progress." 
            : "No historic simulation runs loaded.";
        elRunsList.innerHTML = `
            <div class="empty-state">
                <p>${emptyMsg}</p>
            </div>
        `;
        return;
    }

    filteredRuns.forEach(r => {
        const isSelected = selectedRunId === r.run_id;
        const statusClass = r.status || "idle";
        
        const date = r.timestamp ? r.timestamp.split("T")[0] : "N/A";
        const time = r.timestamp ? r.timestamp.split("T")[1].substring(0, 5) : "";
        
        const card = document.createElement("div");
        card.className = `run-card-item ${statusClass} ${isSelected ? 'selected' : ''}`;
        card.dataset.runId = r.run_id;
        
        card.innerHTML = `
            <div class="run-card-header">
                <span class="run-card-id">🆔 ${r.run_id}</span>
                <span class="device-badge ${statusClass}">${r.status}</span>
            </div>
            <div class="run-card-body">
                <span class="run-card-apk" title="${r.apk_name}">📦 ${r.apk_name || "Unknown APK"}</span>
                <div class="run-card-meta">
                    <span>📱 Dev: <code>${r.device_id || "N/A"}</code></span>
                    <span>🏁 Steps: ${r.max_steps || 50}</span>
                </div>
            </div>
            <div class="run-card-footer">
                <span>📅 Started: ${date} ${time}</span>
            </div>
        `;
        
        card.addEventListener("click", () => {
            selectRun(r.run_id);
        });
        
        elRunsList.appendChild(card);
    });
}

async function selectRun(runId) {
    if (!runId || runId === "none") {
        clearTimelineDetails();
        return;
    }

    selectedRunId = runId;
    selectedStepIndex = -1;
    
    // Highlight active card selection
    document.querySelectorAll(".run-card-item").forEach(card => {
        if (card.dataset.runId === runId) {
            card.classList.add("selected");
        } else {
            card.classList.remove("selected");
        }
    });

    const run = runsData[runId];
    if (!run) {
        clearTimelineDetails();
        return;
    }

    const isPlaying = run.config.status === "playing" || run.config.status === "starting";

    // If events are not loaded yet, fetch them from backend (supports history recovery on page refresh)
    if (run.events.length === 0) {
        if (elTimelineStepLabel) elTimelineStepLabel.innerText = "Loading...";
        if (elTimelineStatusDesc) elTimelineStatusDesc.innerText = "Loading run details...";
        
        try {
            const res = await fetch(`/api/runs/${runId}`);
            if (res.ok) {
                const data = await res.json();
                run.events = data.telemetry || [];
                run.logs = data.logs || "No logs were captured for this run.";
                runsData[runId] = run;
            }
        } catch (e) {
            console.error(`Failed to load details for run ${runId}`, e);
        }
    }

    // Render timeline and status
    elStepBadge.innerText = run.config.status;
    elStepBadge.className = `badge ${run.config.status}`;
    
    elStateBadge.innerText = isPlaying ? "playing" : "historic";
    elStateBadge.className = `badge-tag state-tag ${isPlaying ? "thinking" : "idle"}`;

    elLogcatConsole.innerText = run.logs || "Waiting for game session logcat dump...";

    // Configure stop button visibility
    if (isPlaying) {
        elStopBtn.disabled = false;
        elStopBtn.classList.remove("hidden");
        elStopBtn.querySelector(".btn-text").innerText = "Stop Run";

        // Automatically connect to SSE stream if not connected yet
        if (!activeEventSources[runId]) {
            console.log(`Connecting to SSE stream for active run ${runId}`);
            connectSSEForRun(runId);
        }
    } else {
        elStopBtn.disabled = true;
        elStopBtn.classList.add("hidden");
    }

    renderTimeline(run.events, run.config.status);
    
    if (run.events.length > 0) {
        selectTimelineStep(run.events.length - 1);
    } else {
        clearTimelineDetails();
        if (isPlaying) {
            elTimelineStatusDesc.innerText = "Waiting for step 1 frame...";
        }
    }
}



function clearTimelineDetails() {
    elViewportPlaceholder.classList.remove("hidden");
    if (elDualViewports) elDualViewports.classList.add("hidden");
    if (elViewportTabs) elViewportTabs.classList.add("hidden");
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
    if (elTelemetryStepDetails) {
        elTelemetryStepDetails.innerHTML = `<span class="dimmed">No active step selected. Use the scrubber timeline to inspect step telemetry.</span>`;
    }
    
    // Disable prev/next buttons on clear
    if (elBtnPrevStep && elBtnNextStep) {
        elBtnPrevStep.disabled = true;
        elBtnNextStep.disabled = true;
    }
    selectedStepIndex = -1;
}

function renderStepTelemetry(ev) {
    if (!elTelemetryStepDetails) return;
    
    if (!ev) {
        elTelemetryStepDetails.innerHTML = `<span class="dimmed">No step telemetry available.</span>`;
        return;
    }
    
    const time = ev.timestamp ? ev.timestamp.split("T")[1].substring(0, 8) : "--:--:--";
    const date = ev.timestamp ? ev.timestamp.split("T")[0] : "----/--/--";
    
    elTelemetryStepDetails.innerHTML = `
        <div class="telemetry-grid">
            <div class="telemetry-item">
                <span class="telemetry-label">⏰ Start Time (UTC)</span>
                <span class="telemetry-value">${time} <small class="dimmed">${date}</small></span>
            </div>
            <div class="telemetry-item">
                <span class="telemetry-label">⏱️ Step Duration</span>
                <span class="telemetry-value font-primary">${ev.duration !== undefined ? `${ev.duration} seconds` : "N/A"}</span>
            </div>
            <div class="telemetry-item">
                <span class="telemetry-label">📍 Step Index</span>
                <span class="telemetry-value badge-style">Step ${ev.step_index}</span>
            </div>
            <div class="telemetry-item">
                <span class="telemetry-label">📱 Target Device</span>
                <span class="telemetry-value"><code>${ev.emulator_id || "N/A"}</code></span>
            </div>
            <div class="telemetry-item">
                <span class="telemetry-label">📦 APK Package</span>
                <span class="telemetry-value"><code>${ev.package_name || "N/A"}</code></span>
            </div>
            <div class="telemetry-item" style="grid-column: span 2;">
                <span class="telemetry-label">🎮 Player Actions & Tool Calls</span>
                <div class="telemetry-value" style="font-size: 0.8rem; line-height: 1.4; margin-top: 0.25rem;">
                    ${(() => {
                        if (ev.actions_taken && ev.actions_taken.length > 0) {
                            return ev.actions_taken.map(action => {
                                let detail = `<strong style="color: var(--primary-hover);">${action.type.toUpperCase()}</strong>`;
                                if (action.params && Object.keys(action.params).length > 0) {
                                    detail += `: <code style="background: rgba(0,0,0,0.3); padding: 0.1rem 0.3rem; border-radius: 4px;">${JSON.stringify(action.params)}</code>`;
                                }
                                if (action.adb_command) {
                                    detail += `<br><small class="dimmed" style="font-family: var(--font-mono); font-size: 0.68rem; margin-top: 0.25rem; display: block;">💻 ${action.adb_command}</small>`;
                                }
                                return `<div class="action-detail-row" style="padding: 0.3rem 0; border-bottom: 1px solid rgba(255,255,255,0.05);">${detail}</div>`;
                            }).join("");
                        }
                        return ev.action_summary || "No actions performed (observing)";
                    })()}
                </div>
            </div>
        </div>
    `;
}

// Retain empty backwards compatible shell to prevent other event listeners from failing
async function loadTelemetryEvents() {
    // Deprecated: Telemetry is now step-specific
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
        const run = runsData[selectedRunId];
        const events = run ? run.events : [];
        if (events && selectedStepIndex < events.length - 1) {
            selectTimelineStep(selectedStepIndex + 1);
        }
    });
}

// Premium Non-Blocking Toast Notifications Utility
function showToast(title, message, icon = "🚀") {
    const container = document.getElementById("toast-container");
    if (!container) return;

    const toast = document.createElement("div");
    toast.className = "toast-item";
    toast.innerHTML = `
        <div class="toast-icon">${icon}</div>
        <div class="toast-content">
            <div class="toast-title">${title}</div>
            <div class="toast-message">${message}</div>
        </div>
        <button type="button" class="toast-close">&times;</button>
    `;

    container.appendChild(toast);

    // Trigger reflow for CSS animation entry
    toast.offsetHeight;
    toast.classList.add("show");

    // Close button handler
    const closeBtn = toast.querySelector(".toast-close");
    closeBtn.addEventListener("click", () => {
        toast.classList.remove("show");
        toast.classList.add("hide");
        setTimeout(() => toast.remove(), 400);
    });

    // Auto dismiss after 6 seconds
    setTimeout(() => {
        if (toast.parentNode) {
            toast.classList.remove("show");
            toast.classList.add("hide");
            setTimeout(() => toast.remove(), 400);
        }
    }, 6000);
}

// Init on load
checkStatusAndDevices();
loadTelemetryEvents();
listHistoricRuns();
