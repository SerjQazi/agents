"""Shared AgentOS HTML layout."""

from __future__ import annotations

import html


AGENTOS_BASE = "http://100.68.10.125:8080"


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def nav_url(path: str) -> str:
    return path


def sidebar_html(active: str) -> str:
    sections = [
        (
            "MAIN",
            [
                ("dashboard", "/", "Dashboard"),
                ("dashboard-v2", "/dashboard-v2", "Dashboard V2"),
                ("control", "/ops", "Control Panels"),
                ("agents", "/agents", "Agents"),
                ("logs", "/logs", "Logs"),
                ("guide", "/guide", "System Guide"),
            ],
        ),
        (
            "BUILD PIPELINE",
            [
                ("upload", "/upload", "Upload Pipeline"),
                ("planner", "/planner", "Planner Agent"),
                ("coding", "/coding", "Coding Agent"),
                ("daily", "/reports/daily", "Daily Digest"),
                ("reviews", "/reviews", "Reviews"),
                ("staging", "/staging", "Staging"),
            ],
        ),
        (
            "TOOLS",
            [
                ("ops", "/ops", "Ops Cheat Sheet"),
                ("commands", "/commands", "Commands"),
                ("settings", "/settings", "Settings"),
                ("aimemory", "/aimemory", "AI Memory"),
            ],
        ),
    ]
    parts = ['<aside class="ao-sidebar" aria-label="AgentOS navigation">']
    parts.append('<div class="ao-brand"><span class="ao-brand-mark">AO</span><span>AgentOS</span></div>')
    for title, items in sections:
        parts.append(f'<div class="ao-nav-section"><div class="ao-nav-title">{esc(title)}</div><nav class="ao-nav">')
        for key, path, label in items:
            class_name = "ao-nav-link active" if key == active else "ao-nav-link"
            parts.append(f'<a class="{class_name}" href="{esc(nav_url(path))}"><span>{esc(label)}</span></a>')
        parts.append("</nav></div>")
    parts.append("</aside>")
    return "".join(parts)


def layout_css() -> str:
    return """
      :root {
        --ao-bg: #050914;
        --ao-panel: rgba(12, 21, 37, 0.74);
        --ao-panel-strong: rgba(15, 27, 44, 0.94);
        --ao-border: rgba(125, 211, 252, 0.16); /* Softer border */
        --ao-border-strong: rgba(125, 211, 252, 0.3);
        --ao-text: #eef7ff;
        --ao-muted: #a8b7cc;
        --ao-soft: #8a9bb3; /* Slightly brighter soft text */
        --ao-cyan: #00d4ff;
        --ao-blue: #6ecbff;
        --ao-green: #37d67a;
        --ao-danger: #ff6370;
        --ao-sidebar-width: 280px; /* Slightly wider sidebar */

        /* New Variables for Consistency */
        --ao-radius-sm: 6px;
        --ao-radius-md: 10px;
        --ao-radius-lg: 16px;
        --ao-spacing-sm: 8px;
        --ao-spacing-md: 16px;
        --ao-spacing-lg: 24px;
        --ao-transition: all 0.2s ease-out;

        color-scheme: dark;
      }

      * {
        box-sizing: border-box;
        margin: 0;
        padding: 0;
      }

      body {
        min-height: 100vh;
        font-family: 'Inter', system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        font-size: 15px; /* Slightly larger base font */
        line-height: 1.6;
        background:
          radial-gradient(circle at 12% 8%, rgba(64, 224, 208, 0.1), transparent 31%),
          radial-gradient(circle at 88% 4%, rgba(106, 167, 255, 0.12), transparent 30%),
          linear-gradient(145deg, #050914 0%, #08111f 52%, #0d1728 100%);
        color: var(--ao-text);
      }

      a {
        color: var(--ao-blue);
        text-decoration: none;
        transition: var(--ao-transition);
      }
      a:hover {
        color: var(--ao-cyan);
      }

      /* General Layout */
      .ao-shell {
        display: grid;
        grid-template-columns: var(--ao-sidebar-width) minmax(0, 1fr);
        min-height: 100vh;
      }

      /* Sidebar */
      .ao-sidebar {
        position: sticky;
        top: 0;
        height: 100vh;
        overflow-y: auto;
        padding: var(--ao-spacing-md) var(--ao-spacing-sm);
        border-right: 1px solid rgba(110, 203, 255, 0.12); /* Softer border */
        background:
          linear-gradient(180deg, rgba(255, 255, 255, 0.04), rgba(255, 255, 255, 0.015)), /* Softer gradient */
          rgba(5, 9, 20, 0.85); /* Slightly less opaque */
        box-shadow: 8px 0 24px rgba(0, 0, 0, 0.15); /* Softer shadow */
        backdrop-filter: blur(16px); /* Slightly less blur */
      }

      .ao-brand {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: var(--ao-spacing-sm) var(--ao-spacing-sm) var(--ao-spacing-lg);
        font-size: 20px; /* Slightly larger brand text */
        font-weight: 800; /* Bolder */
        letter-spacing: -0.02em;
        color: var(--ao-text);
      }

      .ao-brand-mark {
        width: 36px;
        height: 36px;
        border: 1px solid rgba(0, 212, 255, 0.28); /* Softer border */
        border-radius: var(--ao-radius-sm); /* Sharper corners */
        background: rgba(0, 212, 255, 0.1); /* Softer background */
        box-shadow: 0 0 16px rgba(0, 212, 255, 0.1); /* Softer glow */
        font-size: 18px;
      }

      .ao-nav-section {
        display: grid;
        gap: var(--ao-spacing-sm);
        padding: var(--ao-spacing-md) 0;
        border-top: 1px solid rgba(110, 203, 255, 0.1); /* Lighter border */
      }
      .ao-nav-section:first-of-type {
        border-top: 0;
        padding-top: 0;
      }

      .ao-nav-title {
        padding: 0 var(--ao-spacing-sm);
        color: var(--ao-soft);
        font-size: 11px;
        font-weight: 900;
        letter-spacing: 0.1em; /* Increased letter spacing */
        text-transform: uppercase;
        margin-bottom: 4px; /* Added spacing below title */
      }

      .ao-nav {
        display: grid;
        gap: 4px; /* Tighter spacing for nav items */
      }

      .ao-nav-link {
        display: flex;
        align-items: center;
        min-height: 42px; /* Taller nav items */
        padding: 9px var(--ao-spacing-sm);
        border: 1px solid transparent;
        border-radius: var(--ao-radius-sm);
        color: var(--ao-muted);
        font-size: 14px;
        font-weight: 600; /* Medium bold */
        position: relative;
        transition: var(--ao-transition);
      }
      .ao-nav-link:hover {
        background: rgba(0, 212, 255, 0.06); /* Softer hover */
        border-color: rgba(0, 212, 255, 0.15);
        color: var(--ao-text);
      }
      .ao-nav-link.active {
        background: rgba(0, 212, 255, 0.15); /* Stronger active background */
        border-color: rgba(0, 212, 255, 0.3); /* Stronger active border */
        color: var(--ao-cyan); /* Active color */
        font-weight: 700;
      }
      .ao-nav-link.active::before { /* Active indicator bar */
        content: '';
        position: absolute;
        left: 0;
        top: 50%;
        transform: translateY(-50%);
        width: 3px;
        height: 70%;
        background: var(--ao-cyan);
        border-radius: 0 3px 3px 0;
      }

      /* Main Content Area */
      .ao-main {
        width: min(1440px, 100%); /* Wider main content */
        min-width: 0;
        margin: 0 auto;
        padding: var(--ao-spacing-lg); /* Consistent padding */
      }

      .ao-topbar {
        gap: var(--ao-spacing-md);
        margin-bottom: var(--ao-spacing-lg); /* More spacing below topbar */
        padding: var(--ao-spacing-md) var(--ao-spacing-lg);
        border: 1px solid var(--ao-border-strong); /* Stronger border */
        border-radius: var(--ao-radius-lg);
        background:
          linear-gradient(180deg, rgba(255, 255, 255, 0.08), rgba(255, 255, 255, 0.03)),
          var(--ao-panel-strong); /* Stronger panel background */
        box-shadow: 0 18px 48px rgba(0, 0, 0, 0.25); /* More pronounced shadow */
      }
      .ao-topbar h1 {
        font-size: 26px; /* Larger title */
        line-height: 1.2;
        font-weight: 700;
      }
      .home-badge {
        display: inline-block;
        margin-left: 12px;
        padding: 3px 10px;
        border: 1px solid rgba(55, 214, 122, 0.32);
        border-radius: 999px;
        background: rgba(21, 128, 61, 0.14);
        color: var(--ao-green);
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.04em;
        vertical-align: middle;
      }
      .ao-topbar p {
        margin-top: 6px; /* More spacing below title */
        color: var(--ao-muted);
        font-size: 14px;
        line-height: 1.5;
      }

      /* General Card Styling */
      .ao-panel,
      .ao-card,
      .index-card, /* Existing card classes */
      .upload-card,
      .progress-card,
      .result-card,
      .safety-checklist,
      .memory-panel /* New generic panel class for consistency */
      {
        border: 1px solid var(--ao-border);
        border-radius: var(--ao-radius-lg);
        background:
          linear-gradient(180deg, rgba(255, 255, 255, 0.03), transparent), /* Subtle top highlight */
          var(--ao-panel);
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12); /* Lighter shadow for general cards */
        margin-bottom: var(--ao-spacing-lg); /* Consistent bottom margin */
        padding: var(--ao-spacing-lg); /* Consistent padding inside cards */
        transition: var(--ao-transition);
        position: relative; /* For inner glow effects */
      }

      .ao-panel:hover, .ao-card:hover {
        box-shadow: 0 12px 32px rgba(0, 0, 0, 0.18); /* Slightly more pronounced hover shadow */
      }

      .card-title-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: var(--ao-spacing-md);
        margin-bottom: var(--ao-spacing-sm);
      }
      .card-title-row h2 {
        font-size: 19px;
        font-weight: 700;
        line-height: 1.3;
        color: var(--ao-text);
      }
      .index-card h2 { font-size: 18px; } /* Slightly smaller for index cards */

      /* Typography adjustments */
      h1, h2, h3, h4, h5, h6 {
        color: var(--ao-text);
        font-weight: 700;
        line-height: 1.3;
      }
      p {
        color: var(--ao-muted);
        line-height: 1.6;
        margin-bottom: var(--ao-spacing-sm);
      }
      p:last-child { margin-bottom: 0; }
      .subtle-id {
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
        font-size: 13px;
        color: var(--ao-soft);
        margin-top: 6px;
      }

      /* Buttons & Badges */
      .button, .primary-button, .picker-button {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 40px;
        padding: 9px 16px;
        border-radius: var(--ao-radius-sm);
        font-weight: 600;
        font-size: 14px;
        transition: var(--ao-transition);
        text-decoration: none;
      }
      .button {
        border: 1px solid var(--ao-border-strong);
        background: rgba(16, 36, 58, 0.7); /* Darker background for default button */
        color: var(--ao-text);
      }
      .button:hover {
        background: rgba(16, 36, 58, 0.9);
        border-color: var(--ao-cyan);
        box-shadow: 0 0 8px rgba(0, 212, 255, 0.15);
      }
      .primary-button {
        border: 1px solid var(--ao-blue);
        background: linear-gradient(180deg, var(--ao-blue), #1d4ed8);
        color: #fff;
      }
      .primary-button:hover {
        background: linear-gradient(180deg, var(--ao-cyan), #0f3e9c);
        border-color: var(--ao-cyan);
        box-shadow: 0 0 10px rgba(0, 212, 255, 0.2);
      }
      .secondary-button {
        border: 1px solid var(--ao-border);
        background: var(--ao-panel);
        color: var(--ao-muted);
      }
      .secondary-button:hover {
        border-color: var(--ao-blue);
        color: var(--ao-text);
      }

      .safety-pill, .status-pill {
        white-space: nowrap;
        border: 1px solid rgba(94, 234, 212, 0.35);
        border-radius: 999px;
        color: #5eead4;
        background: rgba(20, 184, 166, 0.1);
        padding: 5px 10px;
        font-size: 12px;
        font-weight: 800;
        text-transform: uppercase;
      }
      .status-pill.red {
        border-color: rgba(255, 99, 112, 0.35);
        color: #ff6370;
        background: rgba(255, 99, 112, 0.1);
      }
      .status-pill.yellow {
        border-color: rgba(251, 191, 36, 0.35);
        color: #fbbf24;
        background: rgba(251, 191, 36, 0.1);
      }

      /* Upload Pipeline Specific */
      .upload-head, .safety-head { padding: var(--ao-spacing-md) var(--ao-spacing-lg); }
      .upload-head h2, .safety-head h2 { font-size: 20px; }
      .safety-grid { gap: var(--ao-spacing-md); padding: var(--ao-spacing-md) var(--ao-spacing-lg); }

      .drop-zone {
        min-height: 200px;
        border: 2px dashed rgba(125, 211, 252, 0.2); /* Softer dashed border */
        border-radius: var(--ao-radius-md);
        background: rgba(5, 12, 24, 0.4); /* Softer background */
        gap: var(--ao-spacing-sm);
        padding: var(--ao-spacing-lg);
      }
      .drop-zone strong { font-size: 18px; }
      .drop-zone.dragging {
        border-color: var(--ao-cyan);
        background: rgba(0, 212, 255, 0.08);
      }
      .drop-icon {
        width: 40px;
        height: 40px;
        border: 1px solid rgba(125, 211, 252, 0.2);
        color: var(--ao-blue);
        font-size: 24px;
      }

      .picker-row { margin-top: var(--ao-spacing-md); }
      .file-list {
        margin-top: var(--ao-spacing-md);
        font-size: 14px;
        color: var(--ao-muted);
      }

      .progress-card {
        padding: var(--ao-spacing-lg);
        display: grid;
        gap: var(--ao-spacing-md);
      }
      .step {
        gap: var(--ao-spacing-md);
        border: 1px solid var(--ao-border);
        border-radius: var(--ao-radius-md);
        padding: var(--ao-spacing-md);
        background: var(--ao-panel);
      }
      .step strong { font-size: 15px; }
      .step p { font-size: 13px; margin-top: 2px; }
      .step span {
        width: 28px;
        height: 28px;
        border: 1px solid var(--ao-border-strong);
        color: var(--ao-muted);
        font-weight: 700;
        font-size: 14px;
        line-height: 1; /* Center text vertically */
        border-radius: 50%;
        flex-shrink: 0;
      }
      .step span::after { content: ''; background: transparent; } /* Remove default dot */

      .step.uploaded span::after { content: '⇧'; } /* Upload icon */
      .step.scanning span::after { content: '🔎'; } /* Scan icon */
      .step.planning span::after { content: '🧠'; } /* Plan icon */
      .step.staging span::after { content: '📦'; } /* Staging icon */
      .step.reviewing span::after { content: '📋'; } /* Review icon */
      .step.ready span::after { content: '✅'; } /* Ready icon */

      .step.done span {
        background: rgba(20, 184, 166, 0.18);
        border-color: rgba(94, 234, 212, 0.55);
        color: #5eead4;
      }
      .step.done span::after { content: '✓'; } /* Checkmark for done */
      .step.active span {
        border-color: var(--ao-cyan);
        box-shadow: 0 0 10px rgba(0, 212, 255, 0.2);
        color: var(--ao-cyan);
      }
      .step.failed span {
        border-color: var(--ao-danger);
        color: var(--ao-danger);
      }
      .step.failed span::after { content: '✕'; } /* Cross for failed */


      /* Empty State */
      .empty-state {
        text-align: center;
        padding: var(--ao-spacing-lg) 0;
        margin-bottom: var(--ao-spacing-lg);
        border: 1px dashed var(--ao-border);
        border-radius: var(--ao-radius-lg);
        background: rgba(5, 12, 24, 0.3);
      }
      .empty-state h2 {
        font-size: 20px;
        color: var(--ao-muted);
        margin-bottom: var(--ao-spacing-sm);
      }
      .empty-state p {
        font-size: 14px;
        color: var(--ao-soft);
      }
      .empty-state .index-actions {
        margin-top: var(--ao-spacing-md);
        justify-content: center;
      }

      /* Reports and Preformatted Text */
      .report-view pre,
      pre {
        white-space: pre-wrap;
        word-break: break-all;
        background: var(--ao-panel-strong);
        border: 1px solid var(--ao-border-strong);
        border-radius: var(--ao-radius-sm);
        padding: var(--ao-spacing-md);
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
        font-size: 13px;
        line-height: 1.5;
        max-height: 500px; /* Max height for scrollable code blocks */
        overflow-y: auto;
      }
      .report-view code,
      code {
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
        background: rgba(125, 211, 252, 0.08);
        border-radius: 3px;
        padding: 2px 4px;
        font-size: 0.85em;
      }

      /* AI Ecosystem and Memory place holders */
      .ai-ecosystem-grid, .ai-memory-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
        gap: var(--ao-spacing-md);
        margin-top: var(--ao-spacing-md);
      }
      .ai-agent-card {
        border: 1px solid var(--ao-border);
        border-radius: var(--ao-radius-lg);
        background: var(--ao-panel);
        padding: var(--ao-spacing-md);
        box-shadow: 0 4px 16px rgba(0,0,0,0.08);
        transition: var(--ao-transition);
      }
      .ai-agent-card:hover {
        box-shadow: 0 8px 24px rgba(0,0,0,0.12);
        border-color: var(--ao-blue);
      }
      .ai-agent-card h3 {
        font-size: 17px;
        margin-bottom: var(--ao-spacing-sm);
        color: var(--ao-cyan);
      }
      .ai-agent-card .role {
        font-size: 13px;
        color: var(--ao-muted);
        margin-bottom: var(--ao-spacing-sm);
      }
      .ai-agent-card .status {
        font-size: 12px;
        color: var(--ao-soft);
        display: flex;
        align-items: center;
        gap: 5px;
      }
      .ai-agent-card .status::before {
        content: '●';
        font-size: 1.2em;
        line-height: 0;
        color: var(--ao-green); /* Default for online */
      }
      .ai-agent-card.offline .status::before { color: var(--ao-danger); }
      .ai-agent-card.unknown .status::before { color: var(--ao-soft); }

      /* Media Queries */
      @media (max-width: 900px) {
        .ao-shell { grid-template-columns: 1fr; }
        .ao-sidebar {
          position: relative; /* Not sticky on mobile */
          height: auto;
          max-height: 60vh; /* Allow scrolling on smaller screens */
          border-right: 0;
          border-bottom: 1px solid rgba(110, 203, 255, 0.1);
          box-shadow: none;
          padding: var(--ao-spacing-md);
        }
        .ao-main { padding: var(--ao-spacing-md); }
        .ao-topbar { margin-bottom: var(--ao-spacing-md); padding: var(--ao-spacing-sm) var(--ao-spacing-md); }
        .ao-topbar h1 { font-size: 22px; }
        .ao-topbar p { font-size: 13px; }
        .ao-nav-section { padding: var(--ao-spacing-sm) 0; }
        .ao-nav-title { font-size: 10px; }
        .ao-nav-link { min-height: 38px; font-size: 13px; }
        .ao-panel, .ao-card, .index-card { padding: var(--ao-spacing-md); }
        .safety-head, .upload-head { flex-direction: column; align-items: flex-start; padding: var(--ao-spacing-md); }
        .safety-pill { margin-top: var(--ao-spacing-sm); }
        .safety-grid { grid-template-columns: 1fr; padding: var(--ao-spacing-md); }
        .drop-zone strong { font-size: 16px; }
        .picker-row { flex-direction: column; align-items: stretch; }
        .picker-button, .primary-button { width: 100%; }
        .progress-card { padding: var(--ao-spacing-md); }
        .step { padding: var(--ao-spacing-sm); gap: var(--ao-spacing-sm); }
        .step strong { font-size: 14px; }
        .step p { font-size: 12px; }
        .ai-ecosystem-grid, .ai-memory-grid { grid-template-columns: 1fr; }
      }
    """


def render_layout(title: str, active: str, content: str, extra_css: str = "", script: str = "", subtitle: str = "") -> str:
    topbar = ""
    if title or subtitle:
        subtitle_html = f"<p>{esc(subtitle)}</p>" if subtitle else ""
        topbar = f'<header class="ao-topbar"><div><h1>{esc(title)}</h1>{subtitle_html}</div></header>'
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title or "AgentOS")}</title>
  <style>
    {layout_css()}
    {extra_css}
  </style>
</head>
<body>
  <div class="ao-shell">
    {sidebar_html(active)}
    <main class="ao-main">
      {topbar}
      {content}
    </main>
  </div>
  {script}
</body>
</html>"""


def render_cyber_layout(
    title: str,
    active: str,
    content: str,
    extra_css: str = "",
    script: str = "",
    topbar_stats: dict[str, object] | None = None,
) -> str:
    """Render cyberpunk FiveM AI IDE layout."""
    try:
        from apps.orchestrator_v1_helpers import cyber_layout_css, cyber_js, render_sidebar, render_topbar
        sidebar = render_sidebar(active)
        topbar = render_topbar(topbar_stats or {})
        # Cyber routes intentionally avoid legacy AgentOS shell CSS so blueprint layout
        # structure and spacing remain consistent across Mission Control/Upload/Review/Logs.
        css = cyber_layout_css() + extra_css
        script_block = f"<script>{cyber_js()}</script>{script}"
    except ImportError:
        sidebar = sidebar_html(active)
        topbar = f'<header class="ao-topbar"><div><h1>{esc(title)}</h1></header>'
        css = layout_css() + extra_css
        script_block = script
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)} | ORCHESTRATOR_V1</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;600;700&display=swap" rel="stylesheet">
  <style>
    {css}
  </style>
</head>
<body>
  <div class="cyber-shell">
    {sidebar}
    <main class="cyber-main">
      {topbar}
      {content}
    </main>
  </div>
  {script_block}
</body>
</html>"""
