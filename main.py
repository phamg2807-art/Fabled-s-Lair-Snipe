# ── Imports ───────────────────────────────────────────────────────────────────
import os
import json
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from collections import Counter
from flask import Flask, jsonify, render_template_string, request

# ── Config ────────────────────────────────────────────────────────────────────
API_BASE    = "https://fabled-s-lair-snipe.onrender.com"
API_METRICS = f"{API_BASE}/api/metrics"
API_ZITE    = f"{API_BASE}/api/zite"
PORT        = int(os.environ.get("PORT", 5000))

app = Flask(__name__)

# ── API Fetching ──────────────────────────────────────────────────────────────

def fetch_metrics(timeout=8):
    try:
        req = urllib.request.Request(
            API_METRICS,
            headers={"User-Agent": "FabledDashboard/1.0", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw), None
    except urllib.error.URLError as e:
        return None, f"Network error: {e.reason}"
    except Exception as e:
        return None, str(e)

# ── Data Processing ───────────────────────────────────────────────────────────

def parse_duration_to_seconds(dur_str):
    """Convert '10m 30s' or '2m 0s' to seconds."""
    if not dur_str or dur_str in ("N/A", "N/A (Start missed)"):
        return None
    total = 0
    parts = dur_str.strip().split()
    for i, p in enumerate(parts):
        if p.endswith("m"):
            total += int(p[:-1]) * 60
        elif p.endswith("s"):
            total += int(p[:-1])
    return total if total > 0 else None

def fmt_seconds(sec):
    if sec is None:
        return "—"
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"

def time_ago(iso_str):
    if not iso_str:
        return "—"
    try:
        dt  = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        sec = int((now - dt).total_seconds())
        if sec < 60:   return f"{sec}s ago"
        if sec < 3600: return f"{sec//60}m ago"
        if sec < 86400: return f"{sec//3600}h ago"
        return f"{sec//86400}d ago"
    except Exception:
        return "—"

def extract_event_history(data):
    """Pull all completed sessions from raw webhook registry into a flat list."""
    events = []
    registry = data.get("raw_webhook_registry", {})
    for cid, ch_data in registry.items():
        ch_name = ch_data.get("name", "unknown")
        accounts = ch_data.get("accounts", {})
        for link_key, acc in accounts.items():
            for sess in acc.get("completed_sessions", []):
                sec = parse_duration_to_seconds(sess.get("duration", ""))
                events.append({
                    "name":         sess.get("name", "UNKNOWN"),
                    "type":         "merchant" if "MERCHANT" in sess.get("name","").upper() else "biome",
                    "duration":     sess.get("duration", "—"),
                    "duration_sec": sec,
                    "at":           sess.get("at", ""),
                    "time_ago":     time_ago(sess.get("at", "")),
                    "macro_source": sess.get("macro_source", "Unknown"),
                    "account":      acc.get("display_name", "Unknown"),
                    "channel":      ch_name,
                    "link":         link_key if link_key.startswith("http") else None,
                })
    events.sort(key=lambda e: e.get("at", ""), reverse=True)
    return events

def compute_statistics(data, events):
    biome_counts   = data.get("counters", {}).get("biomes", {})
    merchant_counts = data.get("counters", {}).get("merchants", {})
    all_counts     = {**biome_counts, **merchant_counts}
    most_common    = max(all_counts, key=all_counts.get) if all_counts else "—"

    durations = [e["duration_sec"] for e in events if e["duration_sec"] is not None]
    avg_dur   = int(sum(durations) / len(durations)) if durations else None
    max_dur   = max(durations) if durations else None
    min_dur   = min(durations) if durations else None

    # events per biome sorted
    biome_sorted = sorted(biome_counts.items(), key=lambda x: -x[1])

    # Source breakdown
    src_counter = Counter(e["macro_source"] for e in events)

    return {
        "total_events":   data.get("telemetry", {}).get("grand_total_biomes", 0)
                          + data.get("telemetry", {}).get("grand_total_merchants", 0),
        "total_biomes":   data.get("telemetry", {}).get("grand_total_biomes", 0),
        "total_merchants": data.get("telemetry", {}).get("grand_total_merchants", 0),
        "most_common":    most_common,
        "avg_duration":   fmt_seconds(avg_dur),
        "longest":        fmt_seconds(max_dur),
        "shortest":       fmt_seconds(min_dur),
        "biome_sorted":   biome_sorted,
        "merchant_sorted": sorted(merchant_counts.items(), key=lambda x: -x[1]),
        "source_sorted":  src_counter.most_common(10),
        "session_count":  len(events),
    }

# ── CSS ───────────────────────────────────────────────────────────────────────

GLOBAL_CSS = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg:      #09090f;
  --surface: #0e0e18;
  --card:    #13131f;
  --border:  #1c1c2e;
  --border2: #252540;
  --text:    #c8cad8;
  --muted:   #565878;
  --accent:  #6c63ff;
  --accent2: #a78bfa;
  --live:    #22c55e;
  --warn:    #f59e0b;
  --danger:  #ef4444;
  --cyan:    #06b6d4;
  --mono:    'JetBrains Mono', 'Fira Code', 'Courier New', monospace;
}

html { scroll-behavior: smooth; }

body {
  font-family: 'Inter', 'Segoe UI', system-ui, sans-serif;
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
  font-size: 14px;
  line-height: 1.6;
}

a { color: var(--accent2); text-decoration: none; }
a:hover { color: #fff; }

/* Layout */
.layout { display: flex; min-height: 100vh; }

.sidebar {
  width: 220px;
  min-width: 220px;
  background: var(--surface);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  padding: 0;
  position: fixed;
  top: 0; left: 0;
  height: 100vh;
  z-index: 100;
  overflow-y: auto;
}

.sidebar-brand {
  padding: 24px 20px 20px;
  border-bottom: 1px solid var(--border);
}

.sidebar-brand .brand-name {
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #fff;
}

.sidebar-brand .brand-sub {
  font-size: 11px;
  color: var(--muted);
  margin-top: 2px;
}

.sidebar-status {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 10px;
  font-size: 11px;
  font-weight: 600;
  color: var(--live);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: currentColor;
  animation: pulse-dot 2s ease-in-out infinite;
  flex-shrink: 0;
}

@keyframes pulse-dot {
  0%, 100% { opacity: 0.5; transform: scale(0.9); }
  50%       { opacity: 1;   transform: scale(1.1); }
}

.sidebar-nav { padding: 12px 0; flex: 1; }

.nav-section {
  padding: 8px 20px 4px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--muted);
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 20px;
  color: var(--muted);
  font-size: 13px;
  font-weight: 500;
  transition: color 0.15s, background 0.15s;
  border-left: 2px solid transparent;
  cursor: pointer;
  text-decoration: none;
}

.nav-item:hover {
  color: var(--text);
  background: rgba(108,99,255,0.06);
}

.nav-item.active {
  color: #fff;
  border-left-color: var(--accent);
  background: rgba(108,99,255,0.1);
}

.nav-item svg { width: 15px; height: 15px; flex-shrink: 0; }

.sidebar-footer {
  padding: 16px 20px;
  border-top: 1px solid var(--border);
  font-size: 11px;
  color: var(--muted);
}

.main-content {
  margin-left: 220px;
  flex: 1;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.topbar {
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  padding: 14px 32px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  position: sticky;
  top: 0;
  z-index: 50;
}

.topbar-title {
  font-size: 15px;
  font-weight: 600;
  color: #fff;
}

.topbar-meta {
  font-size: 12px;
  color: var(--muted);
  display: flex;
  align-items: center;
  gap: 16px;
}

.page-body { padding: 28px 32px; flex: 1; }

/* Cards */
.card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 20px;
}

.card-sm { padding: 16px; }

/* Stat grid */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 14px;
  margin-bottom: 28px;
}

.stat-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 18px 20px;
  border-top: 2px solid var(--accent);
}

.stat-card.live   { border-top-color: var(--live); }
.stat-card.warn   { border-top-color: var(--warn); }
.stat-card.cyan   { border-top-color: var(--cyan); }
.stat-card.purple { border-top-color: var(--accent2); }

.stat-label { font-size: 10px; text-transform: uppercase; letter-spacing: 0.1em; color: var(--muted); margin-bottom: 8px; font-weight: 600; }
.stat-value { font-size: 28px; font-weight: 800; color: #fff; font-variant-numeric: tabular-nums; }
.stat-sub   { font-size: 11px; color: var(--muted); margin-top: 4px; }

/* Section heading */
.section-heading {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--muted);
  font-weight: 700;
  margin-bottom: 14px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border);
}

/* Badges */
.badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

.badge-live    { background: rgba(34,197,94,0.12);  color: var(--live); border: 1px solid rgba(34,197,94,0.2); }
.badge-biome   { background: rgba(108,99,255,0.12); color: var(--accent2); border: 1px solid rgba(108,99,255,0.2); }
.badge-merchant { background: rgba(245,158,11,0.12); color: var(--warn); border: 1px solid rgba(245,158,11,0.2); }
.badge-offline { background: rgba(239,68,68,0.12); color: var(--danger); border: 1px solid rgba(239,68,68,0.2); }
.badge-online  { background: rgba(34,197,94,0.12); color: var(--live); border: 1px solid rgba(34,197,94,0.2); }
.badge-muted   { background: rgba(86,88,120,0.15); color: var(--muted); border: 1px solid var(--border2); }

/* Table */
.data-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.data-table th {
  text-align: left;
  padding: 10px 14px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}
.data-table td {
  padding: 11px 14px;
  border-bottom: 1px solid rgba(28,28,46,0.6);
  vertical-align: middle;
  color: var(--text);
}
.data-table tr:last-child td { border-bottom: none; }
.data-table tr:hover td { background: rgba(108,99,255,0.04); }
.data-table .mono { font-family: var(--mono); font-size: 12px; }

/* Live event card */
.event-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-left: 3px solid var(--accent);
  border-radius: 8px;
  padding: 14px 18px;
  margin-bottom: 10px;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.event-card.merchant { border-left-color: var(--warn); }
.event-card.biome    { border-left-color: var(--accent); }

.event-name   { font-size: 15px; font-weight: 700; color: #fff; margin-bottom: 4px; }
.event-meta   { font-size: 12px; color: var(--muted); }
.event-meta span { color: var(--cyan); }

.event-right  { text-align: right; flex-shrink: 0; }
.timer-badge  {
  font-family: var(--mono);
  font-size: 13px;
  font-weight: 700;
  color: var(--live);
  background: rgba(34,197,94,0.08);
  border: 1px solid rgba(34,197,94,0.15);
  border-radius: 5px;
  padding: 4px 10px;
  letter-spacing: 0.04em;
}

/* Webhook row */
.webhook-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
}
.webhook-row:last-child { border-bottom: none; }
.webhook-name { font-size: 13px; font-weight: 500; color: #fff; }
.webhook-sub  { font-size: 11px; color: var(--muted); margin-top: 2px; }

/* Search input */
.search-bar {
  background: var(--surface);
  border: 1px solid var(--border2);
  border-radius: 7px;
  color: var(--text);
  padding: 9px 14px;
  font-size: 13px;
  width: 100%;
  max-width: 320px;
  outline: none;
  transition: border-color 0.15s;
}
.search-bar:focus { border-color: var(--accent); }
.search-bar::placeholder { color: var(--muted); }

/* Select */
.filter-select {
  background: var(--surface);
  border: 1px solid var(--border2);
  border-radius: 7px;
  color: var(--text);
  padding: 9px 12px;
  font-size: 13px;
  outline: none;
  cursor: pointer;
  transition: border-color 0.15s;
}
.filter-select:focus { border-color: var(--accent); }

/* Controls bar */
.controls-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 18px;
}

/* Bar chart */
.bar-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
  font-size: 12px;
}
.bar-label { width: 130px; flex-shrink: 0; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bar-track { flex: 1; background: var(--border); border-radius: 3px; height: 7px; overflow: hidden; }
.bar-fill  { height: 100%; border-radius: 3px; background: var(--accent); transition: width 0.5s ease; }
.bar-fill.warn { background: var(--warn); }
.bar-fill.cyan { background: var(--cyan); }
.bar-count { width: 50px; text-align: right; color: var(--muted); font-family: var(--mono); flex-shrink: 0; }

/* Code block */
.code-block {
  background: #06060e;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 20px;
  font-family: var(--mono);
  font-size: 12px;
  line-height: 1.7;
  overflow: auto;
  max-height: 70vh;
  color: #a8b5cc;
}

/* Utility */
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
.mb-4  { margin-bottom: 16px; }
.mb-6  { margin-bottom: 24px; }
.mb-8  { margin-bottom: 32px; }
.mt-4  { margin-top: 16px; }
.txt-muted { color: var(--muted); }
.txt-sm { font-size: 12px; }
.txt-mono { font-family: var(--mono); font-size: 12px; }
.fw-bold { font-weight: 700; }
.color-live { color: var(--live); }
.color-warn { color: var(--warn); }
.color-danger { color: var(--danger); }
.color-accent { color: var(--accent2); }
.color-cyan { color: var(--cyan); }
.empty-state { text-align: center; padding: 48px 20px; color: var(--muted); font-size: 13px; }
.pill { display: inline-block; background: var(--border); border-radius: 4px; padding: 2px 7px; font-size: 11px; font-family: var(--mono); color: var(--text); }

/* Btn */
.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border-radius: 7px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  border: none;
  outline: none;
  transition: opacity 0.15s, background 0.15s;
}
.btn-primary { background: var(--accent); color: #fff; }
.btn-ghost   { background: var(--border); color: var(--text); }
.btn:hover { opacity: 0.85; }

/* Error banner */
.error-banner {
  background: rgba(239,68,68,0.08);
  border: 1px solid rgba(239,68,68,0.2);
  border-radius: 8px;
  padding: 14px 18px;
  color: #fca5a5;
  font-size: 13px;
  margin-bottom: 24px;
}

/* Responsive */
@media (max-width: 900px) {
  .sidebar { width: 180px; min-width: 180px; }
  .main-content { margin-left: 180px; }
  .grid-2 { grid-template-columns: 1fr; }
  .grid-3 { grid-template-columns: 1fr 1fr; }
}

@media (max-width: 640px) {
  .sidebar { display: none; }
  .main-content { margin-left: 0; }
  .page-body { padding: 16px; }
  .topbar { padding: 12px 16px; }
  .grid-3 { grid-template-columns: 1fr; }
}
"""

# ── HTML Base ─────────────────────────────────────────────────────────────────

def base_html(page_id, title, body_content, extra_js=""):
    nav_items = [
        ("dashboard", "/",        "Dashboard",      """<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>"""),
        ("biomes",    "/biomes",  "Biome Tracker",  """<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>"""),
        ("stats",     "/stats",   "Statistics",     """<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>"""),
        ("webhook",   "/webhook", "Webhooks",       """<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 20V10M12 20V4M6 20v-6"/></svg>"""),
        ("apiv",      "/api",     "API Viewer",     """<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>"""),
    ]

    nav_html = '<nav class="sidebar-nav"><p class="nav-section">Navigation</p>'
    for pid, href, label, icon in nav_items:
        active = 'active' if pid == page_id else ''
        nav_html += f'<a class="nav-item {active}" href="{href}">{icon}{label}</a>'
    nav_html += "</nav>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — Fabled's Lair</title>
<style>{GLOBAL_CSS}</style>
</head>
<body>
<div class="layout">
  <aside class="sidebar">
    <div class="sidebar-brand">
      <div class="brand-name">Fabled's Lair</div>
      <div class="brand-sub">Snipe Tracker</div>
      <div class="sidebar-status"><span class="dot"></span> Live</div>
    </div>
    {nav_html}
    <div class="sidebar-footer">
      Data via <a href="{API_BASE}" target="_blank">API</a>
    </div>
  </aside>
  <div class="main-content">
    <div class="topbar">
      <span class="topbar-title">{title}</span>
      <div class="topbar-meta">
        <span id="last-update">—</span>
        <span class="badge badge-online">Online</span>
      </div>
    </div>
    <div class="page-body">
{body_content}
    </div>
  </div>
</div>
<script>
document.getElementById('last-update').textContent = 'Updated ' + new Date().toLocaleTimeString();
{extra_js}
</script>
</body>
</html>"""

# ── Page: Dashboard ───────────────────────────────────────────────────────────

@app.route("/")
def page_dashboard():
    data, err = fetch_metrics()

    if err or not data:
        body = f'<div class="error-banner">Unable to reach the tracking API: {err or "No data"}. The backend may be starting up — refresh in a moment.</div>'
        return render_template_string(base_html("dashboard", "Dashboard", body))

    t = data.get("telemetry", {})
    live_events = data.get("live_events", [])
    streams = data.get("active_webhook_streams", [])

    stats_html = f"""
<div class="stat-grid">
  <div class="stat-card live">
    <div class="stat-label">Live Events</div>
    <div class="stat-value">{t.get('active_live_events', 0)}</div>
    <div class="stat-sub">active right now</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Total Biomes</div>
    <div class="stat-value">{t.get('grand_total_biomes', 0):,}</div>
    <div class="stat-sub">all time detections</div>
  </div>
  <div class="stat-card warn">
    <div class="stat-label">Total Merchants</div>
    <div class="stat-value">{t.get('grand_total_merchants', 0):,}</div>
    <div class="stat-sub">all time detections</div>
  </div>
  <div class="stat-card cyan">
    <div class="stat-label">Active Feeds</div>
    <div class="stat-value">{t.get('active_webhooks_last_10m', 0)}<span style="font-size:16px;color:var(--muted)">/{t.get('total_registered_webhooks',0)}</span></div>
    <div class="stat-sub">last 10 minutes</div>
  </div>
  <div class="stat-card purple">
    <div class="stat-label">Tracked Channels</div>
    <div class="stat-value">{t.get('total_detected_channels', 0)}</div>
    <div class="stat-sub">auto-detected</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Uptime</div>
    <div class="stat-value" style="font-size:16px;padding-top:6px">{data.get('uptime','—')}</div>
    <div class="stat-sub">backend tracker</div>
  </div>
</div>"""

    # Live events
    live_html = '<p class="section-heading">Live Events</p>'
    if not live_events:
        live_html += '<div class="empty-state">No active events at this moment.</div>'
    else:
        for ev in live_events:
            etype = ev.get("type", "biome")
            ename = ev.get("name", "UNKNOWN")
            chan  = ev.get("channel_name", "—")
            acc   = ev.get("account_identity", "—")
            src   = ev.get("macro_source", "—")
            sa    = ev.get("started_at", "")
            ago   = time_ago(sa)
            started_fmt = sa[11:19] + " UTC" if len(sa) > 18 else "—"
            badge_cls = "badge-merchant" if etype == "merchant" else "badge-biome"
            card_cls  = "merchant" if etype == "merchant" else "biome"
            live_html += f"""
<div class="event-card {card_cls}">
  <div>
    <div class="event-name">{ename}</div>
    <div class="event-meta">
      <span class="badge {badge_cls}">{etype}</span>
      &nbsp; Channel: <span>{chan}</span>
      &nbsp; Account: <span>{acc}</span>
      &nbsp; Source: <span>{src}</span>
    </div>
  </div>
  <div class="event-right">
    <div class="timer-badge" data-started="{sa}">LIVE</div>
    <div class="txt-sm txt-muted mt-4">Since {started_fmt}<br>{ago}</div>
  </div>
</div>"""

    # Active streams summary
    streams_html = '<p class="section-heading mt-4">Active Webhook Feeds</p><div class="card card-sm">'
    if not streams:
        streams_html += '<div class="empty-state">No active feeds detected.</div>'
    else:
        for s in streams:
            last_m = s.get("last_seen_ago_mins", 0)
            color  = "var(--live)" if last_m < 3 else "var(--warn)" if last_m < 8 else "var(--danger)"
            streams_html += f"""
<div class="webhook-row">
  <div>
    <div class="webhook-name">{s['name']}</div>
    <div class="webhook-sub">{s.get('accounts_count',0)} accounts tracked</div>
  </div>
  <div class="txt-sm" style="color:{color};font-family:var(--mono);">{last_m:.1f}m ago</div>
</div>"""
    streams_html += "</div>"

    body = stats_html + live_html + streams_html

    js = """
function updateTimers() {
  document.querySelectorAll('[data-started]').forEach(function(el) {
    var s = el.getAttribute('data-started');
    if (!s) return;
    var started = new Date(s);
    var now = new Date();
    var sec = Math.floor((now - started) / 1000);
    var m = Math.floor(sec / 60), ss = sec % 60;
    el.textContent = m + 'm ' + (ss < 10 ? '0' : '') + ss + 's';
  });
}
updateTimers();
setInterval(updateTimers, 1000);
setTimeout(function(){ location.reload(); }, 30000);
"""
    return render_template_string(base_html("dashboard", "Dashboard", body, js))

# ── Page: Biome Tracker ───────────────────────────────────────────────────────

@app.route("/biomes")
def page_biomes():
    data, err = fetch_metrics()

    body = ""
    if err or not data:
        body = f'<div class="error-banner">Unable to reach API: {err}</div>'
        return render_template_string(base_html("biomes", "Biome Tracker", body))

    events = extract_event_history(data)
    # Also include live events at top
    live_events = data.get("live_events", [])

    rows = ""
    for ev in events:
        etype = ev.get("type", "biome")
        badge_cls = "badge-merchant" if etype == "merchant" else "badge-biome"
        rows += f"""<tr class="event-row" data-name="{ev['name']}" data-type="{etype}" data-source="{ev.get('macro_source','')}">
  <td class="fw-bold">{ev['name']}</td>
  <td><span class="badge {badge_cls}">{etype}</span></td>
  <td class="mono">{ev.get('at','—')[:19].replace('T',' ')}</td>
  <td class="mono">{ev.get('duration','—')}</td>
  <td class="txt-muted txt-sm">{ev.get('time_ago','—')}</td>
  <td class="txt-muted txt-sm">{ev.get('macro_source','—')}</td>
  <td class="txt-muted txt-sm" style="max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{ev.get('channel','—')}</td>
</tr>"""

    if not rows:
        rows = '<tr><td colspan="7" class="empty-state">No session history found yet.</td></tr>'

    live_count = len([e for e in events if True]) # total sessions
    biome_sess = len([e for e in events if e["type"] == "biome"])
    merch_sess = len([e for e in events if e["type"] == "merchant"])

    body = f"""
<div class="stat-grid" style="grid-template-columns:repeat(auto-fit,minmax(140px,1fr));margin-bottom:24px">
  <div class="stat-card"><div class="stat-label">Tracked Sessions</div><div class="stat-value">{live_count}</div></div>
  <div class="stat-card"><div class="stat-label">Biome Sessions</div><div class="stat-value">{biome_sess}</div></div>
  <div class="stat-card warn"><div class="stat-label">Merchant Sessions</div><div class="stat-value">{merch_sess}</div></div>
  <div class="stat-card live"><div class="stat-label">Live Now</div><div class="stat-value">{len(live_events)}</div></div>
</div>

<div class="controls-bar">
  <input class="search-bar" type="text" id="search-input" placeholder="Search biome name or source..." oninput="filterTable()">
  <select class="filter-select" id="type-filter" onchange="filterTable()">
    <option value="">All types</option>
    <option value="biome">Biome</option>
    <option value="merchant">Merchant</option>
  </select>
  <select class="filter-select" id="src-filter" onchange="filterTable()">
    <option value="">All sources</option>
    {''.join(f'<option value="{s}">{s}</option>' for s in sorted(set(e.get('macro_source','') for e in events if e.get('macro_source'))))}
  </select>
</div>

<div class="card" style="padding:0;overflow:auto">
  <table class="data-table" id="events-table">
    <thead>
      <tr>
        <th onclick="sortTable(0)" style="cursor:pointer">Name</th>
        <th>Type</th>
        <th onclick="sortTable(2)" style="cursor:pointer">Time</th>
        <th onclick="sortTable(3)" style="cursor:pointer">Duration</th>
        <th>Ago</th>
        <th>Source</th>
        <th>Channel</th>
      </tr>
    </thead>
    <tbody id="table-body">
      {rows}
    </tbody>
  </table>
</div>
<div class="txt-sm txt-muted mt-4" id="row-count">{live_count} sessions shown</div>
"""

    js = """
var sortDir = {};
function sortTable(col) {
  var tbody = document.getElementById('table-body');
  var rows  = Array.from(tbody.querySelectorAll('tr.event-row'));
  sortDir[col] = !sortDir[col];
  rows.sort(function(a, b) {
    var av = a.cells[col] ? a.cells[col].textContent.trim() : '';
    var bv = b.cells[col] ? b.cells[col].textContent.trim() : '';
    return sortDir[col] ? av.localeCompare(bv) : bv.localeCompare(av);
  });
  rows.forEach(function(r){ tbody.appendChild(r); });
}
function filterTable() {
  var q    = document.getElementById('search-input').value.toLowerCase();
  var type = document.getElementById('type-filter').value.toLowerCase();
  var src  = document.getElementById('src-filter').value.toLowerCase();
  var rows = document.querySelectorAll('#table-body tr.event-row');
  var vis  = 0;
  rows.forEach(function(r) {
    var name = (r.dataset.name || '').toLowerCase();
    var rtype = (r.dataset.type || '').toLowerCase();
    var rsrc  = (r.dataset.source || '').toLowerCase();
    var show  = (!q || name.includes(q) || rsrc.includes(q))
             && (!type || rtype === type)
             && (!src  || rsrc.includes(src));
    r.style.display = show ? '' : 'none';
    if (show) vis++;
  });
  var rc = document.getElementById('row-count');
  if (rc) rc.textContent = vis + ' sessions shown';
}
"""
    return render_template_string(base_html("biomes", "Biome Tracker", body, js))

# ── Page: Statistics ──────────────────────────────────────────────────────────

@app.route("/stats")
def page_stats():
    data, err = fetch_metrics()

    if err or not data:
        body = f'<div class="error-banner">Unable to reach API: {err}</div>'
        return render_template_string(base_html("stats", "Statistics", body))

    events = extract_event_history(data)
    s      = compute_statistics(data, events)

    # Biome bar chart
    biome_max = s["biome_sorted"][0][1] if s["biome_sorted"] else 1
    biome_bars = ""
    for name, cnt in s["biome_sorted"]:
        pct = int(cnt / biome_max * 100)
        biome_bars += f"""
<div class="bar-row">
  <div class="bar-label" title="{name}">{name}</div>
  <div class="bar-track"><div class="bar-fill" style="width:{pct}%"></div></div>
  <div class="bar-count">{cnt:,}</div>
</div>"""

    # Merchant bars
    merch_max  = s["merchant_sorted"][0][1] if s["merchant_sorted"] else 1
    merch_bars = ""
    for name, cnt in s["merchant_sorted"]:
        pct = int(cnt / merch_max * 100)
        merch_bars += f"""
<div class="bar-row">
  <div class="bar-label" title="{name}">{name}</div>
  <div class="bar-track"><div class="bar-fill warn" style="width:{pct}%"></div></div>
  <div class="bar-count">{cnt:,}</div>
</div>"""

    # Source bars
    src_max  = s["source_sorted"][0][1] if s["source_sorted"] else 1
    src_bars = ""
    for name, cnt in s["source_sorted"]:
        pct = int(cnt / src_max * 100)
        src_bars += f"""
<div class="bar-row">
  <div class="bar-label" title="{name}">{name}</div>
  <div class="bar-track"><div class="bar-fill cyan" style="width:{pct}%"></div></div>
  <div class="bar-count">{cnt}</div>
</div>"""

    body = f"""
<div class="stat-grid" style="margin-bottom:28px">
  <div class="stat-card">
    <div class="stat-label">Total Detections</div>
    <div class="stat-value">{s['total_events']:,}</div>
    <div class="stat-sub">biomes + merchants</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Most Common</div>
    <div class="stat-value" style="font-size:18px;padding-top:4px">{s['most_common']}</div>
    <div class="stat-sub">highest frequency biome</div>
  </div>
  <div class="stat-card cyan">
    <div class="stat-label">Avg Session</div>
    <div class="stat-value" style="font-size:20px;padding-top:4px">{s['avg_duration']}</div>
    <div class="stat-sub">from {s['session_count']} logged sessions</div>
  </div>
  <div class="stat-card live">
    <div class="stat-label">Longest Session</div>
    <div class="stat-value" style="font-size:20px;padding-top:4px">{s['longest']}</div>
  </div>
  <div class="stat-card warn">
    <div class="stat-label">Shortest Session</div>
    <div class="stat-value" style="font-size:20px;padding-top:4px">{s['shortest']}</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Logged Sessions</div>
    <div class="stat-value">{s['session_count']}</div>
    <div class="stat-sub">with full duration data</div>
  </div>
</div>

<div class="grid-2 mb-8">
  <div class="card">
    <p class="section-heading">Biome Detection Frequency</p>
    {biome_bars if biome_bars else '<div class="empty-state">No data</div>'}
  </div>
  <div class="card">
    <p class="section-heading">Merchant Detection Frequency</p>
    {merch_bars if merch_bars else '<div class="empty-state">No data</div>'}
  </div>
</div>

<div class="card mb-6" style="max-width:480px">
  <p class="section-heading">Source Breakdown (logged sessions)</p>
  {src_bars if src_bars else '<div class="empty-state">No data</div>'}
</div>
"""
    return render_template_string(base_html("stats", "Statistics", body))

# ── Page: Webhook Monitor ─────────────────────────────────────────────────────

@app.route("/webhook")
def page_webhook():
    data, err = fetch_metrics()

    if err or not data:
        body = f'<div class="error-banner">Unable to reach API: {err}</div>'
        return render_template_string(base_html("webhook", "Webhooks", body))

    t       = data.get("telemetry", {})
    streams = data.get("active_webhook_streams", [])
    registry = data.get("raw_webhook_registry", {})

    rows = ""
    now  = datetime.now(timezone.utc)
    for cid, reg in sorted(registry.items(), key=lambda x: x[1].get("name","")):
        name      = reg.get("name", "unknown")
        last_seen = reg.get("last_seen", "")
        total_msg = reg.get("total_messages", 0)
        accs      = reg.get("accounts", {})

        try:
            ls_dt   = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
            mins_ago = (now - ls_dt).total_seconds() / 60
            ls_fmt   = f"{mins_ago:.1f}m ago"
            if mins_ago < 10:
                status_badge = '<span class="badge badge-online">Active</span>'
            elif mins_ago < 60:
                status_badge = '<span class="badge badge-muted">Idle</span>'
            else:
                status_badge = '<span class="badge badge-offline">Stale</span>'
        except Exception:
            ls_fmt       = "—"
            status_badge = '<span class="badge badge-muted">Unknown</span>'

        completed = sum(len(a.get("completed_sessions", [])) for a in accs.values())
        rows += f"""<tr>
  <td class="fw-bold">{name}</td>
  <td>{status_badge}</td>
  <td class="mono">{total_msg:,}</td>
  <td class="mono">{len(accs)}</td>
  <td class="mono">{completed}</td>
  <td class="txt-muted txt-sm">{ls_fmt}</td>
  <td class="txt-muted txt-sm mono" style="font-size:10px">{cid}</td>
</tr>"""

    body = f"""
<div class="stat-grid" style="margin-bottom:24px">
  <div class="stat-card live">
    <div class="stat-label">Active Feeds</div>
    <div class="stat-value">{t.get('active_webhooks_last_10m',0)}</div>
    <div class="stat-sub">last 10 minutes</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Registered Channels</div>
    <div class="stat-value">{t.get('total_registered_webhooks',0)}</div>
  </div>
  <div class="stat-card cyan">
    <div class="stat-label">Detected Channels</div>
    <div class="stat-value">{t.get('total_detected_channels',0)}</div>
  </div>
</div>

<p class="section-heading">Webhook Channel Registry</p>
<div class="card" style="padding:0;overflow:auto">
  <table class="data-table">
    <thead><tr>
      <th>Channel Name</th>
      <th>Status</th>
      <th>Messages</th>
      <th>Accounts</th>
      <th>Sessions</th>
      <th>Last Seen</th>
      <th>Channel ID</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>
</div>
"""
    js = "setTimeout(function(){ location.reload(); }, 60000);"
    return render_template_string(base_html("webhook", "Webhooks", body, js))

# ── Page: API Viewer ──────────────────────────────────────────────────────────

@app.route("/api")
def page_api():
    data, err = fetch_metrics()

    if err or not data:
        json_str = json.dumps({"error": err or "No data"}, indent=2)
    else:
        json_str = json.dumps(data, indent=2, ensure_ascii=False)

    # Syntax-color the JSON (minimal, inline)
    import html as htmlmod
    colored = htmlmod.escape(json_str)
    colored = colored.replace('"status"', '<span style="color:#a78bfa">"status"</span>')

    body = f"""
<div class="mb-6" style="display:flex;align-items:center;gap:12px">
  <button class="btn btn-primary" onclick="copyJSON()">Copy JSON</button>
  <button class="btn btn-ghost" onclick="location.reload()">Refresh</button>
  <span class="txt-sm txt-muted">Source: <a href="{API_METRICS}" target="_blank">{API_METRICS}</a></span>
</div>
<div class="code-block" id="json-block">{colored}</div>
"""
    js = f"""
function copyJSON() {{
  navigator.clipboard.writeText({json.dumps(json_str)}).then(function(){{
    var btn = document.querySelector('.btn-primary');
    btn.textContent = 'Copied!';
    setTimeout(function(){{ btn.textContent = 'Copy JSON'; }}, 1500);
  }});
}}
setTimeout(function(){{ location.reload(); }}, 60000);
"""
    return render_template_string(base_html("apiv", "API Viewer", body, js))

# ── Proxy API endpoint (pass-through for CORS/convenience) ──────────────────

@app.route("/proxy/metrics")
def proxy_metrics():
    data, err = fetch_metrics()
    if err:
        return jsonify({"error": err}), 502
    return jsonify(data)

# ── Error handlers ────────────────────────────────────────────────────────────

@app.errorhandler(404)
def not_found(e):
    body = '<div class="empty-state" style="margin-top:80px"><div style="font-size:40px;font-weight:800;color:var(--border2)">404</div><div style="margin-top:12px">Page not found. <a href="/">Back to dashboard</a></div></div>'
    return render_template_string(base_html("", "Not Found", body)), 404

# ── Server Start ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
