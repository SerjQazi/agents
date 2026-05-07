# AI Ecosystem and Memory UI Suggestions

This document outlines suggested HTML structures and corresponding CSS class usage for enhancing the AgentOS dashboard's visibility of its AI ecosystem and memory components. These are frontend-only mockups, assuming backend data retrieval would be integrated later.

---

## 1. AI Ecosystem Overview Section

This section would ideally be on the Dashboard or a dedicated "Agents" page, showcasing the status and role of each primary AI.

**Suggested HTML Structure for an AI Ecosystem Grid:**

```html
<section class="ao-panel">
  <h2>AI Ecosystem Overview</h2>
  <p>Status and recommended usage for primary AgentOS AI models and agents.</p>
  <div class="ai-ecosystem-grid">

    <!-- Codex Agent Card -->
    <article class="ai-agent-card">
      <h3>Codex</h3>
      <p class="role">Primary Heavy-Lifter</p>
      <div class="status online">Online (ready)</div>
      <small>Heavy implementation, complex problem-solving, test repair.</small>
      <div class="meta">Cost: High, Latency: Medium</div>
      <button class="button secondary">More Info</button>
    </article>

    <!-- Gemini CLI Agent Card -->
    <article class="ai-agent-card">
      <h3>Gemini CLI</h3>
      <p class="role">Cloud Fallback / Reports</p>
      <div class="status online">Online (ready)</div>
      <small>Bounded planning, reports, UI/UX polish.</small>
      <div class="meta">Cost: Medium, Latency: Low</div>
      <button class="button secondary">More Info</button>
    </article>

    <!-- OpenCode Agent Card (OpenRouter) -->
    <article class="ai-agent-card">
      <h3>OpenCode (OpenRouter)</h3>
      <p class="role">Night-Shift / Specialized Coding</p>
      <div class="status online">Online (ready)</div>
      <small>Focused code generation, quick experiments (via various models).</small>
      <div class="meta">Cost: Variable, Latency: Low</div>
      <button class="button secondary">More Info</button>
    </article>

    <!-- Local Ollama Agent Card -->
    <article class="ai-agent-card offline">
      <h3>Local Ollama</h3>
      <p class="role">Emergency-Only / Deprecated</p>
      <div class="status offline">Stopped (emergency only)</div>
      <small>Last resort for tiny tasks when cloud is down.</small>
      <div class="meta">Cost: Free, Latency: Very High</div>
      <button class="button secondary">More Info</button>
    </article>

    <!-- Placeholder for other internal agents, e.g., Planner, Coding -->
    <article class="ai-agent-card">
      <h3>Planner Agent</h3>
      <p class="role">Script Integration Planning</p>
      <div class="status online">Online (active)</div>
      <small>Framework/dependency scanning, risk assessment.</small>
      <div class="meta">Internal Service</div>
      <button class="button secondary">More Info</button>
    </article>

  </div>
</section>
```

---

## 2. AI Memory Awareness Section

This section would logically fit on the Dashboard or a dedicated "AI Memory" page (linked from the sidebar). It provides quick access or summaries of the shared knowledge base.

**Suggested HTML Structure for an AI Memory Card Layout:**

```html
<section class="ao-panel">
  <h2>AI Memory & Learning</h2>
  <p>Collective intelligence: lessons learned, model routing, and session checkpoints.</p>
  <div class="ai-memory-grid">

    <!-- Lessons Learned Card -->
    <article class="ao-card ai-memory-card">
      <h3>Lessons Learned</h3>
      <p>Insights, patterns, failures from past AI sessions.</p>
      <div class="meta">Updated: 2024-05-06 14:30 UTC</div>
      <a href="/reports/view?path=memory/ai-agents/lessons-learned.md" class="button">View Log</a>
    </article>

    <!-- Model Routing Guide Card -->
    <article class="ao-card ai-memory-card">
      <h3>Model Routing Guide</h3>
      <p>Guidelines for selecting the optimal AI model per task.</p>
      <div class="meta">Version: 1.1</div>
      <a href="/reports/view?path=memory/ai-agents/model-routing.md" class="button">View Guide</a>
    </article>

    <!-- Session Checkpoints Card -->
    <article class="ao-card ai-memory-card">
      <h3>Session Checkpoints</h3>
      <p>Archived summaries of key AI work sessions.</p>
      <div class="meta">Last Session: Codex (2024-05-05)</div>
      <a href="/reports/session-checkpoints" class="button">Browse Checkpoints</a>
    </article>

    <!-- Specific Lesson Type Card (Example: Inventory Migration) -->
    <article class="ao-card ai-memory-card">
      <h3>Inventory Migration Lessons</h3>
      <p>Specific insights from inventory system migrations.</p>
      <div class="meta">Key Learnings: SQL safety, export mapping.</div>
      <a href="/reports/view?path=memory/lessons/inventory-migration-lessons.md" class="button">View Lessons</a>
    </article>

  </div>
</section>
```
