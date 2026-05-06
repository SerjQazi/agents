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
                ("control", "/control", "Control Panels"),
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
        color-scheme: dark;
        --ao-bg: #050914;
        --ao-panel: rgba(12, 21, 37, 0.74);
        --ao-panel-strong: rgba(15, 27, 44, 0.94);
        --ao-border: rgba(125, 211, 252, 0.2);
        --ao-border-strong: rgba(125, 211, 252, 0.42);
        --ao-text: #eef7ff;
        --ao-muted: #a8b7cc;
        --ao-soft: #6f8098;
        --ao-cyan: #00d4ff;
        --ao-blue: #6ecbff;
        --ao-green: #37d67a;
        --ao-danger: #ff6370;
        --ao-sidebar-width: 272px;
      }

      * { box-sizing: border-box; }

      body {
        margin: 0;
        min-height: 100vh;
        font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        background:
          radial-gradient(circle at 12% 8%, rgba(64, 224, 208, 0.17), transparent 31%),
          radial-gradient(circle at 88% 4%, rgba(106, 167, 255, 0.18), transparent 30%),
          linear-gradient(145deg, #050914 0%, #08111f 52%, #0d1728 100%);
        color: var(--ao-text);
      }

      a { color: var(--ao-blue); }

      .ao-shell {
        display: grid;
        grid-template-columns: var(--ao-sidebar-width) minmax(0, 1fr);
        min-height: 100vh;
      }

      .ao-sidebar {
        position: sticky;
        top: 0;
        height: 100vh;
        overflow-y: auto;
        padding: 20px 14px;
        border-right: 1px solid rgba(110, 203, 255, 0.16);
        background:
          linear-gradient(180deg, rgba(255, 255, 255, 0.055), rgba(255, 255, 255, 0.018)),
          rgba(5, 9, 20, 0.8);
        box-shadow: 12px 0 36px rgba(0, 0, 0, 0.18);
        backdrop-filter: blur(18px);
      }

      .ao-brand {
        display: flex;
        align-items: center;
        gap: 11px;
        padding: 4px 9px 22px;
        font-size: 19px;
        font-weight: 750;
        letter-spacing: 0;
      }

      .ao-brand-mark {
        display: inline-grid;
        place-items: center;
        width: 38px;
        height: 38px;
        border: 1px solid rgba(0, 212, 255, 0.34);
        border-radius: 8px;
        background: rgba(0, 212, 255, 0.12);
        color: var(--ao-text);
        box-shadow: 0 0 22px rgba(0, 212, 255, 0.14);
      }

      .ao-nav-section {
        display: grid;
        gap: 8px;
        padding: 14px 0;
        border-top: 1px solid rgba(110, 203, 255, 0.14);
      }

      .ao-nav-section:first-of-type { border-top: 0; padding-top: 0; }

      .ao-nav-title {
        padding: 0 10px;
        color: var(--ao-soft);
        font-size: 11px;
        font-weight: 900;
        letter-spacing: 0.08em;
      }

      .ao-nav {
        display: grid;
        gap: 6px;
      }

      .ao-nav-link {
        display: flex;
        align-items: center;
        min-height: 39px;
        padding: 9px 11px;
        border: 1px solid transparent;
        border-radius: 8px;
        color: var(--ao-muted);
        text-decoration: none;
        font-size: 14px;
        font-weight: 700;
      }

      .ao-nav-link.active,
      .ao-nav-link:hover {
        border-color: rgba(0, 212, 255, 0.26);
        background: rgba(0, 212, 255, 0.1);
        color: var(--ao-text);
        text-decoration: none;
      }

      .ao-main {
        width: min(1320px, 100%);
        min-width: 0;
        margin: 0 auto;
        padding: 24px;
      }

      .ao-topbar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
        margin-bottom: 18px;
        padding: 16px 18px;
        border: 1px solid var(--ao-border);
        border-radius: 16px;
        background:
          linear-gradient(180deg, rgba(255, 255, 255, 0.07), rgba(255, 255, 255, 0.025)),
          var(--ao-panel);
        box-shadow: 0 14px 36px rgba(0, 0, 0, 0.22);
      }

      .ao-topbar h1 {
        margin: 0;
        font-size: 24px;
        line-height: 1.15;
      }

      .ao-topbar p {
        margin: 4px 0 0;
        color: var(--ao-muted);
        font-size: 14px;
      }

      @media (max-width: 900px) {
        .ao-shell { grid-template-columns: 1fr; }
        .ao-sidebar {
          position: sticky;
          z-index: 20;
          height: auto;
          max-height: 45vh;
          border-right: 0;
          border-bottom: 1px solid rgba(110, 203, 255, 0.16);
        }
        .ao-nav-section { padding: 10px 0; }
        .ao-main { padding: 16px; }
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
