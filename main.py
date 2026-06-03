import discord
from discord.ext import commands
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import logging
import re
import os
import json
import asyncio
import time
from datetime import datetime, timezone

# ============================================================
#  1. LOGGING — Real-time unbuffered, clean format
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S %p'
)

# ============================================================
#  2. GATEWAY INTENTS
# ============================================================
intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ============================================================
#  3. PERSISTENCE & AUTO-DETECT CONFIG
# ============================================================
DATA_STORE_PATH = "metrics_store.json"

AUTO_DETECT_CONTAINERS = {1501595856493740162, 1511360799996907710, 1509915924663238776}
dynamic_detected_channels = set()

# ============================================================
#  4. GLOBAL METRIC TRACKERS
# ============================================================
biome_counts     = {}
merchant_counts  = {}
webhook_activity = {}   # channel_id -> { name, last_seen, total_messages, accounts }
active_live_events = {} # event_key  -> { type, name, started_at, server, … }

# ============================================================
#  5. PRE-COMPILED HOT-PATH REGEX
# ============================================================
ROBLOX_LINK_RE = re.compile(r"https://www\.roblox\.com/share\?\S+")
BIOME_MATCH_RE = re.compile(r"(?:Biome\s+(?:Started|Ended)(?:\s*:\s*|\s*-\s*))([A-Z_]+)", re.IGNORECASE)
EVENT_START_RE = re.compile(r"\b(started|start|spawned|arrived|appeared|has arrived|is here)\b", re.IGNORECASE)
EVENT_END_RE   = re.compile(r"\b(ended|end|despawned|left|gone|has left|disappeared|expired|timed out)\b", re.IGNORECASE)

KNOWN_BIOMES   = ["SINGULARITY","GLITCHED","DREAMSPACE","CYBERSPACE","STARFALL",
                  "CORRUPTION","WINDY","SNOWY","RAINY","HELL","NORMAL","SAND"]
CLEAN_WORDS_RE = re.compile(r"\b[A-Z]{4,}\b")

# ============================================================
#  6. SESSION TIME MAP  (seconds)
# ============================================================
EVENT_SESSION_LIMITS = {
    # Standard Biomes
    "WINDY":        120,
    "SNOWY":        120,
    "RAINY":        120,
    "SAND STORM":   650,
    "HELL":         666,
    "STARFALL":     650,
    "HEAVEN":       240,
    "NULL":          99,
    # Rare Biomes
    "GLITCHED":     164,
    "DREAMSPACE":   192,
    "CYBERSPACE":   720,
    "SINGULARITY": 1200,
    # Merchants  ← must match exactly what merchant_name resolves to
    "MARI (MERCHANT)":       180,
    "JESTER (MERCHANT)":     180,
    "RIN (MERCHANT)":        180,
    "MYSTERIOUS MERCHANT":   180,
    "TRAVELING MERCHANT":    180,
    "MERCHANT":              180,
}

# ============================================================
#  7. BACKGROUND SAVE THROTTLE  (prevents hammering disk/API)
# ============================================================
_last_save_time   = 0.0
_last_backup_time = 0.0
SAVE_INTERVAL_S   = 15   # local disk: at most once every 15 s
BACKUP_INTERVAL_S = 60   # Discord cloud: at most once every 60 s

# ============================================================
#  8. HELPERS
# ============================================================
def calculate_macro_capacity(event_name: str, avg_action_time: int = 40, buffer_time: int = 15) -> str | int:
    """Theoretical max accounts a user can macro before session end."""
    total_seconds = EVENT_SESSION_LIMITS.get(event_name.upper())
    if total_seconds is None:
        return "Unknown"
    usable = total_seconds - buffer_time
    return max(0, usable // avg_action_time)


def _fmt_duration(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s}s"


def load_persisted_metrics():
    global biome_counts, merchant_counts, webhook_activity
    if os.path.exists(DATA_STORE_PATH):
        try:
            with open(DATA_STORE_PATH, 'r', encoding='utf-8') as f:
                stored = json.load(f)
                biome_counts    = stored.get("biomes", {})
                merchant_counts = stored.get("merchants", {})
                webhook_activity = stored.get("webhook_activity", {})
                logging.info(f"💾 LOCAL ENGINE: Restored metrics from {DATA_STORE_PATH}")
        except Exception as e:
            logging.error(f"⚠️ LOCAL ENGINE: Error reading cache: {e}")


def save_persisted_metrics():
    """Throttled — writes at most once every SAVE_INTERVAL_S seconds."""
    global _last_save_time
    now = time.monotonic()
    if now - _last_save_time < SAVE_INTERVAL_S:
        return
    _last_save_time = now
    try:
        payload = {"biomes": biome_counts, "merchants": merchant_counts, "webhook_activity": webhook_activity}
        with open(DATA_STORE_PATH, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logging.error(f"⚠️ LOCAL ENGINE: Failed writing to disk: {e}")


async def backup_state_to_discord_cloud():
    """Throttled — syncs at most once every BACKUP_INTERVAL_S seconds."""
    global _last_backup_time
    now = time.monotonic()
    if now - _last_backup_time < BACKUP_INTERVAL_S:
        return
    _last_backup_time = now

    state_channel_id = os.getenv("STATE_CHANNEL_ID")
    channel = None
    if state_channel_id:
        channel = bot.get_channel(int(state_channel_id))
    if not channel:
        for guild in bot.guilds:
            channel = discord.utils.get(guild.text_channels, name="telemetry-state-db")
            if channel:
                break

    if channel:
        try:
            payload = {
                "biomes": biome_counts,
                "merchants": merchant_counts,
                "webhook_activity": webhook_activity,
                "active_live_events": active_live_events,
            }
            temp_file = "cloud_backup.json"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)

            await channel.send(
                content=f"🔄 **Telemetry Cloud Backup** | `{datetime.now(timezone.utc).isoformat()}`",
                file=discord.File(temp_file),
            )
            logging.info("💾 CLOUD DATABASE: State synced to Discord storage channel.")
            try:
                os.remove(temp_file)
            except:
                pass
        except Exception as e:
            logging.error(f"⚠️ CLOUD DATABASE: Sync failed: {e}")


async def load_state_from_discord_cloud():
    global biome_counts, merchant_counts, webhook_activity, active_live_events
    state_channel_id = os.getenv("STATE_CHANNEL_ID")
    channel = None
    if state_channel_id:
        channel = bot.get_channel(int(state_channel_id))
    if not channel:
        for guild in bot.guilds:
            channel = discord.utils.get(guild.text_channels, name="telemetry-state-db")
            if channel:
                break

    if channel:
        try:
            logging.info("⚡ CLOUD DATABASE: Scanning history for latest backup…")
            async for message in channel.history(limit=25):
                if message.attachments:
                    for attachment in message.attachments:
                        if attachment.filename.endswith(".json"):
                            data_bytes = await attachment.read()
                            stored = json.loads(data_bytes.decode('utf-8'))
                            biome_counts        = stored.get("biomes", {})
                            merchant_counts     = stored.get("merchants", {})
                            webhook_activity    = stored.get("webhook_activity", {})
                            active_live_events  = stored.get("active_live_events", {})
                            logging.info("🎯 CLOUD DATABASE: Historical data restored from Discord Cloud Storage!")
                            return True
        except Exception as e:
            logging.error(f"⚠️ CLOUD DATABASE: Recovery error: {e}")
    return False


def get_metrics_payload():
    now = datetime.now(timezone.utc)
    total_webhooks        = len(webhook_activity)
    active_webhooks_count = 0
    active_streams_list   = []
    grand_total_biomes    = sum(biome_counts.values())
    grand_total_merchants = sum(merchant_counts.values())

    for cid, data in webhook_activity.items():
        last_seen_dt = datetime.fromisoformat(data["last_seen"])
        delta_mins   = (now - last_seen_dt).total_seconds() / 60.0
        if delta_mins <= 10.0:
            active_webhooks_count += 1
            active_streams_list.append({
                "channel_id":       cid,
                "name":             data["name"],
                "last_seen_ago_mins": round(delta_mins, 2),
                "accounts_count":   len(data.get("accounts", {})),
            })

    return {
        "status":    "ONLINE",
        "timestamp": now.isoformat(),
        "telemetry": {
            "total_registered_webhooks": total_webhooks,
            "active_webhooks_last_10m":  active_webhooks_count,
            "grand_total_biomes":        grand_total_biomes,
            "grand_total_merchants":     grand_total_merchants,
        },
        "counters": {"biomes": biome_counts, "merchants": merchant_counts},
        "live_events":            list(active_live_events.values()),
        "active_webhook_streams": active_streams_list,
        "raw_webhook_registry":   webhook_activity,
    }


# ============================================================
#  9. WEB SERVER — HTML Dashboard + JSON API
# ============================================================
class RenderHealthCheckHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        if self.path == '/api/metrics':
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type')
            self.end_headers()
            self.wfile.write(json.dumps(get_metrics_payload(), ensure_ascii=False, indent=2).encode('utf-8'))
            return

        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()

        data = get_metrics_payload()
        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta http-equiv="refresh" content="15">
    <title>Telemetry Hub — Multi-Account Dashboard</title>
    <style>
        :root {{
            --bg:      #070810;
            --surface: #0f1117;
            --card:    #161b27;
            --border:  #1e2535;
            --cyan:    #00e5ff;
            --purple:  #a78bfa;
            --amber:   #f59e0b;
            --red:     #ff2a6d;
            --green:   #00ffa3;
            --muted:   #5a6a80;
            --text:    #c5ccd8;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: var(--text); padding: 28px; }}
        .container {{ max-width: 1280px; margin: 0 auto; }}

        /* Header */
        header {{ display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border); padding-bottom: 16px; margin-bottom: 28px; }}
        header h1 {{ font-size: 22px; color: var(--cyan); letter-spacing: .5px; }}
        .badge-online {{ background: #0a2e1e; color: var(--green); border: 1px solid var(--green); padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: 700; letter-spacing: 1px; }}

        /* Stat grid */
        .stat-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 32px; }}
        .stat-card {{ background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 18px 20px; border-top: 3px solid var(--cyan); }}
        .stat-card.purple {{ border-top-color: var(--purple); }}
        .stat-card.amber  {{ border-top-color: var(--amber); }}
        .stat-card.red    {{ border-top-color: var(--red); }}
        .stat-label {{ font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: var(--muted); margin-bottom: 8px; }}
        .stat-val {{ font-size: 34px; font-weight: 800; color: #fff; }}

        /* Section */
        section {{ margin-bottom: 36px; }}
        section h2 {{ font-size: 13px; text-transform: uppercase; letter-spacing: 2px; color: var(--muted); margin-bottom: 14px; padding-bottom: 8px; border-bottom: 1px solid var(--border); }}

        /* Live event rows */
        .live-row {{ background: var(--card); border: 1px solid var(--border); border-left: 3px solid var(--red); border-radius: 8px; padding: 14px 18px; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center; }}
        .live-name {{ font-size: 16px; font-weight: 700; color: #fff; }}
        .live-meta {{ font-size: 12px; color: var(--muted); margin-top: 4px; }}
        .live-meta span {{ color: var(--cyan); }}
        .pulse-badge {{ background: var(--red); color: #fff; padding: 4px 10px; border-radius: 20px; font-size: 11px; font-weight: 700; animation: pulse 1.8s ease-in-out infinite; white-space: nowrap; }}
        @keyframes pulse {{ 0%,100% {{ opacity:.55; }} 50% {{ opacity:1; }} }}

        /* Webhook blocks */
        .webhook-block {{ background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 18px 20px; margin-bottom: 14px; }}
        .webhook-title {{ font-size: 15px; font-weight: 700; color: var(--cyan); display: flex; justify-content: space-between; margin-bottom: 12px; padding-bottom: 10px; border-bottom: 1px solid var(--border); }}
        .account-row {{ background: var(--surface); border-left: 3px solid var(--purple); border-radius: 6px; padding: 12px 14px; margin-top: 8px; font-size: 13px; }}
        .account-name {{ font-weight: 700; color: #fff; margin-bottom: 6px; }}
        .session-tag {{ display: inline-block; background: #1a2035; border: 1px solid var(--border); color: var(--cyan); padding: 3px 8px; border-radius: 4px; font-size: 11px; margin: 2px; }}
        .empty {{ color: var(--muted); font-style: italic; font-size: 13px; padding: 10px 0; }}
    </style>
</head>
<body>
<div class="container">
    <header>
        <h1>⚡ Multi-Account Telemetry Hub</h1>
        <span class="badge-online">● ONLINE</span>
    </header>

    <!-- Stat Cards -->
    <div class="stat-grid">
        <div class="stat-card purple">
            <div class="stat-label">✨ Grand Total Biomes</div>
            <div class="stat-val" style="color:var(--purple)">{data['telemetry']['grand_total_biomes']}</div>
        </div>
        <div class="stat-card amber">
            <div class="stat-label">🛒 Grand Total Merchants</div>
            <div class="stat-val" style="color:var(--amber)">{data['telemetry']['grand_total_merchants']}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">📡 Total Channels</div>
            <div class="stat-val">{data['telemetry']['total_registered_webhooks']}</div>
        </div>
        <div class="stat-card red">
            <div class="stat-label">🔴 Active Webhooks (10 min)</div>
            <div class="stat-val" style="color:var(--red)">{data['telemetry']['active_webhooks_last_10m']}</div>
        </div>
    </div>

    <!-- Live Events -->
    <section>
        <h2>🔴 Real-Time Active Sessions</h2>
"""
        if not data['live_events']:
            html += '<p class="empty">No active macro instances detected right now.</p>'
        else:
            for ev in data['live_events']:
                html += f"""
        <div class="live-row">
            <div>
                <div class="live-name">{ev['name']} <small style="color:var(--muted);font-weight:400;">({ev['type'].upper()})</small></div>
                <div class="live-meta">Channel: <span>#{ev['channel_name']}</span> &nbsp;|&nbsp; Account: <span>{ev.get('account_identity','Unknown')}</span></div>
            </div>
            <span class="pulse-badge">LIVE since {ev['started_at'][11:19]} UTC</span>
        </div>"""

        html += """
    </section>

    <!-- Channel Profiles -->
    <section>
        <h2>📡 Channel Macro Profiles & Session History</h2>
"""
        if not data['raw_webhook_registry']:
            html += '<p class="empty">No channel stream history recorded yet.</p>'
        else:
            for cid, reg in sorted(data['raw_webhook_registry'].items(), key=lambda x: x[1]['name']):
                accounts = reg.get("accounts", {})
                # FIX: Only show accounts that have at least one completed session (i.e. a merchant/biome actually arrived)
                active_accounts = {k: v for k, v in accounts.items() if v.get("completed_sessions")}
                html += f"""
        <div class="webhook-block">
            <div class="webhook-title">
                <span>#{reg['name']} <small style="color:var(--muted);font-weight:400;">({reg['total_messages']} frames)</small></span>
                <span style="font-size:12px;color:var(--muted);">Accounts with Activity: {len(active_accounts)}</span>
            </div>"""
                if not active_accounts:
                    html += '<p class="empty">Waiting for first event to complete…</p>'
                else:
                    for l_key, acc in active_accounts.items():
                        html += f"""
            <div class="account-row">
                <div class="account-name">{acc['display_name']} <small style="color:var(--muted);font-weight:400;font-size:11px;">({l_key[:28]}…)</small></div>
                <div>"""
                        history = acc.get("completed_sessions", [])
                        for sess in reversed(history):
                            html += f"<span class='session-tag'>{sess['name']}: {sess['duration']}</span>"
                        html += """
                </div>
            </div>"""
                html += "\n        </div>"

        html += """
    </section>
</div>
</body>
</html>"""
        self.wfile.write(html.encode('utf-8'))

    def log_message(self, format, *args):
        pass


def keep_alive():
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), RenderHealthCheckHandler)
    logging.info(f"WEB SERVER: Dashboard active on port {port}")
    server.serve_forever()


# ============================================================
#  10. BOT EVENTS
# ============================================================
@bot.event
async def on_ready():
    load_persisted_metrics()
    await load_state_from_discord_cloud()
    for guild in bot.guilds:
        for channel in guild.text_channels:
            if guild.id in AUTO_DETECT_CONTAINERS or (channel.category_id in AUTO_DETECT_CONTAINERS):
                dynamic_detected_channels.add(channel.id)
    logging.info(f"📡 AUTO-DETECT: Cached {len(dynamic_detected_channels)} text channels.")
    logging.info("✅ SYSTEM ONLINE — Discord Gateway connected. Tracking live. 🚀")


@bot.event
async def on_guild_channel_create(channel):
    if isinstance(channel, discord.TextChannel):
        if channel.guild.id in AUTO_DETECT_CONTAINERS or (channel.category_id in AUTO_DETECT_CONTAINERS):
            dynamic_detected_channels.add(channel.id)
            logging.info(f"📡 AUTO-DETECT: New channel #{channel.name} ({channel.id}) added to live filters.")


@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    start_processing_time = time.perf_counter()
    channel_name = message.channel.name.lower()
    missing_channel_whitelist = {
        1511359721632694363, 1511365304624877568,
        1511335720239759361, 1511362877322432792,
    }

    is_monitored_channel = (
        message.channel.id in missing_channel_whitelist
        or message.channel.id in dynamic_detected_channels
        or "webhook" in channel_name
    )
    if not is_monitored_channel:
        return

    cid_str  = str(message.channel.id)
    now_iso  = datetime.now(timezone.utc).isoformat()
    is_forwarder = False
    link_detection_vector = "None"

    # ── Build combined text (message + embeds + buttons) ──────────────
    combined_embed_text = message.content or ""
    if message.embeds:
        for embed in message.embeds:
            els = [embed.title or "", embed.description or ""]
            for f in embed.fields:
                els.extend([f.name or "", f.value or ""])
            combined_embed_text += " " + " ".join(els)

    if message.components:
        for row in message.components:
            for component in row.children:
                if hasattr(component, 'url') and component.url:
                    combined_embed_text += f" {component.url}"
                    link_detection_vector = "Interaction Button Component Link"

    link_match  = ROBLOX_LINK_RE.search(combined_embed_text)
    roblox_link = link_match.group(0) if link_match else None
    if roblox_link and link_detection_vector == "None":
        link_detection_vector = "Raw Message Text or Embed Block"

    # ── Update channel registry ────────────────────────────────────────
    if not is_forwarder:
        if cid_str not in webhook_activity:
            webhook_activity[cid_str] = {
                "name":           message.channel.name,
                "last_seen":      now_iso,
                "total_messages": 1,
                "accounts":       {},
            }
        else:
            webhook_activity[cid_str]["last_seen"]       = now_iso
            webhook_activity[cid_str]["total_messages"] += 1
            webhook_activity[cid_str].setdefault("accounts", {})

        # Register account by Roblox link, but DON'T surface it to the dashboard
        # until a completed session exists (handled in HTML rendering above).
        if roblox_link:
            acc_registry = webhook_activity[cid_str]["accounts"]
            if roblox_link not in acc_registry:
                assigned_index = len(acc_registry) + 1
                acc_registry[roblox_link] = {
                    "display_name":       f"Account {assigned_index}",
                    "biomes":             {},
                    "merchants":          {},
                    "completed_sessions": [],
                }
            account_identity = acc_registry[roblox_link]["display_name"]
        else:
            account_identity = "Account 1"
    else:
        account_identity = "Forwarder Source"

    # ── Only process embeds ───────────────────────────────────────────
    if not message.embeds:
        return

    for embed in message.embeds:
        text_elements = []
        if embed.title:                  text_elements.append(embed.title)
        if embed.description:            text_elements.append(embed.description)
        if embed.author and embed.author.name: text_elements.append(embed.author.name)
        for field in embed.fields:
            if field.name:  text_elements.append(field.name)
            if field.value: text_elements.append(field.value)

        combined_text       = " ".join(text_elements)
        combined_text_lower = combined_text.lower()

        is_start = bool(EVENT_START_RE.search(combined_text_lower))
        is_end   = bool(EVENT_END_RE.search(combined_text_lower))

        if is_end:
            print(f"DEBUG: END trigger detected → {combined_text_lower[:60]}")

        if not is_start and not is_end:
            continue

        guild_name = message.guild.name if message.guild else "Private Guild"

        is_merchant_event = (
            "merchant" in combined_text_lower
            or "mari"  in combined_text_lower
            or "jester" in combined_text_lower
            or "rin"   in combined_text_lower
        )

        # ════════════════════════════════════════════════════════════════
        #  MERCHANT BRANCH
        # ════════════════════════════════════════════════════════════════
        if is_merchant_event:
            if   "mysterious" in combined_text_lower: merchant_name = "MYSTERIOUS MERCHANT"
            elif "traveling"  in combined_text_lower: merchant_name = "TRAVELING MERCHANT"
            elif "mari"       in combined_text_lower: merchant_name = "MARI (MERCHANT)"
            elif "jester"     in combined_text_lower: merchant_name = "JESTER (MERCHANT)"
            elif "rin"        in combined_text_lower: merchant_name = "RIN (MERCHANT)"
            else:                                     merchant_name = "MERCHANT"

            event_type   = "SPAWNED" if is_start else "DESPAWNED"
            event_key    = f"{cid_str}_{account_identity}_{merchant_name}"
            duration_str = "N/A"
            target_key   = event_key
            found_start_event = None

            # Smart fallback: scan active events for same channel + merchant name
            if event_key in active_live_events:
                found_start_event = active_live_events[event_key]
            else:
                for k, ev in list(active_live_events.items()):
                    if k.startswith(f"{cid_str}_") and ev["name"] == merchant_name:
                        target_key   = k
                        found_start_event = ev
                        account_identity  = ev["account_identity"]
                        if ev["link"] != "None":
                            roblox_link           = ev["link"]
                            link_detection_vector = "Smart Historical Profile Match"
                        break

            if is_start:
                # FIX: Only increment merchant_counts on START (not on end).
                # This was already correct, but now we guard against duplicate starts.
                if event_key not in active_live_events:
                    merchant_counts[merchant_name] = merchant_counts.get(merchant_name, 0) + 1
                active_live_events[event_key] = {
                    "type":             "merchant",
                    "name":             merchant_name,
                    "started_at":       now_iso,
                    "server":           guild_name,
                    "channel_name":     message.channel.name,
                    "account_identity": account_identity,
                    "link":             roblox_link or "None",
                }
            else:  # is_end
                if found_start_event:
                    start_dt     = datetime.fromisoformat(found_start_event["started_at"])
                    delta_secs   = (datetime.now(timezone.utc) - start_dt).total_seconds()
                    duration_str = _fmt_duration(delta_secs)
                    active_live_events.pop(target_key, None)

                    # Persist completed session under the CORRECT account key
                    link_key = roblox_link or found_start_event.get("link")
                    if (not is_forwarder
                            and link_key
                            and link_key != "None"
                            and cid_str in webhook_activity
                            and link_key in webhook_activity[cid_str]["accounts"]):
                        webhook_activity[cid_str]["accounts"][link_key]["completed_sessions"].append({
                            "name":     merchant_name,
                            "duration": duration_str,
                            "at":       now_iso,
                        })
                else:
                    duration_str = "N/A (Start missed)"

            # Throttled saves — no more blocking on every message
            asyncio.get_event_loop().call_soon(
                lambda: asyncio.ensure_future(asyncio.to_thread(save_persisted_metrics))
            )
            asyncio.ensure_future(backup_state_to_discord_cloud())

            metrics        = get_metrics_payload()
            exec_ms        = (time.perf_counter() - start_processing_time) * 1000
            macro_capacity = calculate_macro_capacity(merchant_name)
            status_icon    = "🟢" if is_start else "🔴"

            print(f"\n🛒 [MERCHANT] {event_type} {status_icon}  |  {merchant_name}  |  {account_identity}")
            print(f"   ↳ Channel : #{message.channel.name}  ({guild_name})")
            if roblox_link:
                print(f"   ↳ Link    : {roblox_link}  [{link_detection_vector}]")
            print(f"   ↳ Capacity: {macro_capacity} accounts  (40s macro + 15s buffer)")
            print(f"   ↳ Duration: {duration_str}  |  ⚡ {exec_ms:.1f}ms  |  "
                  f"Active: {metrics['telemetry']['active_webhooks_last_10m']}/{metrics['telemetry']['total_registered_webhooks']}")
            print("─" * 80)

        # ════════════════════════════════════════════════════════════════
        #  BIOME BRANCH
        # ════════════════════════════════════════════════════════════════
        else:
            biome_match = BIOME_MATCH_RE.search(combined_text)
            if biome_match:
                biome_name = biome_match.group(1).upper()
            else:
                found_known = [b for b in KNOWN_BIOMES if b.lower() in combined_text_lower]
                if found_known:
                    biome_name = "SINGULARITY" if "SINGULARITY" in found_known else found_known[0]
                else:
                    words          = CLEAN_WORDS_RE.findall(combined_text)
                    filtered_words = [w for w in words if w not in {
                        "START","STARTED","ENDED","BIOME","TIME","INVITE","SERVER","PRIVATE","LINK"
                    }]
                    biome_name = filtered_words[0] if filtered_words else "UNKNOWN BIOME"

            if biome_name == "SAND":
                biome_name = "SAND STORM"

            event_type   = "STARTED" if is_start else "ENDED"
            event_key    = f"{cid_str}_{account_identity}_{biome_name}"
            duration_str = "N/A"
            target_key   = event_key
            found_start_event = None

            if event_key in active_live_events:
                found_start_event = active_live_events[event_key]
            else:
                for k, ev in list(active_live_events.items()):
                    if k.startswith(f"{cid_str}_") and ev["name"] == biome_name:
                        target_key   = k
                        found_start_event = ev
                        account_identity  = ev["account_identity"]
                        if ev["link"] != "None":
                            roblox_link           = ev["link"]
                            link_detection_vector = "Smart Historical Profile Match"
                        break

            if is_start:
                if event_key not in active_live_events:
                    biome_counts[biome_name] = biome_counts.get(biome_name, 0) + 1
                active_live_events[event_key] = {
                    "type":             "biome",
                    "name":             biome_name,
                    "started_at":       now_iso,
                    "server":           guild_name,
                    "channel_name":     message.channel.name,
                    "account_identity": account_identity,
                    "link":             roblox_link or "None",
                }
            else:
                if found_start_event:
                    start_dt     = datetime.fromisoformat(found_start_event["started_at"])
                    delta_secs   = (datetime.now(timezone.utc) - start_dt).total_seconds()
                    duration_str = _fmt_duration(delta_secs)
                    active_live_events.pop(target_key, None)

                    link_key = roblox_link or found_start_event.get("link")
                    if (not is_forwarder
                            and link_key
                            and link_key != "None"
                            and cid_str in webhook_activity
                            and link_key in webhook_activity[cid_str]["accounts"]):
                        acct_sessions = webhook_activity[cid_str]["accounts"][link_key]["completed_sessions"]
                        if len(acct_sessions) >= 10:
                            acct_sessions.pop(0)
                        acct_sessions.append({
                            "name":     biome_name,
                            "duration": duration_str,
                            "at":       now_iso,
                        })
                else:
                    duration_str = "N/A (Start missed)"

            asyncio.get_event_loop().call_soon(
                lambda: asyncio.ensure_future(asyncio.to_thread(save_persisted_metrics))
            )
            asyncio.ensure_future(backup_state_to_discord_cloud())

            metrics        = get_metrics_payload()
            exec_ms        = (time.perf_counter() - start_processing_time) * 1000
            macro_capacity = calculate_macro_capacity(biome_name)
            status_icon    = "🟢" if is_start else "🔴"

            print(f"\n🔮 [BIOME] {event_type} {status_icon}  |  {biome_name}  |  {account_identity}")
            print(f"   ↳ Channel : #{message.channel.name}  ({guild_name})")
            if roblox_link:
                print(f"   ↳ Link    : {roblox_link}  [{link_detection_vector}]")
            print(f"   ↳ Capacity: {macro_capacity} accounts  (40s macro + 15s buffer)")
            print(f"   ↳ Duration: {duration_str}  |  ⚡ {exec_ms:.1f}ms  |  "
                  f"Active: {metrics['telemetry']['active_webhooks_last_10m']}/{metrics['telemetry']['total_registered_webhooks']}")
            print("─" * 80)


# ============================================================
#  11. BOOT
# ============================================================
threading.Thread(target=keep_alive, daemon=True).start()

TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)
else:
    print("❌ Error: DISCORD_TOKEN environment variable not set.")
