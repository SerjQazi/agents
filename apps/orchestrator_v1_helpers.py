"""ORCHESTRATOR_V1 Cyberpunk UI Helpers.

Tactical components for the FiveM AI IDE.
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from typing import Any


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def render_sidebar(active: str = "dashboard") -> str:
    """Render the cyberpunk tactical sidebar."""
    
    nav_sections = [
        ("CONTROL", [
            ("dashboard", "/dashboard-v2", "⌁", "Mission Control"),
            ("upload", "/upload", "⇪", "Upload Pipeline"),
            ("agents", "/agents", "◉", "Active Agents"),
            ("reviews", "/reviews", "▣", "Codex Review"),
            ("logs", "/logs", "☰", "System Logs"),
            ("ops", "/ops", "✦", "System Health"),
            ("guide", "/guide", "?", "Documentation"),
        ]),
    ]
    
    parts = ['<aside class="cyber-sidebar">']
    parts.append('''
    <div class="cyber-brand">
        <span class="brand-mark">A9</span>
        <div class="brand-text">
            <span class="brand-name">FiveM_AI_IDE</span>
            <span class="brand-version">ORCHESTRATOR_V1</span>
            <span class="brand-instance">Instance: Alpha-9</span>
        </div>
    </div>
    ''')
    
    for title, items in nav_sections:
        parts.append(f'<div class="cyber-nav-section">{esc(title)}')
        for key, path, icon, label in items:
            active_class = "cyber-nav-link active" if key == active else "cyber-nav-link"
            parts.append(
                f'<a class="{active_class}" href="{esc(path)}">'
                f'<span class="nav-icon">{esc(icon)}</span><span>{esc(label)}</span></a>'
            )
        parts.append('</div>')

    parts.append(
        """
        <div class="cyber-sidebar-utility">
            <div class="utility-row"><span class="dot success"></span><span>Guard Mode</span><strong>SAFE</strong></div>
            <div class="utility-row"><span class="dot cyan"></span><span>Patch Queue</span><strong>LIVE</strong></div>
            <div class="utility-row"><span class="dot warn"></span><span>Apply Mode</span><strong>MANUAL</strong></div>
        </div>
        """
    )
    
    parts.append('</aside>')
    return "".join(parts)


def render_topbar(stats: dict[str, Any] | None = None) -> str:
    """Render the tactical top status bar."""
    
    stats = stats or {}
    now = datetime.now(timezone.utc)
    
    cpu = stats.get("cpu", "12%")
    mem = stats.get("memory", "3.2G")
    active = stats.get("active_tasks", "3")
    title = str(stats.get("title") or "").strip()
    title_html = f'<span class="topbar-title">{esc(title)}</span>' if title else ""
    
    return f'''
    <header class="cyber-topbar">
        <div class="topbar-left">
            <span class="system-status">
                <span class="status-dot online"></span>
                <span class="status-text">ORCHESTRATOR_V1</span>
            </span>
            {title_html}
        </div>
        <div class="topbar-center">
            <span class="system-metric"><span class="metric-label">CPU_LOAD</span><span class="metric-value">{esc(cpu)}</span></span>
            <span class="system-metric"><span class="metric-label">MEM_ALLOC</span><span class="metric-value">{esc(mem)}</span></span>
            <span class="system-metric"><span class="metric-label">CONN</span><span class="metric-value">ONLINE</span></span>
            <span class="system-metric"><span class="metric-label">UPTIME</span><span class="metric-value">{esc(stats.get("uptime", "n/a"))}</span></span>
        </div>
        <div class="topbar-right">
            <span class="system-time">{now.strftime("%H:%M:%S")} UTC</span>
            <span class="utility-icons" aria-label="utility">◳ ◲ ⌁</span>
        </div>
    </header>
    '''


def render_modal(title: str, content: str, modal_id: str = "modal") -> str:
    """Render a tactical modal."""
    
    return f'''
    <div class="cyber-modal-overlay" id="{esc(modal_id)}-overlay" onclick="closeCyberModal('{esc(modal_id)}')">
        <div class="cyber-modal" id="{esc(modal_id)}" onclick="event.stopPropagation()">
            <div class="cyber-modal-header">
                <span class="cyber-modal-title">{esc(title)}</span>
                <button class="cyber-modal-close" onclick="closeCyberModal('{esc(modal_id)}')">✕</button>
            </div>
            <div class="cyber-modal-content">
                <pre class="cyber-modal-text">{content}</pre>
            </div>
            <div class="cyber-modal-footer">
                <button class="cyber-btn" onclick="copyToClipboard(`{_escape_js(content)}`)">⧉ COPY</button>
                <button class="cyber-btn" onclick="closeCyberModal('{esc(modal_id)}')">CLOSE</button>
            </div>
        </div>
    </div>
    '''


def _escape_js(text: str) -> str:
    return text.replace("`", "\\`").replace("${", "\\${")


def render_panel(title: str, content: str, panel_class: str = "") -> str:
    """Render a tactical panel."""
    
    return f'''
    <div class="cyber-panel {esc(panel_class)}">
        <div class="cyber-panel-header">
            <span class="cyber-panel-title">{esc(title)}</span>
        </div>
        <div class="cyber-panel-content">
            {content}
        </div>
    </div>
    '''


def render_status_badge(status: str, label: str | None = None) -> str:
    """Render a tactical status badge."""
    
    label = label or status.upper()
    
    status_classes = {
        "online": "badge-success",
        "active": "badge-success",
        "completed": "badge-success",
        "pending": "badge-warning",
        "paused": "badge-warning",
        "running": "badge-info",
        "failed": "badge-danger",
        "error": "badge-danger",
        "cancelled": "badge-danger",
    }
    
    badge_class = status_classes.get(status.lower(), "badge-default")
    
    return f'<span class="cyber-badge {badge_class}">{esc(label)}</span>'


def render_tactical_button(label: str, onclick: str = "", btn_class: str = "cyber-btn") -> str:
    """Render a tactical button."""
    
    onclick_attr = f' onclick="{esc(onclick)}"' if onclick else ""
    
    return f'<button class="{esc(btn_class)}"{onclick_attr}>{esc(label)}</button>'


def cyber_layout_css() -> str:
    """Return the cyberpunk CSS."""
    
    return """
    :root {
        --cyber-bg: #051424;
        --cyber-bg-deep: #010f1f;
        --cyber-surface: #0d1c2d;
        --cyber-surface-2: #122131;
        --cyber-panel: rgba(13, 28, 45, 0.94);
        --cyber-border: rgba(0, 242, 255, 0.18);
        --cyber-border-active: rgba(0, 242, 255, 0.46);
        --cyber-text: #e0f4ff;
        --cyber-muted: #7f99b2;
        --cyber-cyan: #00f2ff;
        --cyber-cyan-dim: rgba(0, 242, 255, 0.13);
        --cyber-green: #00ff9f;
        --cyber-red: #ff5f7a;
        --cyber-yellow: #ffc857;
        --cyber-sidebar-width: 280px;
        --cyber-radius: 4px;
        /* Compatibility aliases used by existing page-level styles. */
        --ao-bg: var(--cyber-bg);
        --ao-panel: var(--cyber-panel);
        --ao-panel-strong: var(--cyber-panel);
        --ao-border: var(--cyber-border);
        --ao-border-strong: var(--cyber-border-active);
        --ao-text: var(--cyber-text);
        --ao-muted: var(--cyber-muted);
        --ao-soft: #8ea6bf;
        --ao-cyan: var(--cyber-cyan);
        --ao-blue: #73d9ff;
        --ao-green: var(--cyber-green);
        --ao-danger: var(--cyber-red);
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }

    html, body {
        width: 100%;
        min-width: 0;
    }

    body {
        min-height: 100vh;
        font-family: 'Inter', 'JetBrains Mono', system-ui, sans-serif;
        font-size: 13px;
        line-height: 1.5;
        background: var(--cyber-bg);
        color: var(--cyber-text);
        overflow-x: hidden;
    }

    a { color: var(--cyber-cyan); text-decoration: none; }
    a:hover { color: var(--cyber-green); }

    /* Scrollbars */
    * {
        scrollbar-width: thin;
        scrollbar-color: rgba(0, 242, 255, 0.45) rgba(6, 14, 24, 0.95);
    }
    *::-webkit-scrollbar {
        width: 10px;
        height: 10px;
    }
    *::-webkit-scrollbar-track {
        background: rgba(6, 14, 24, 0.95);
    }
    *::-webkit-scrollbar-thumb {
        background: rgba(0, 242, 255, 0.32);
        border: 1px solid rgba(0, 242, 255, 0.46);
        border-radius: 4px;
    }
    *::-webkit-scrollbar-thumb:hover {
        background: rgba(0, 242, 255, 0.5);
    }

    /* Layout */
    .cyber-shell {
        display: flex;
        height: 100vh;
        width: 100%;
        min-width: 0;
        overflow: hidden;
    }

    /* Sidebar */
    .cyber-sidebar {
        position: fixed;
        top: 0;
        left: 0;
        width: var(--cyber-sidebar-width);
        height: 100vh;
        background: rgba(2, 6, 12, 0.95);
        border-right: 1px solid var(--cyber-border);
        padding: 18px 16px;
        overflow-y: auto;
        backdrop-filter: blur(12px);
        z-index: 20;
    }

    .cyber-brand {
        display: flex;
        gap: 10px;
        padding: 8px 0 20px;
        border-bottom: 1px solid var(--cyber-border);
        margin-bottom: 20px;
    }

    .brand-mark {
        width: 36px;
        height: 36px;
        background: var(--cyber-cyan-dim);
        border: 1px solid var(--cyber-cyan);
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 16px;
        font-weight: 700;
        color: var(--cyber-cyan);
        letter-spacing: 0;
    }

    .brand-text {
        display: flex;
        flex-direction: column;
        gap: 2px;
    }

    .brand-name {
        font-size: 15px;
        font-weight: 700;
        letter-spacing: 0.05em;
        color: var(--cyber-text);
    }

    .brand-version {
        font-size: 11px;
        color: var(--cyber-muted);
        letter-spacing: 0.1em;
    }

    .brand-instance {
        font-size: 11px;
        color: var(--cyber-cyan);
        letter-spacing: 0.06em;
        margin-top: 2px;
    }

    .cyber-nav-section {
        margin-bottom: 16px;
        font-size: 10px;
        color: var(--cyber-muted);
        text-transform: uppercase;
        letter-spacing: 0.1em;
    }

    .cyber-nav-link {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 10px 11px;
        color: var(--cyber-muted);
        border: 1px solid transparent;
        margin: 4px 0;
        transition: all 0.15s ease;
        font-size: 13px;
        border-radius: 4px;
        text-transform: none;
        letter-spacing: 0.02em;
    }
    .nav-icon {
        width: 16px;
        text-align: center;
        color: var(--cyber-cyan);
        font-family: 'JetBrains Mono', ui-monospace, monospace;
        font-size: 12px;
        flex: 0 0 16px;
    }

    .cyber-nav-link:hover {
        color: var(--cyber-text);
        background: var(--cyber-cyan-dim);
        border-color: var(--cyber-border);
    }

    .cyber-nav-link.active {
        color: var(--cyber-cyan);
        background: var(--cyber-cyan-dim);
        border-color: var(--cyber-border-active);
    }

    .cyber-sidebar-utility {
        margin-top: 18px;
        padding-top: 12px;
        border-top: 1px solid var(--cyber-border);
        display: flex;
        flex-direction: column;
        gap: 6px;
    }

    .utility-row {
        display: grid;
        grid-template-columns: 10px minmax(0, 1fr) auto;
        gap: 8px;
        align-items: center;
        border: 1px solid rgba(0, 242, 255, 0.12);
        border-radius: 4px;
        background: rgba(3, 10, 18, 0.65);
        padding: 5px 7px;
        font-size: 10px;
        color: var(--cyber-muted);
        letter-spacing: 0.04em;
        text-transform: uppercase;
    }

    .utility-row strong {
        color: var(--cyber-text);
        font-size: 10px;
    }

    .utility-row .dot {
        width: 6px;
        height: 6px;
        border-radius: 999px;
        background: var(--cyber-cyan);
    }

    .utility-row .dot.success { background: var(--cyber-green); }
    .utility-row .dot.warn { background: var(--cyber-yellow); }
    .utility-row .dot.cyan { background: var(--cyber-cyan); }

    /* Main */
    .cyber-main {
        margin-left: var(--cyber-sidebar-width);
        width: calc(100% - var(--cyber-sidebar-width));
        flex: 1 1 auto;
        min-width: 0;
        max-width: none;
        padding: 14px;
        height: 100vh;
        overflow: auto;
        display: flex;
        flex-direction: column;
        gap: 10px;
    }

    .cyber-main > * {
        min-width: 0;
    }

    .cyber-main .mono,
    .cyber-main code,
    .cyber-main pre,
    .cyber-main .path,
    .cyber-main .log-value {
        font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
    }

    .cyber-main .button,
    .cyber-main .primary-button,
    .cyber-main .picker-button {
        border-radius: 4px;
        border: 1px solid rgba(0, 242, 255, 0.28);
        background: rgba(0, 242, 255, 0.08);
        color: #d9f5ff;
        box-shadow: none;
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.05em;
        text-transform: uppercase;
        min-height: 32px;
        padding: 6px 10px;
    }

    .cyber-main .button:hover,
    .cyber-main .primary-button:hover,
    .cyber-main .picker-button:hover {
        border-color: rgba(0, 242, 255, 0.48);
        background: rgba(0, 242, 255, 0.16);
        color: #ffffff;
    }

    .cyber-main .button.secondary {
        border-color: rgba(143, 168, 196, 0.36);
        color: #b7cde7;
        background: rgba(5, 14, 25, 0.72);
    }

    .cyber-main .button:disabled,
    .cyber-main .primary-button:disabled,
    .cyber-main .picker-button:disabled {
        opacity: 0.55;
        cursor: not-allowed;
    }

    .cyber-main .panel,
    .cyber-main .ov1-panel {
        border: 1px solid rgba(0, 242, 255, 0.2);
        border-radius: 4px;
        background: rgba(13, 28, 45, 0.9);
        min-width: 0;
    }

    .cyber-main .panel-header,
    .cyber-main .ov1-panel-header {
        border-bottom: 1px solid rgba(0, 242, 255, 0.2);
        padding: 10px 12px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 10px;
    }

    .cyber-main .panel-title,
    .cyber-main .ov1-panel-title {
        margin: 0;
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: #92f7ff;
        font-weight: 700;
    }

    .cyber-main .panel-body,
    .cyber-main .ov1-panel-body {
        padding: 10px;
        min-width: 0;
    }

    .cyber-main .status-led,
    .cyber-main .ov1-led {
        width: 8px;
        height: 8px;
        border-radius: 999px;
        background: var(--cyber-green);
        box-shadow: 0 0 12px rgba(0, 255, 159, 0.5);
        flex: 0 0 auto;
    }
    .cyber-main .status-led.warn,
    .cyber-main .ov1-led.warn {
        background: var(--cyber-yellow);
        box-shadow: 0 0 12px rgba(255, 200, 87, 0.45);
    }
    .cyber-main .status-led.danger,
    .cyber-main .ov1-led.danger {
        background: var(--cyber-red);
        box-shadow: 0 0 12px rgba(255, 95, 122, 0.45);
    }

    /* Topbar */
    .cyber-topbar {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 14px;
        width: 100%;
        min-width: 0;
        padding: 12px 14px;
        background: var(--cyber-panel);
        border: 1px solid var(--cyber-border);
        margin-bottom: 8px;
        border-radius: 4px;
        font-size: 13px;
    }

    .topbar-left, .topbar-center, .topbar-right {
        display: flex;
        align-items: center;
        gap: 16px;
    }

    .topbar-title {
        border-left: 1px solid rgba(0, 242, 255, 0.2);
        padding-left: 14px;
        color: #dff7ff;
        font-size: 13px;
        font-weight: 800;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        white-space: nowrap;
    }

    .system-status {
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .status-dot {
        width: 6px;
        height: 6px;
        background: var(--cyber-green);
        border-radius: 50%;
        animation: pulse 2s infinite;
    }

    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.4; }
    }

    .status-text {
        color: var(--cyber-green);
        font-weight: 700;
        letter-spacing: 0.05em;
    }

    .system-metric {
        display: flex;
        gap: 6px;
    }

    .metric-label {
        color: var(--cyber-muted);
        font-size: 11px;
        letter-spacing: 0.06em;
    }

    .metric-value {
        color: var(--cyber-cyan);
        font-weight: 700;
        font-size: 12px;
    }

    .system-time {
        color: var(--cyber-muted);
        font-family: ui-monospace, monospace;
    }

    .utility-icons {
        color: var(--cyber-cyan);
        letter-spacing: 0.08em;
        font-family: ui-monospace, monospace;
    }

    /* Panels */
    .cyber-panel {
        background: var(--cyber-panel);
        border: 1px solid var(--cyber-border);
        margin-bottom: 16px;
        border-radius: 4px;
        min-width: 0;
    }

    .cyber-panel-header {
        padding: 10px 14px;
        border-bottom: 1px solid var(--cyber-border);
        display: flex;
        justify-content: space-between;
        align-items: center;
    }

    .cyber-panel-title {
        font-size: 12px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.08em;
    }

    .cyber-panel-content {
        padding: 14px;
    }

    /* Badges */
    .cyber-badge {
        display: inline-block;
        padding: 3px 8px;
        font-size: 10px;
        font-weight: 600;
        letter-spacing: 0.05em;
        border: 1px solid;
    }

    .badge-success {
        background: rgba(0, 255, 157, 0.1);
        border-color: rgba(0, 255, 157, 0.3);
        color: var(--cyber-green);
    }

    .badge-warning {
        background: rgba(255, 170, 0, 0.1);
        border-color: rgba(255, 170, 0, 0.3);
        color: var(--cyber-yellow);
    }

    .badge-danger {
        background: rgba(255, 51, 102, 0.1);
        border-color: rgba(255, 51, 102, 0.3);
        color: var(--cyber-red);
    }

    .badge-info {
        background: var(--cyber-cyan-dim);
        border-color: var(--cyber-border-active);
        color: var(--cyber-cyan);
    }

    /* Buttons */
    .cyber-btn {
        display: inline-flex;
        align-items: center;
        padding: 8px 14px;
        background: var(--cyber-panel);
        border: 1px solid var(--cyber-border);
        color: var(--cyber-text);
        font-family: inherit;
        font-size: 12px;
        cursor: pointer;
        transition: all 0.15s ease;
    }

    .cyber-btn:hover {
        background: var(--cyber-cyan-dim);
        border-color: var(--cyber-cyan);
        color: var(--cyber-cyan);
    }

    .cyber-btn:active {
        background: var(--cyber-cyan);
        color: var(--cyber-bg);
    }

    /* Modal */
    .cyber-modal-overlay {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0, 0, 0, 0.85);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 9999;
        backdrop-filter: blur(4px);
        animation: fadeIn 0.2s ease;
    }

    @keyframes fadeIn {
        from { opacity: 0; }
        to { opacity: 1; }
    }

    .cyber-modal {
        width: 90%;
        max-width: 900px;
        max-height: 85vh;
        background: var(--cyber-panel);
        border: 1px solid var(--cyber-border);
        display: flex;
        flex-direction: column;
        animation: slideUp 0.2s ease;
    }

    @keyframes slideUp {
        from { transform: translateY(20px); opacity: 0; }
        to { transform: translateY(0); opacity: 1; }
    }

    .cyber-modal-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 12px 16px;
        border-bottom: 1px solid var(--cyber-border);
    }

    .cyber-modal-title {
        font-size: 13px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }

    .cyber-modal-close {
        background: none;
        border: none;
        color: var(--cyber-muted);
        cursor: pointer;
        font-size: 16px;
    }

    .cyber-modal-close:hover {
        color: var(--cyber-red);
    }

    .cyber-modal-content {
        flex: 1;
        overflow-y: auto;
        padding: 16px;
    }

    .cyber-modal-text {
        font-family: ui-monospace, monospace;
        font-size: 12px;
        line-height: 1.6;
        white-space: pre-wrap;
        word-wrap: break-word;
        color: var(--cyber-text);
    }

    .cyber-modal-footer {
        display: flex;
        gap: 10px;
        padding: 12px 16px;
        border-top: 1px solid var(--cyber-border);
        justify-content: flex-end;
    }

    /* Utility */
    .cyber-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
        gap: 16px;
    }

    .cyber-empty {
        color: var(--cyber-muted);
        font-style: italic;
    }

    /* Task Items */
    .cyber-task-item {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 8px 10px;
        border: 1px solid var(--cyber-border);
        margin-bottom: 6px;
        font-size: 12px;
    }

    .cyber-task-item:hover {
        border-color: var(--cyber-border-active);
        background: var(--cyber-cyan-dim);
    }

    .task-id {
        color: var(--cyber-muted);
        font-family: ui-monospace, monospace;
    }

    .task-name {
        flex: 1;
        color: var(--cyber-text);
    }

    /* Headings */
    .cyber-h1 { font-size: 22px; font-weight: 700; }
    .cyber-h2 { font-size: 18px; font-weight: 700; }
    .cyber-h3 { font-size: 14px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; }

    /* Pre */
    .cyber-pre {
        background: rgba(0, 0, 0, 0.4);
        border: 1px solid var(--cyber-border);
        padding: 14px;
        overflow-x: auto;
        font-family: ui-monospace, monospace;
        font-size: 12px;
        line-height: 1.6;
    }

    @media (max-width: 1200px) {
        .cyber-sidebar {
            width: 240px;
        }

        .cyber-main {
            margin-left: 240px;
            width: auto;
        }
    }

    @media (max-width: 980px) {
        .cyber-sidebar {
            position: static;
            width: 100%;
            height: auto;
            border-right: 0;
            border-bottom: 1px solid var(--cyber-border);
        }

        .cyber-main {
            margin-left: 0;
            width: 100%;
        }
    }
    """


def cyber_js() -> str:
    """Return the cyberpunk JavaScript."""
    
    return """
    function openCyberModal(modalId) {
        var overlay = document.getElementById(modalId + '-overlay');
        if (overlay) {
            overlay.style.display = 'flex';
        }
    }

    function closeCyberModal(modalId) {
        var overlay = document.getElementById(modalId + '-overlay');
        if (overlay) {
            overlay.style.display = 'none';
        }
    }

    function copyToClipboard(text) {
        navigator.clipboard.writeText(text).then(function() {
            alert('Copied to clipboard');
        }).catch(function(err) {
            console.error('Failed to copy:', err);
        });
    }

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            var overlays = document.querySelectorAll('.cyber-modal-overlay');
            overlays.forEach(function(overlay) {
                if (overlay.style.display === 'flex') {
                    overlay.style.display = 'none';
                }
            });
        }
    });
    """
