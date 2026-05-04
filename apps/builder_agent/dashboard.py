"""Small read-only HTML dashboard renderer."""

from __future__ import annotations

import html
import json
from typing import Any

from .config import BuilderConfig


def render_dashboard(config: BuilderConfig, data: dict[str, list[dict[str, Any]]]) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light dark">
  <title>Builder Agent</title>
  <style>
    :root {{
      --bg: #f4f7fb;
      --bg-soft: #edf2f7;
      --surface: #ffffff;
      --surface-2: #f8fafc;
      --text: #172033;
      --muted: #667085;
      --line: #d9e2ec;
      --line-soft: #e8eef5;
      --accent: #0ea5e9;
      --accent-strong: #2563eb;
      --accent-soft: #e0f2fe;
      --accent-glow: rgba(14, 165, 233, 0.18);
      --good: #0f766e;
      --warn: #b45309;
      --bad: #b42318;
      --shadow: 0 18px 48px rgba(15, 23, 42, 0.08);
      color-scheme: light;
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        --bg: #08111f;
        --bg-soft: #0d1b2e;
        --surface: #111c2d;
        --surface-2: #0c1727;
        --text: #edf5ff;
        --muted: #9fb1c7;
        --line: #22344c;
        --line-soft: #1a2a40;
        --accent: #38bdf8;
        --accent-strong: #60a5fa;
        --accent-soft: rgba(56, 189, 248, 0.14);
        --accent-glow: rgba(56, 189, 248, 0.2);
        --good: #5eead4;
        --warn: #fbbf24;
        --bad: #fb7185;
        --shadow: 0 20px 56px rgba(0, 0, 0, 0.35);
        color-scheme: dark;
      }}
    }}
    html[data-theme="light"] {{
      --bg: #f4f7fb;
      --bg-soft: #edf2f7;
      --surface: #ffffff;
      --surface-2: #f8fafc;
      --text: #172033;
      --muted: #667085;
      --line: #d9e2ec;
      --line-soft: #e8eef5;
      --accent: #0ea5e9;
      --accent-strong: #2563eb;
      --accent-soft: #e0f2fe;
      --accent-glow: rgba(14, 165, 233, 0.18);
      --good: #0f766e;
      --warn: #b45309;
      --bad: #b42318;
      --shadow: 0 18px 48px rgba(15, 23, 42, 0.08);
      color-scheme: light;
    }}
    html[data-theme="dark"] {{
      --bg: #08111f;
      --bg-soft: #0d1b2e;
      --surface: #111c2d;
      --surface-2: #0c1727;
      --text: #edf5ff;
      --muted: #9fb1c7;
      --line: #22344c;
      --line-soft: #1a2a40;
      --accent: #38bdf8;
      --accent-strong: #60a5fa;
      --accent-soft: rgba(56, 189, 248, 0.14);
      --accent-glow: rgba(56, 189, 248, 0.2);
      --good: #5eead4;
      --warn: #fbbf24;
      --bad: #fb7185;
      --shadow: 0 20px 56px rgba(0, 0, 0, 0.35);
      color-scheme: dark;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
      background:
        radial-gradient(circle at top left, var(--accent-soft), transparent 30rem),
        linear-gradient(180deg, var(--bg-soft), var(--bg));
      color: var(--text);
      min-height: 100vh;
    }}
    header {{
      position: sticky;
      top: 0;
      z-index: 10;
      border-bottom: 1px solid var(--line);
      background: color-mix(in srgb, var(--surface) 88%, transparent);
      backdrop-filter: blur(16px);
    }}
    .topbar {{
      max-width: 1320px;
      margin: 0 auto;
      padding: 18px 22px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }}
    main {{ max-width: 1240px; margin: 0 auto; padding: 26px; }}
    h1 {{ font-size: clamp(22px, 3vw, 30px); line-height: 1.1; margin: 0 0 6px; letter-spacing: 0; }}
    h2 {{ font-size: 16px; line-height: 1.2; margin: 0; letter-spacing: 0; }}
    .meta {{ color: var(--muted); font-size: 14px; line-height: 1.5; }}
    .header-actions {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; justify-content: flex-end; }}
    .pill {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 30px;
      padding: 5px 10px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: linear-gradient(180deg, var(--surface-2), color-mix(in srgb, var(--surface-2) 72%, var(--accent-soft)));
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
      box-shadow: 0 8px 24px color-mix(in srgb, var(--accent-glow) 45%, transparent);
    }}
    .theme-toggle {{
      display: inline-flex;
      padding: 3px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: var(--surface-2);
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
    }}
    .theme-toggle button, .actions button {{
      appearance: none;
      border: 0;
      border-radius: 999px;
      background: transparent;
      color: var(--muted);
      cursor: pointer;
      font: inherit;
      font-size: 12px;
      font-weight: 800;
      min-height: 30px;
      padding: 6px 11px;
      transition: background 150ms ease, color 150ms ease, box-shadow 150ms ease, transform 150ms ease;
    }}
    a {{ color: var(--accent-strong); font-weight: 750; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .theme-toggle button[aria-pressed="true"] {{
      background: var(--accent);
      color: #00111f;
      box-shadow: 0 8px 18px color-mix(in srgb, var(--accent) 24%, transparent);
    }}
    .theme-toggle button:hover:not([aria-pressed="true"]) {{ color: var(--text); background: color-mix(in srgb, var(--accent-soft) 62%, transparent); }}
    .grid {{ display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 20px; }}
    .panel {{
      min-width: 0;
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 96%, transparent), color-mix(in srgb, var(--surface) 90%, var(--surface-2))),
        var(--surface);
      border: 1px solid var(--line);
      border-radius: 10px;
      box-shadow: var(--shadow);
      overflow: hidden;
    }}
    .intro {{
      position: relative;
      padding: 18px;
      background:
        radial-gradient(circle at top right, var(--accent-glow), transparent 18rem),
        linear-gradient(135deg, color-mix(in srgb, var(--surface) 92%, var(--accent-soft)), var(--surface));
    }}
    .intro::before {{
      content: "";
      position: absolute;
      inset: 0;
      border-top: 1px solid color-mix(in srgb, var(--accent) 38%, transparent);
      pointer-events: none;
    }}
    .intro-content {{ position: relative; display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 16px; align-items: center; }}
    .intro h2 {{ font-size: clamp(20px, 2.4vw, 28px); margin-bottom: 8px; }}
    .intro p {{ max-width: 820px; margin: 0; color: var(--muted); font-size: 15px; line-height: 1.6; }}
    .intro-mark {{
      display: grid;
      place-items: center;
      width: 56px;
      height: 56px;
      border-radius: 16px;
      background: linear-gradient(135deg, var(--accent), var(--accent-strong));
      color: #00111f;
      font-size: 28px;
      box-shadow: 0 18px 38px var(--accent-glow);
    }}
    .panel.wide {{ grid-column: 1 / -1; }}
    .panel.standard {{ grid-column: span 6; }}
    .panel-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 17px 18px;
      border-bottom: 1px solid var(--line-soft);
      background: linear-gradient(180deg, color-mix(in srgb, var(--surface-2) 86%, transparent), transparent);
    }}
    .title-with-icon {{ display: inline-flex; align-items: center; gap: 8px; min-width: 0; }}
    .title-icon {{ font-size: 18px; line-height: 1; }}
    .count {{ color: var(--muted); font-size: 12px; font-weight: 800; }}
    .panel-body {{ padding: 0; min-width: 0; }}
    .form-body {{ padding: 18px; }}
    .task-form {{ display: grid; gap: 14px; }}
    .form-grid {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(220px, 360px); gap: 14px; }}
    label {{ display: grid; gap: 7px; color: var(--muted); font-size: 12px; font-weight: 850; text-transform: uppercase; letter-spacing: 0.04em; }}
    textarea, input {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface-2);
      color: var(--text);
      font: inherit;
      font-size: 14px;
      line-height: 1.45;
      padding: 11px 12px;
      outline: none;
    }}
    textarea {{ min-height: 118px; resize: vertical; }}
    textarea:focus, input:focus {{ border-color: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent); }}
    input[readonly] {{ color: var(--muted); }}
    .submit-row {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }}
    .submit-row button {{
      appearance: none;
      border: 1px solid color-mix(in srgb, var(--accent) 55%, var(--line));
      border-radius: 8px;
      background: linear-gradient(180deg, var(--accent), var(--accent-strong));
      color: #00111f;
      cursor: pointer;
      font: inherit;
      font-size: 14px;
      font-weight: 900;
      min-height: 40px;
      padding: 9px 14px;
      box-shadow: 0 12px 24px color-mix(in srgb, var(--accent) 22%, transparent);
      transition: transform 150ms ease, box-shadow 150ms ease, filter 150ms ease;
    }}
    .submit-row button:hover:not(:disabled) {{
      transform: translateY(-1px);
      filter: saturate(1.08);
      box-shadow: 0 16px 32px color-mix(in srgb, var(--accent) 28%, transparent);
    }}
    .submit-row button:disabled {{ cursor: wait; opacity: 0.7; }}
    .form-note {{ color: var(--muted); font-size: 13px; line-height: 1.45; }}
    .form-status {{ color: var(--muted); font-size: 13px; font-weight: 750; min-height: 20px; }}
    .form-status.ok {{ color: var(--good); }}
    .form-status.error {{ color: var(--bad); }}
    .table-wrap {{ width: 100%; max-width: 100%; overflow-x: auto; overscroll-behavior-x: contain; }}
    table {{ width: 100%; min-width: 720px; border-collapse: collapse; font-size: 14px; table-layout: auto; }}
    .tasks-table {{ min-width: 760px; }}
    .compact-table {{ min-width: 680px; }}
    .services-table {{ min-width: 840px; }}
    .paths-table {{ min-width: 0; }}
    th, td {{
      text-align: left;
      border-bottom: 1px solid var(--line-soft);
      padding: 12px 14px;
      vertical-align: top;
    }}
    th {{
      position: sticky;
      top: 0;
      background: var(--surface);
      color: var(--muted);
      font-size: 11px;
      font-weight: 900;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      white-space: nowrap;
    }}
    tr:last-child td {{ border-bottom: 0; }}
    td {{ overflow-wrap: normal; word-break: normal; line-height: 1.45; }}
    .cell-id, .nowrap {{ white-space: nowrap; overflow-wrap: normal; word-break: normal; }}
    .cell-text {{ max-width: 34rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .cell-small {{ max-width: 18rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .button-link {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 30px;
      padding: 5px 10px;
      border: 1px solid color-mix(in srgb, var(--accent) 42%, var(--line));
      border-radius: 7px;
      background: var(--accent-soft);
      color: var(--accent-strong);
      font-size: 12px;
      font-weight: 900;
      white-space: nowrap;
    }}
    .button-link:hover {{ text-decoration: none; background: color-mix(in srgb, var(--accent-soft) 62%, var(--surface)); }}
    code {{
      display: inline-block;
      max-width: 100%;
      background: var(--surface-2);
      border: 1px solid var(--line-soft);
      color: var(--text);
      padding: 3px 6px;
      border-radius: 6px;
      overflow-wrap: anywhere;
    }}
    .cell-muted {{ color: var(--muted); }}
    .badge {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 24px;
      padding: 3px 8px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: var(--surface-2);
      color: var(--muted);
      font-size: 12px;
      font-weight: 850;
      white-space: nowrap;
    }}
    .badge.active, .badge.info {{ color: var(--accent-strong); background: var(--accent-soft); border-color: color-mix(in srgb, var(--accent) 35%, var(--line)); }}
    .badge.completed, .badge.ok, .badge.running, .badge.enabled, .badge.passed {{ color: var(--good); background: color-mix(in srgb, var(--good) 13%, transparent); border-color: color-mix(in srgb, var(--good) 30%, var(--line)); }}
    .badge.warning, .badge.medium, .badge.blocked-review, .badge.inactive, .badge.disabled, .badge.not-seen, .badge.unknown, .badge.not-checked {{ color: var(--warn); background: color-mix(in srgb, var(--warn) 13%, transparent); border-color: color-mix(in srgb, var(--warn) 28%, var(--line)); }}
    .badge.error, .badge.failed, .badge.high, .badge.not-found, .badge.unreachable, .badge.unhealthy {{ color: var(--bad); background: color-mix(in srgb, var(--bad) 12%, transparent); border-color: color-mix(in srgb, var(--bad) 30%, var(--line)); }}
    .badge.reachable {{ color: var(--good); background: color-mix(in srgb, var(--good) 13%, transparent); border-color: color-mix(in srgb, var(--good) 30%, var(--line)); }}
    .actions {{ margin: 14px 16px 16px; display: flex; gap: 8px; flex-wrap: wrap; }}
    .actions button {{
      border: 1px solid var(--line);
      border-radius: 7px;
      color: var(--muted);
      background: var(--surface-2);
      cursor: not-allowed;
      opacity: 0.82;
    }}
    .actions button:hover {{ background: color-mix(in srgb, var(--surface-2) 80%, var(--accent-soft)); }}
    .control-row {{ display: flex; gap: 10px; flex-wrap: wrap; padding: 16px; }}
    .control-row button, .control-row a {{
      appearance: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 38px;
      padding: 8px 12px;
      border-radius: 8px;
      border: 1px solid var(--line);
      background: var(--surface-2);
      color: var(--text);
      font: inherit;
      font-size: 13px;
      font-weight: 850;
      cursor: pointer;
      text-decoration: none;
    }}
    .control-row button:hover, .control-row a:hover {{ background: color-mix(in srgb, var(--surface-2) 78%, var(--accent-soft)); text-decoration: none; }}
    .control-row .primary {{ border-color: color-mix(in srgb, var(--accent) 55%, var(--line)); background: linear-gradient(180deg, var(--accent), var(--accent-strong)); color: #00111f; }}
    .control-row .danger {{ color: var(--bad); }}
    .control-row button:disabled {{ cursor: not-allowed; opacity: 0.62; }}
    .detail-body {{ padding: 16px; display: grid; gap: 14px; }}
    .detail-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; }}
    .note-box {{ border: 1px solid var(--line-soft); border-radius: 8px; background: var(--surface-2); padding: 12px; }}
    .note-box h3 {{ margin: 0 0 8px; font-size: 14px; }}
    pre.diff {{
      margin: 0;
      max-height: 460px;
      overflow: auto;
      white-space: pre;
      border: 1px solid var(--line-soft);
      border-radius: 8px;
      background: var(--surface-2);
      color: var(--text);
      padding: 12px;
      font-size: 12px;
      line-height: 1.45;
    }}
    .empty-state {{
      display: grid;
      gap: 6px;
      padding: 18px;
      color: var(--muted);
      line-height: 1.45;
    }}
    .empty-state strong {{ color: var(--text); font-size: 14px; }}
    details.memory-details {{ grid-column: 1 / -1; }}
    details.memory-details summary {{
      cursor: pointer;
      list-style: none;
    }}
    details.memory-details summary::-webkit-details-marker {{ display: none; }}
    @media (max-width: 920px) {{
      .panel.standard {{ grid-column: 1 / -1; }}
      .topbar {{ align-items: flex-start; flex-direction: column; }}
      .header-actions {{ justify-content: flex-start; }}
    }}
    @media (max-width: 640px) {{
      main {{ padding: 14px; }}
      .topbar {{ padding: 14px; }}
      .grid {{ gap: 12px; }}
      .panel-header {{ padding: 13px 14px; }}
      th, td {{ padding: 9px 10px; }}
      table {{ min-width: 640px; }}
      .paths-table {{ min-width: 520px; }}
      .theme-toggle {{ width: 100%; }}
      .theme-toggle button {{ flex: 1; }}
      .intro-content {{ grid-template-columns: 1fr; }}
      .intro-mark {{ width: 48px; height: 48px; font-size: 24px; }}
      .form-grid {{ grid-template-columns: 1fr; }}
      .submit-row {{ align-items: stretch; flex-direction: column; }}
      .submit-row button {{ width: 100%; }}
    }}
  </style>
  <script>
    (function () {{
      var saved = localStorage.getItem("builder-agent-theme") || "system";
      if (saved === "light" || saved === "dark") {{
        document.documentElement.dataset.theme = saved;
      }}
      window.setBuilderTheme = function (theme) {{
        localStorage.setItem("builder-agent-theme", theme);
        if (theme === "system") {{
          delete document.documentElement.dataset.theme;
        }} else {{
          document.documentElement.dataset.theme = theme;
        }}
        document.querySelectorAll("[data-theme-choice]").forEach(function (button) {{
          button.setAttribute("aria-pressed", button.dataset.themeChoice === theme ? "true" : "false");
        }});
      }};
      window.addEventListener("DOMContentLoaded", function () {{
        window.setBuilderTheme(saved);
        var form = document.getElementById("new-task-form");
        var status = document.getElementById("new-task-status");
        if (!form || !status) {{
          return;
        }}
        form.addEventListener("submit", function (event) {{
          event.preventDefault();
          var button = form.querySelector("button[type='submit']");
          var prompt = form.prompt.value.trim();
          var scriptPath = form.script_path.value.trim();
          if (!prompt) {{
            status.textContent = "Prompt is required.";
            status.className = "form-status error";
            return;
          }}
          button.disabled = true;
          status.textContent = "Submitting plan-only task...";
          status.className = "form-status";
          fetch("/tasks", {{
            method: "POST",
            headers: {{"Content-Type": "application/json"}},
            body: JSON.stringify({{
              prompt: prompt,
              script_path: scriptPath || null,
              model: form.model.value || null
            }})
          }})
            .then(function (response) {{
              return response.json().then(function (body) {{
                if (!response.ok) {{
                  throw new Error(body.detail || "Task failed.");
                }}
                return body;
              }});
            }})
            .then(function (body) {{
              status.textContent = "Task completed: " + body.task_id + ". Refreshing dashboard...";
              status.className = "form-status ok";
              window.setTimeout(function () {{ window.location.reload(); }}, 700);
            }})
            .catch(function (error) {{
              status.textContent = error.message;
              status.className = "form-status error";
            }})
            .finally(function () {{
              button.disabled = false;
            }});
        }});
      }});
    }})();
  </script>
</head>
<body>
  <header>
    <div class="topbar">
      <div>
        <h1>Builder Agent</h1>
        <div class="meta">A local planning cockpit for FiveM script fixes, compatibility scans, and careful next steps.</div>
      </div>
      <div class="header-actions">
        <span class="pill">Local only</span>
        <span class="pill">Plan mode</span>
        <span class="pill">Ollama: {esc(config.model)}</span>
        <div class="theme-toggle" aria-label="Theme">
          <button type="button" data-theme-choice="system" aria-pressed="true" onclick="setBuilderTheme('system')">System</button>
          <button type="button" data-theme-choice="light" aria-pressed="false" onclick="setBuilderTheme('light')">Light</button>
          <button type="button" data-theme-choice="dark" aria-pressed="false" onclick="setBuilderTheme('dark')">Dark</button>
        </div>
      </div>
    </div>
  </header>
  <main>
    <section class="panel wide intro">
      <div class="intro-content">
        <div>
          <h2>Careful plans before code changes</h2>
          <p>Builder Agent reviews incoming FiveM scripts, remembers safety rules, scans for framework and dependency clues, then writes a plan and report. It stays read-only: no SQL, no server restarts, no Git pushes, and no live resource edits.</p>
        </div>
        <div class="intro-mark" aria-hidden="true">🛠️</div>
      </div>
    </section>
    <section class="panel wide">
      <div class="panel-header">
        <h2>{icon_title("📋", "New Task")}</h2>
        <span class="count">plan-only intake</span>
      </div>
      <div class="form-body">
        <form id="new-task-form" class="task-form">
          <div class="form-grid">
            <label>
              Prompt
              <textarea name="prompt" required placeholder="Example: Adapt this script from ESX to QBCore."></textarea>
            </label>
            <div class="task-form">
              <label>
                Optional script/folder path
                <input name="script_path" placeholder="incoming/qb-inventory-new">
              </label>
              <label>
                Model
                <input name="model" value="{esc(config.model)}" readonly>
              </label>
            </div>
          </div>
          <div class="submit-row">
            <div>
              <button type="submit">Submit Plan</button>
            </div>
            <div id="new-task-status" class="form-status" role="status" aria-live="polite"></div>
          </div>
          <div class="form-note">Tasks are read-only. Paths are limited to <code>{esc(str(config.incoming_dir))}</code>. Apply and rollback remain disabled.</div>
        </form>
      </div>
    </section>
    {services_panel(data.get("service_inventory", {}))}
    <section class="panel wide">
      <div class="panel-header">
        <h2>{icon_title("🛣️", "Paths")}</h2>
        <span class="count">read-only view</span>
      </div>
      <div class="panel-body table-wrap">
        <table class="paths-table">
          <tr><th>Incoming</th><td><code>{esc(str(config.incoming_dir))}</code></td></tr>
          <tr><th>Server Resources</th><td><code>{esc(str(config.server_resources))}</code></td></tr>
          <tr><th>Reports</th><td><code>{esc(str(config.reports_dir))}</code></td></tr>
          <tr><th>Logs</th><td><code>{esc(str(config.logs_dir))}</code></td></tr>
          <tr><th>Memory</th><td><code>{esc(str(config.database_path))}</code></td></tr>
        </table>
      </div>
      <p class="actions"><button disabled>Plan</button><button disabled>Apply</button><button disabled>Rollback</button></p>
    </section>
    <div class="grid">
      {table_panel("📋", "Active Tasks", [row for row in data["tasks"] if row.get("status") == "active"], ["id", "prompt", "model", "created_at", "view"], "No active tasks right now.", "Submit a plan request and Builder Agent will track it here while it works.", table_class="tasks-table")}
      {table_panel("📋", "Completed Tasks", [row for row in data["tasks"] if row.get("status") != "active"], ["id", "status", "approval_status", "apply_mode", "updated_at", "view"], "No completed tasks yet.", "Submit a plan request to get the first report on the board.", table_class="tasks-table")}
      {table_panel("🔎", "Findings", data["findings"][:5], ["task_id", "severity", "category", "message", "view"], "No findings yet.", "Scans will surface dependencies, SQL files, framework clues, and risk notes here.", table_class="compact-table")}
      {table_panel("📄", "Reports", data["reports"], ["task_id", "title", "created_at", "report"], "No reports yet.", "Completed plan requests will create markdown reports with review notes and test checklists.", table_class="compact-table")}
      {table_panel("🧾", "Logs", data["logs"][:8], ["created_at", "task_id", "level", "action", "message"], "No logs yet.", "Builder Agent records task intake, scans, model calls, reports, and errors here.", table_class="compact-table")}
      {memory_panel(data["memory_notes"])}
    </div>
  </main>
</body>
</html>"""


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def render_task_detail(config: BuilderConfig, detail: dict[str, Any]) -> str:
    task = detail["task"]
    plan = detail.get("plan") or {}
    apply_runs = detail.get("apply_runs") or []
    latest_apply = apply_runs[0] if apply_runs else {}
    validation = parse_json(latest_apply.get("validation_json", "{}")) if latest_apply else {}
    diff_text = latest_apply.get("diff_text", "")
    task_id = str(task["id"])
    sql_detected = any(
        finding.get("category") == "database" and finding.get("severity") in {"high", "error"}
        for finding in detail.get("findings", [])
    )
    sql_banner = (
        "<div class='warning-box'><strong>SQL detected.</strong> Review only. Live apply blocked.</div>"
        if sql_detected
        else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Builder Agent Task</title>
  <style>
    body {{ margin: 0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif; background: #0d1726; color: #edf5ff; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 20px; display: grid; gap: 16px; }}
    a {{ color: #67d8ff; font-weight: 750; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .panel {{ background: #121f32; border: 1px solid #253850; border-radius: 8px; overflow: hidden; box-shadow: 0 18px 48px rgba(0, 0, 0, .28); }}
    .panel-header {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 15px 16px; border-bottom: 1px solid #203047; background: #0f1b2c; }}
    .panel-header h1, .panel-header h2 {{ margin: 0; font-size: 18px; }}
    .detail-body {{ padding: 16px; display: grid; gap: 14px; }}
    .detail-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; }}
    .note-box {{ border: 1px solid #203047; border-radius: 8px; background: #0d1828; padding: 12px; }}
    .note-box h3 {{ margin: 0 0 8px; font-size: 14px; color: #9fb1c7; }}
    code {{ background: #0b1422; border: 1px solid #203047; border-radius: 6px; padding: 2px 5px; overflow-wrap: anywhere; }}
    .badge {{ display: inline-flex; padding: 3px 8px; border-radius: 999px; border: 1px solid #31506f; background: #0b1422; color: #9fdcff; font-weight: 850; font-size: 12px; }}
    .badge.approved, .badge.completed, .badge.passed {{ color: #5eead4; border-color: rgba(94, 234, 212, .35); }}
    .badge.rejected, .badge.failed, .badge.unreachable, .badge.unhealthy {{ color: #fb7185; border-color: rgba(251, 113, 133, .35); }}
    .badge.blocked-review, .badge.warning {{ color: #fbbf24; border-color: rgba(251, 191, 36, .38); }}
    .badge.reachable {{ color: #5eead4; border-color: rgba(94, 234, 212, .35); }}
    .warning-box {{ border: 1px solid rgba(251, 191, 36, .38); border-radius: 8px; background: rgba(251, 191, 36, .1); color: #ffe7a3; padding: 12px; line-height: 1.45; }}
    .control-row {{ display: flex; gap: 10px; flex-wrap: wrap; }}
    button, .button {{ appearance: none; border: 1px solid #31506f; background: #10243a; color: #edf5ff; min-height: 38px; padding: 8px 12px; border-radius: 8px; font: inherit; font-weight: 850; cursor: pointer; }}
    button:hover, .button:hover {{ background: #163453; text-decoration: none; }}
    button.primary {{ background: linear-gradient(180deg, #38bdf8, #60a5fa); color: #00111f; }}
    button.danger {{ color: #fb7185; }}
    button:disabled {{ opacity: .55; cursor: not-allowed; }}
    pre {{ margin: 0; max-height: 460px; overflow: auto; white-space: pre; border: 1px solid #203047; border-radius: 8px; background: #08111f; color: #edf5ff; padding: 12px; font-size: 12px; line-height: 1.45; }}
    ul {{ margin: 0; padding-left: 18px; }}
  </style>
  <script>
    function postAction(path) {{
      var status = document.getElementById("action-status");
      status.textContent = "Working...";
      fetch(path, {{method: "POST", headers: {{"Content-Type": "application/json"}}, body: JSON.stringify({{note: "Dashboard action"}})}})
        .then(function(response) {{ return response.json().then(function(body) {{ if (!response.ok) throw new Error(body.detail || "Action failed."); return body; }}); }})
        .then(function() {{ status.textContent = "Done. Refreshing..."; window.setTimeout(function() {{ window.location.reload(); }}, 600); }})
        .catch(function(error) {{ status.textContent = error.message; }});
    }}
    function sendToCodingAgent(taskId) {{
      var status = document.getElementById("coding-agent-status");
      status.textContent = "Sending to coding_agent...";
      fetch("/tasks/" + taskId + "/send-to-coding-agent", {{method: "POST"}})
        .then(function(response) {{ return response.json().then(function(body) {{ if (!response.ok) throw new Error(body.detail || "coding_agent handoff failed."); return body; }}); }})
        .then(function(body) {{ status.textContent = "coding_agent task " + body.task_id + " completed. Report: " + (body.report_path || "none"); }})
        .catch(function(error) {{ status.textContent = error.message; }});
    }}
  </script>
</head>
<body>
  <main>
    <section class="panel">
      <div class="panel-header">
        <h1>📋 Task {esc(task_id)}</h1>
        <a class="button" href="/">Back to dashboard</a>
      </div>
      <div class="detail-body">
        <div class="detail-grid">
          <div class="note-box"><h3>Status</h3>{badge(task.get("status"))} {badge(task.get("approval_status"))} {badge(task.get("apply_mode"))}</div>
          <div class="note-box"><h3>Model</h3><code>{esc(task.get("model", config.model))}</code></div>
          <div class="note-box"><h3>Script Path</h3><code>{esc(task.get("script_path") or "prompt only")}</code></div>
          <div class="note-box"><h3>Staging Output</h3><code>{esc(task.get("staging_path") or "Not applied to staging yet")}</code></div>
        </div>
        {sql_banner}
        <div class="note-box"><h3>Prompt</h3>{esc(task.get("prompt", ""))}</div>
        <div class="control-row">
          <button class="primary" onclick="postAction('/tasks/{esc(task_id)}/approve')">Approve</button>
          <button class="danger" onclick="postAction('/tasks/{esc(task_id)}/reject')">Reject</button>
          <button onclick="postAction('/tasks/{esc(task_id)}/apply')">Apply to staging only</button>
          <button onclick="sendToCodingAgent('{esc(task_id)}')">Send to coding_agent</button>
          <button disabled>Live apply disabled</button>
          <span id="action-status"></span>
          <span id="coding-agent-status"></span>
        </div>
      </div>
    </section>
    <section class="panel"><div class="panel-header"><h2>Generated Plan</h2></div><div class="detail-body">{plan_html(plan)}</div></section>
    <section class="panel"><div class="panel-header"><h2>Findings</h2></div><div class="detail-body">{list_html(detail.get("findings", []), ["severity", "category", "message"])}</div></section>
    <section class="panel"><div class="panel-header"><h2>Reports</h2></div><div class="detail-body">{reports_html(detail.get("reports", []))}</div></section>
    <section class="panel"><div class="panel-header"><h2>Validation Results</h2><span>{badge(validation.get("status", "not run"))}</span></div><div class="detail-body">{validation_html(validation)}</div></section>
    <section class="panel"><div class="panel-header"><h2>Diff Preview</h2></div><div class="detail-body"><pre>{esc(diff_text or "No staging diff generated yet.")}</pre></div></section>
    <section class="panel"><div class="panel-header"><h2>Logs</h2></div><div class="detail-body">{list_html(detail.get("logs", []), ["created_at", "level", "action", "message"])}</div></section>
  </main>
</body>
</html>"""


def icon_title(icon: str, title: str) -> str:
    return f"<span class='title-with-icon'><span class='title-icon' aria-hidden='true'>{esc(icon)}</span><span>{esc(title)}</span></span>"


def badge(value: object) -> str:
    text = str(value or "none")
    return f"<span class='badge {slug(text)}'>{esc(text)}</span>"


def parse_json(value: object) -> Any:
    try:
        return json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}


def plan_html(plan: dict[str, Any]) -> str:
    if not plan:
        return "<div class='note-box'>No plan stored for this task.</div>"
    sections = [
        ("Summary", plan.get("summary", "")),
        ("Risks", plan.get("risks_json", [])),
        ("Files It Would Change", plan.get("files_json", [])),
        ("Backup Plan", plan.get("backup_plan_json", [])),
        ("Patch Plan", plan.get("patch_plan_json", [])),
        ("Test Checklist", plan.get("test_checklist_json", [])),
    ]
    html_parts = []
    for title, value in sections:
        html_parts.append(f"<div class='note-box'><h3>{esc(title)}</h3>{value_html(value)}</div>")
    return "".join(html_parts)


def value_html(value: object) -> str:
    if isinstance(value, list):
        if not value:
            return "<span>No items.</span>"
        return "<ul>" + "".join(f"<li>{esc(item)}</li>" for item in value) + "</ul>"
    return esc(value)


def list_html(rows: list[dict[str, Any]], columns: list[str]) -> str:
    if not rows:
        return "<div class='note-box'>Nothing recorded yet.</div>"
    items = []
    for row in rows:
        bits = []
        for column in columns:
            value = row.get(column, "")
            if column in {"status", "severity", "level", "decision"}:
                bits.append(badge(value))
            else:
                bits.append(f"<strong>{esc(column)}:</strong> {esc(value)}")
        items.append("<li>" + " &nbsp; ".join(bits) + "</li>")
    return "<ul>" + "".join(items) + "</ul>"


def reports_html(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "<div class='note-box'>No report recorded yet.</div>"
    links = []
    for row in rows:
        task_id = esc(row.get("task_id", ""))
        links.append(f"<li><a href='/reports/{task_id}/view' target='_blank' rel='noopener'>Open report</a> <code>{esc(row.get('path', ''))}</code></li>")
    return "<ul>" + "".join(links) + "</ul>"


def validation_html(validation: dict[str, Any]) -> str:
    checks = validation.get("checks", []) if validation else []
    if not checks:
        return "<div class='note-box'>Validation has not run yet.</div>"
    items = []
    for check in checks:
        items.append(
            "<li>"
            f"{badge(check.get('status'))} <strong>{esc(check.get('check', 'check'))}</strong> "
            f"<code>{esc(check.get('file', ''))}</code> {esc(check.get('message', ''))}"
            "</li>"
        )
    return "<ul>" + "".join(items) + "</ul>"


def services_panel(inventory: dict[str, Any]) -> str:
    agents = inventory.get("agents", []) if isinstance(inventory, dict) else []
    matching_services = inventory.get("matching_services", []) if isinstance(inventory, dict) else []
    matching_processes = inventory.get("matching_processes", []) if isinstance(inventory, dict) else []
    service_rows = "".join(
        "<tr>"
        f"<td class='cell-text'>{esc(row.get('name', ''))}</td>"
        f"<td class='cell-id'><code>{esc(row.get('service', ''))}</code></td>"
        f"<td>{badge(row.get('active', 'unknown'))}</td>"
        f"<td>{badge(row.get('enabled', 'unknown'))}</td>"
        f"<td>{badge(row.get('process', 'unknown'))}</td>"
        f"<td>{badge(row.get('health', 'not checked'))}</td>"
        f"<td class='cell-small'>{esc(row.get('process_hint', ''))}</td>"
        "</tr>"
        for row in agents
    )
    if not service_rows:
        service_rows = "<tr><td colspan='7'><div class='empty-state'><strong>No service inventory.</strong><span>Service checks are read-only and will appear here when available.</span></div></td></tr>"
    unit_list = "".join(
        f"<li><code>{esc(row.get('unit', ''))}</code> {badge(row.get('active', 'unknown'))} {badge(row.get('sub', 'unknown'))} {esc(row.get('description', ''))}</li>"
        for row in matching_services[:10]
    ) or "<li>No matching systemd services found.</li>"
    process_list = "".join(f"<li><code>{esc(line)}</code></li>" for line in matching_processes[:8]) or "<li>No matching processes found.</li>"
    return (
        "<section class='panel wide'>"
        f"<div class='panel-header'><h2>{icon_title('🛰️', 'Agents / Services')}</h2><span class='count'>{len(agents)} known</span></div>"
        "<div class='panel-body table-wrap'>"
        "<table class='services-table'><thead><tr><th>Agent</th><th>Service</th><th>Running</th><th>Auto-start</th><th>Process</th><th>Health</th><th>Process hint</th></tr></thead>"
        f"<tbody>{service_rows}</tbody></table>"
        "</div>"
        "<details class='detail-body'><summary class='button-link'>Show matched units/processes</summary>"
        f"<div class='note-box'><h3>Matching systemd services</h3><ul>{unit_list}</ul></div>"
        f"<div class='note-box'><h3>Matching processes</h3><ul>{process_list}</ul></div>"
        "</details>"
        "</section>"
    )


def memory_panel(rows: list[dict[str, Any]]) -> str:
    columns = ["note_type", "key", "value", "source"]
    if rows:
        body = "".join(
            "<tr>" + "".join(f"<td>{format_cell(row.get(column, ''), column, row)}</td>" for column in columns) + "</tr>"
            for row in rows[:20]
        )
    else:
        body = (
            "<tr><td colspan='4'>"
            "<div class='empty-state'><strong>No memory notes yet.</strong><span>Safety rules and compatibility lessons will appear here once the database is initialized.</span></div>"
            "</td></tr>"
        )
    headers = "".join(f"<th>{esc(column)}</th>" for column in columns)
    return (
        f"<details class='memory-details panel standard'><summary class='panel-header'><h2>{icon_title('🧠', 'Memory')}</h2><span class='count'>{len(rows)} notes</span></summary>"
        f"<div class='panel-body table-wrap'><table class='compact-table'><thead><tr>{headers}</tr></thead><tbody>{body}</tbody></table></div>"
        "</details>"
    )


def table_panel(
    icon: str,
    title: str,
    rows: list[dict[str, Any]],
    columns: list[str],
    empty_title: str,
    empty_detail: str,
    table_class: str = "",
    wrapper_tag: str = "section",
) -> str:
    body = ""
    if rows:
        for row in rows[:20]:
            cells = "".join(f"<td>{format_cell(row.get(column, ''), column, row)}</td>" for column in columns)
            body += f"<tr>{cells}</tr>"
    else:
        body = (
            f"<tr><td colspan='{len(columns)}'>"
            f"<div class='empty-state'><strong>{esc(empty_title)}</strong><span>{esc(empty_detail)}</span></div>"
            "</td></tr>"
        )
    headers = "".join(f"<th>{esc(column)}</th>" for column in columns)
    return (
        f"<{wrapper_tag} class='panel standard'>"
        f"<div class='panel-header'><h2>{icon_title(icon, title)}</h2><span class='count'>{len(rows)} shown</span></div>"
        f"<div class='panel-body table-wrap'><table class='{esc(table_class)}'><thead><tr>{headers}</tr></thead><tbody>{body}</tbody></table></div>"
        f"</{wrapper_tag}>"
    )


def format_cell(value: object, column: str, row: dict[str, Any]) -> str:
    if column == "view" and row.get("id"):
        task_id = esc(str(row["id"]))
        return f"<a class='button-link' href='/tasks/{task_id}/view'>View</a>"
    if column == "view" and row.get("task_id"):
        task_id = esc(str(row["task_id"]))
        return f"<a class='button-link' href='/tasks/{task_id}/view'>View task</a>"
    if column == "report" and row.get("task_id"):
        task_id = esc(str(row["task_id"]))
        return f"<a class='button-link' href='/reports/{task_id}/view' target='_blank' rel='noopener'>Open</a>"
    if value is None:
        return ""
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    if len(text) > 120:
        text = text[:117] + "..."
    if column in {"status", "severity", "level"}:
        css_class = slug(text)
        return f"<span class='badge {css_class}'>{esc(text)}</span>"
    if column == "approval_status" or column == "apply_mode":
        css_class = slug(text)
        return f"<span class='badge {css_class}'>{esc(text)}</span>"
    if column == "id":
        return f"<a class='cell-id' href='/tasks/{esc(text)}/view'>{esc(text)}</a>"
    if column == "task_id":
        return f"<a class='cell-id' href='/tasks/{esc(text)}/view'>{esc(text)}</a>"
    if column == "path" and row.get("task_id"):
        task_id = esc(str(row["task_id"]))
        return f"<a href='/reports/{task_id}/view' target='_blank' rel='noopener'>Open report</a><br><code>{esc(text)}</code>"
    if not text:
        return "<span class='cell-muted'>None</span>"
    css_class = "cell-text" if column in {"prompt", "summary", "message", "value", "title"} else ""
    return f"<span class='{css_class}'>{esc(text)}</span>" if css_class else esc(text)


def slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-")
