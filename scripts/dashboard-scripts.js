// scripts/dashboard-scripts.js
// This script handles dynamic updates for the AgentOS dashboard.

document.addEventListener('DOMContentLoaded', () => {
    const els = {
        serverStatus: document.getElementById("server-status"),
        connectionStatus: document.getElementById("connection-status"),
        lastUpdated: document.getElementById("last-updated"),
        agentsList: document.getElementById("agents-list"),
        logStream: document.getElementById("log-stream"),
        selfHealStatusList: document.getElementById("self-heal-status-list"),
        selfHealSuggestions: document.getElementById("self-heal-suggestions"),
        servicesList: document.getElementById("services-list"),
        commandOutput: document.getElementById("command-output"),
        commandForm: document.getElementById("command-form"),
        commandInput: document.getElementById("command-input"),
        statusPill: document.getElementById("status-pill"), // Added for hero section
        uptimeDisplay: document.getElementById("uptime-display"), // Added for hero section
        aiRoutingDisplay: document.getElementById("ai-routing-display"), // Added for hero section
        environmentBadge: document.getElementById("environment-badge"), // Added for hero section
    };

    let pendingApproval = null;
    let agentStates = {}; // To track agent toggle states
    let logs = []; // For logs preview

    function escapeHtml(value) {
        return String(value)
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    function normalizeLogLevel(entry) {
        const level = String(entry.level || "").toLowerCase();
        if (level === "warning" || String(entry.message || "").startsWith("WARNING:")) return "warn";
        if (level === "error" || String(entry.message || "").startsWith("ERROR:")) return "danger";
        return "info";
    }

    function formatLogTime(value) {
        const date = value ? new Date(value) : new Date();
        if (Number.isNaN(date.getTime())) return new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
        return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    }

    function appendLog(source, message, level = "info") {
        logs.push({ source, message, level, timestamp: new Date().toISOString() });
        if (logs.length > 50) logs.shift(); // Keep log size manageable
        if (els.logStream) renderLogs(logs.slice(-5)); // Render last 5 logs for preview
    }

    function renderLogs(logEntries) {
        if (!els.logStream) return;
        const entries = Array.isArray(logEntries) ? logEntries : logs.slice(-5); // Use passed entries or default to internal logs
        if (entries.length === 0) {
            els.logStream.innerHTML = '<div class="log-line"><span class="log-time">--</span><span class="log-source">system</span><span class="log-level">INFO</span><span class="log-message">No recent logs.</span></div>';
            return;
        }
        els.logStream.innerHTML = entries.map((entry) => {
            const level = normalizeLogLevel(entry);
            return '<div class="log-line ' + level + '"><span class="log-time">' + escapeHtml(formatLogTime(entry.timestamp)) + '</span><span class="log-source">' + escapeHtml(entry.source || "agent") + '</span><span class="log-level">' + level.toUpperCase() + '</span><span class="log-message">' + escapeHtml(entry.message || "") + '</span></div>';
        }).join("");
        els.logStream.scrollTop = els.logStream.scrollHeight;
    }

    function setAgents(agents) {
        if (!els.agentsList) return;
        els.agentsList.innerHTML = agents.map((agent) => {
            const running = agent.status === "online";
            agentStates[agent.name] = running; // Update agent state for toggling
            const statusClass = running ? "online" : (agent.status === "offline" ? "offline" : "unknown");
            return `
                <li class="agent-item">
                    <span class="icon">${agent.icon || ""}</span>
                    <span class="agent-name">${escapeHtml(agent.display_name)}</span>
                    <span class="agent-status ${statusClass}">● ${escapeHtml(agent.status)}</span>
                    <button class="button secondary agent-toggle" type="button" data-agent="${escapeHtml(agent.name)}" ${agent.name === 'system_watcher' ? '' : 'hidden'}>
                        ${running ? "Stop" : "Start"}
                    </button>
                </li>
            `;
        }).join("");
    }

    async function refreshLogs() {
        try {
            const response = await fetch("/agent-logs", { cache: "no-store" });
            if (!response.ok) throw new Error("Log request failed");
            const agentLogs = await response.json();
            logs = agentLogs.logs || []; // Overwrite with fresh logs
            if (els.logStream) renderLogs(logs.slice(-5)); // Only display last 5 in dashboard preview
        } catch (error) {
            appendLog("system_agent", "Log refresh failed.", "danger");
        }
    }

    async function refreshSelfHealing() {
        if (!els.selfHealStatusList) return; // Only refresh if the element exists
        try {
            const [statusResponse, suggestionsResponse] = await Promise.all([
                fetch("/self-heal/status", { cache: "no-store" }),
                fetch("/self-heal/suggestions", { cache: "no-store" }),
            ]);

            if (!statusResponse.ok || !suggestionsResponse.ok) throw new Error("Self-heal request failed");

            const status = await statusResponse.json();
            const suggestions = await suggestionsResponse.json();
            renderSelfHealStatus(status);
            renderSelfHealSuggestions(suggestions.suggestions);
        } catch (error) {
            appendLog("self_healing_agent", "Self-healing refresh failed.", "danger");
        }
    }

    function renderSelfHealStatus(status) {
        if (!els.selfHealStatusList) return;
        const running = Boolean(status && status.running);
        const state = running ? "running" : "stopped";
        const lastCheck = status && status.last_check ? new Date(status.last_check).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "--";
        const suggestionCount = status && Number.isFinite(Number(status.suggestion_count)) ? Number(status.suggestion_count) : 0;
        els.selfHealStatusList.innerHTML = `
            <li>
                <span class="icon">🤖</span>
                <span class="agent-meta">
                    <span class="agent-name"><span class="agent-status-dot"></span>self_healing_agent</span>
                    <span class="agent-description">Status: ${escapeHtml(state)} · Last check: ${escapeHtml(lastCheck)} · Suggestions: ${suggestionCount}</span>
                </span>
            </li>
        `;
    }

    function renderSelfHealSuggestions(suggestions) {
        if (!els.selfHealSuggestions) return;
        const items = Array.isArray(suggestions) ? suggestions : [];
        if (items.length === 0) {
            els.selfHealSuggestions.innerHTML = `
                <li>
                    <span class="icon">✅</span>
                    <span class="agent-meta">
                        <span class="agent-name">System healthy</span>
                        <span class="agent-description">No actions required.</span>
                    </span>
                </li>
            `;
            return;
        }
        els.selfHealSuggestions.innerHTML = items.map((suggestion) => {
            const action = suggestion.suggested_action || "";
            const actionText = action || suggestion.detail || "Review manually";
            const approveButton = action ? `<button class="button secondary self-heal-approve" type="button" data-action="${escapeHtml(action)}">Approve</button>` : '';
            return `
                <li>
                    <span class="icon">⚠️</span>
                    <span class="agent-meta">
                        <span class="agent-name">${escapeHtml(suggestion.message || "Self-healing suggestion")}</span>
                        <span class="agent-description">Recommended action: ${escapeHtml(actionText)}</span>
                    </span>
                    ${approveButton}
                </li>
            `;
        }).join("");
    }

    async function refreshControl() {
        try {
            const [systemResponse, agentsResponse, logsResponse] = await Promise.all([
                fetch("/system", { cache: "no-store" }),
                fetch("/agents/data", { cache: "no-store" }),
                fetch("/agent-logs", { cache: "no-store" }),
            ]);

            if (!systemResponse.ok || !agentsResponse.ok || !logsResponse.ok) throw new Error("Control request failed");

            const system = await systemResponse.json();
            const agents = await agentsResponse.json();
            const agentLogs = await logsResponse.json();
            const now = new Date();

            if (els.serverStatus) els.serverStatus.textContent = "Online";
            if (els.statusPill) els.statusPill.classList.remove("danger");
            if (els.connectionStatus) els.connectionStatus.textContent = "online";
            if (els.lastUpdated) els.lastUpdated.textContent = "Last updated: " + now.toLocaleTimeString();

            // Update hero section elements
            if (els.uptimeDisplay) els.uptimeDisplay.textContent = system.uptime || "N/A"; // Assuming system endpoint provides uptime
            if (els.environmentBadge) els.environmentBadge.textContent = system.environment || "dev"; // Assuming system endpoint provides environment
            // AI Routing and Provider status will need more detailed data from the backend

            agentStates.system_agent = Boolean(agentLogs.status && agentLogs.status.running);
            setAgents(agents.agents);
            logs = agentLogs.logs || []; // Update global logs array
            if (els.logStream) renderLogs(logs.slice(-5)); // Render last 5 logs for preview

        } catch (error) {
            if (els.serverStatus) els.serverStatus.textContent = "Offline";
            if (els.statusPill) els.statusPill.classList.add("danger");
            if (els.connectionStatus) els.connectionStatus.textContent = "offline";
            if (els.lastUpdated) els.lastUpdated.textContent = "Last updated: failed at " + new Date().toLocaleTimeString();
            if (els.agentsList) els.agentsList.innerHTML = '<li><span class="agent-meta"><span class="agent-description">Unable to load available agents.</span></span></li>';
            appendLog("system_agent", "Control refresh failed.", "danger");
        }
    }

    // Initial load and periodic refreshes
    refreshControl();
    refreshSelfHealing(); // Ensure self-healing is also refreshed if its panel exists
    refreshLogs(); // Initial log refresh
    setInterval(refreshLogs, 3000); // Only logs refresh every 3 seconds
    setInterval(refreshSelfHealing, 5000); // Self-healing every 5 seconds
    setInterval(refreshControl, 5000); // Main control every 5 seconds

    // Event listeners (copied from original app.py)
    if (els.commandForm) {
        els.commandForm.addEventListener("submit", (event) => {
            event.preventDefault();
            submitCommand(els.commandInput.value);
        });
    }

    if (els.commandOutput) {
        els.commandOutput.addEventListener("click", (event) => {
            const action = event.target.dataset.commandAction;
            if (action === "approve") {
                approvePendingCommand();
            }
            if (action === "cancel") {
                pendingApproval = null;
                els.commandOutput.textContent = "Command approval canceled.";
                appendLog("command_center", "Command approval canceled.");
            }
        });
    }

    if (els.selfHealSuggestions) {
        els.selfHealSuggestions.addEventListener("click", (event) => {
            const button = event.target.closest(".self-heal-approve");
            if (!button) return;
            // approveSelfHealAction is not defined in this script
            // Assuming this is handled by a backend call or dedicated self-heal page
            appendLog("system_agent", "Self-heal approval not implemented in dashboard script.", "warn");
        });
    }

    if (els.servicesList) {
        els.servicesList.addEventListener("click", (event) => {
            const button = event.target.closest(".service-action");
            if (!button) return;
            // approveSelfHealAction is not defined in this script
            appendLog("system_agent", "Service action not implemented in dashboard script.", "warn");
        });
    }

    if (els.agentsList) {
        els.agentsList.addEventListener("click", async (event) => {
            const button = event.target.closest(".agent-toggle");
            if (!button) return;
            const agentName = button.dataset.agent;
            if (agentName === "system_watcher") {
                const nextAction = agentStates.system_agent ? "stop" : "start";
                button.disabled = true;
                try {
                    const response = await fetch("/agents/system_watcher/" + nextAction, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                    });
                    if (!response.ok) throw new Error("Watcher request failed");
                    const status = await response.json();
                    agentStates.system_agent = Boolean(status.running);
                    button.textContent = agentStates.system_agent ? "Stop" : "Start";
                    appendLog("system_watcher", `system_watcher ${agentStates.system_agent ? "started" : "stopped"}.`);
                } catch (error) {
                    appendLog("system_watcher", "system_watcher control request failed.", "danger");
                } finally {
                    button.disabled = false;
                }
                return;
            }
            // For other agents, simply toggle state visually if no backend interaction is required from dashboard
            agentStates[agentName] = !agentStates[agentName];
            button.textContent = agentStates[agentName] ? "Stop" : "Start";
            appendLog("system_agent", `${agentName} ${agentStates[agentName] ? "started" : "stopped"}.`);
        });
    }

    // Command submission logic (from original app.py, adjusted for dashboard)
    async function submitCommand(input) {
        const command = input.trim();
        if (!command) return;

        if (els.commandOutput) {
            els.commandOutput.textContent = "Running command...";
            els.commandOutput.classList.add("visible");
        }
        appendLog("command_center", "Command submitted: " + command);

        try {
            const response = await fetch("/command", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ input: command }),
            });

            if (!response.ok) throw new Error("Command request failed");
            const data = await response.json();
            if (els.commandOutput) renderCommandResult(data);
            appendLog(data.agent || "command_center", data.response || "Command completed.");
        } catch (error) {
            pendingApproval = null;
            if (els.commandOutput) els.commandOutput.textContent = "Command failed. Check server logs for details.";
            appendLog("command_center", "Command failed.", "danger");
        }
    }

    async function approvePendingCommand() {
        if (!pendingApproval) return;

        if (els.commandOutput) els.commandOutput.textContent = "Running approved command...";
        appendLog("command_center", "Approved action: " + pendingApproval.action);

        try {
            const response = await fetch("/command/approve", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(pendingApproval),
            });

            if (!response.ok) throw new Error("Approval request failed");

            const data = await response.json();
            pendingApproval = null;
            if (els.commandOutput) els.commandOutput.textContent = JSON.stringify(data, null, 2);
            appendLog(data.agent || "command_center", `Approved command finished with exit code ${data.exit_code}.`);
        } catch (error) {
            pendingApproval = null;
            if (els.commandOutput) els.commandOutput.textContent = "Approved command failed. Check server logs for details.";
            appendLog("command_center", "Approved command failed.", "danger");
        }
    }

});
