# ════════════════════════════════════════════════════════════════════════════════
#  ZITE TELEMETRY BOT  —  Full Rewrite
#  Sections:
#   1.  Imports & Logging
#   2.  Intents & Bot
#   3.  Channel IDs & Config
#   4.  Global State
#   5.  Regex & Lookups
#   6.  Cosmetics (colors / emojis / tips)
#   7.  Core Helpers
#   8.  Persistence (local + cloud)
#   9.  Metrics Payload
#  10.  Embed Builders  (biome / merchant / departure / extended-log)
#  11.  Merchant Departure Watchdog
#  12.  Auto-Pin Error System
#  13.  website-output → embed-output Auto-Formatter
#  14.  Web Server (dashboard + /api/metrics)
#  15.  Core Message Processing
#  16.  DISCORD COMMANDS  (30+)
#  17.  Boot
# ════════════════════════════════════════════════════════════════════════════════

# ── 1. Imports & Logging ──────────────────────────────────────────────────────
import discord
from discord.ext import commands, tasks
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import logging
import re
import os
import json
import asyncio
import time
import platform
import psutil
from datetime import datetime, timezone, timedelta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S %p",
)
log = logging.getLogger(__name__)

BOT_START_TIME = datetime.now(timezone.utc)

# ── 2. Intents & Bot ──────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.messages        = True
intents.guilds          = True
intents.message_content = True
intents.members         = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# ── 3. Channel IDs & Config ───────────────────────────────────────────────────
DATA_STORE_PATH = "metrics_store.json"

# Detection containers (guilds / categories whose channels are auto-monitored)
AUTO_DETECT_CONTAINERS    = {1501595856493740162, 1511360799996907710, 1509915924663238776}
MISSING_CHANNEL_WHITELIST = {1511359721632694363, 1511365304624877568,
                              1511335720239759361, 1511362877322432792}
dynamic_detected_channels: set = set()

# Special output channels
EXTENDED_LOG_CHANNEL_ID  = 1512287503141306570   # website-output  (plain auto text)
CMD_CHANNEL_ID           = 1512289164786401500   # website-cmds    (bot commands)
EMBED_OUTPUT_CHANNEL_ID  = 1512290157179703426   # embed-output    (rich embeds)

MERCHANT_DEPART_CHANNEL_ID = os.getenv("MERCHANT_DEPART_CHANNEL_ID")
MERCHANT_WARN_BEFORE_S     = 30
_departure_warned: set     = set()

SAVE_INTERVAL_S   = 15
BACKUP_INTERVAL_S = 60

# ── 4. Global State ───────────────────────────────────────────────────────────
biome_counts:       dict  = {}
merchant_counts:    dict  = {}
webhook_activity:   dict  = {}
active_live_events: dict  = {}
_last_save_time:    float = 0.0
_last_backup_time:  float = 0.0

# ── 5. Regex & Lookups ────────────────────────────────────────────────────────
ROBLOX_LINK_RE = re.compile(r"https://www\.roblox\.com/share\?\S+")
BIOME_MATCH_RE = re.compile(
    r"(?:Biome\s+(?:Started|Ended)(?:\s*[:\-]\s*))([A-Z_]+)", re.IGNORECASE
)
EVENT_START_RE = re.compile(
    r"\b(started|start|spawned|arrived|appeared|has arrived|is here)\b", re.IGNORECASE
)
EVENT_END_RE = re.compile(
    r"\b(ended|end|despawned|left|gone|has left|disappeared|expired|timed out)\b",
    re.IGNORECASE,
)
CLEAN_WORDS_RE = re.compile(r"\b[A-Z]{4,}\b")

KNOWN_BIOMES = [
    "SINGULARITY","GLITCHED","DREAMSPACE","CYBERSPACE",
    "STARFALL","CORRUPTION","WINDY","SNOWY","RAINY","HELL","NORMAL","SAND",
]
STOP_WORDS = frozenset({
    "START","STARTED","ENDED","BIOME","TIME","INVITE",
    "SERVER","PRIVATE","LINK","WARNING",
})

EVENT_SESSION_LIMITS: dict = {
    "WINDY": 120, "SNOWY": 120, "RAINY": 120, "SAND STORM": 650,
    "HELL": 666, "STARFALL": 650, "HEAVEN": 240, "NULL": 99,
    "NORMAL": 60, "GLITCHED": 164, "DREAMSPACE": 192, "CYBERSPACE": 720,
    "SINGULARITY": 1200,
    "MARI (MERCHANT)": 180, "JESTER (MERCHANT)": 180, "RIN (MERCHANT)": 180,
    "MYSTERIOUS MERCHANT": 180, "TRAVELING MERCHANT": 180, "MERCHANT": 180,
}

# ── 6. Cosmetics ──────────────────────────────────────────────────────────────
BIOME_COLORS = {
    "SINGULARITY":0x9B59B6,"GLITCHED":0x00FF88,"DREAMSPACE":0xFF69B4,
    "CYBERSPACE":0x00E5FF,"STARFALL":0xFFD700,"CORRUPTION":0x8B0000,
    "WINDY":0xADD8E6,"SNOWY":0xE0F7FA,"RAINY":0x4682B4,"HELL":0xFF2A2A,
    "SAND STORM":0xC2A35A,"HEAVEN":0xFFFACD,"NORMAL":0x778899,
}
BIOME_EMOJIS = {
    "SINGULARITY":"🌀","GLITCHED":"⚠️","DREAMSPACE":"💤","CYBERSPACE":"🖥️",
    "STARFALL":"🌠","CORRUPTION":"☠️","WINDY":"💨","SNOWY":"❄️","RAINY":"🌧️",
    "HELL":"🔥","SAND STORM":"🏜️","HEAVEN":"☁️","NORMAL":"🌿","UNKNOWN":"❓",
}
MERCHANT_COLORS = {
    "MARI (MERCHANT)":0xFF69B4,"JESTER (MERCHANT)":0xFFA500,
    "RIN (MERCHANT)":0x00CED1,"MYSTERIOUS MERCHANT":0x6A0DAD,
    "TRAVELING MERCHANT":0x228B22,"MERCHANT":0xF59E0B,
}
MERCHANT_EMOJIS = {
    "MARI (MERCHANT)":"🌸","JESTER (MERCHANT)":"🃏","RIN (MERCHANT)":"🎐",
    "MYSTERIOUS MERCHANT":"🔮","TRAVELING MERCHANT":"🧳","MERCHANT":"🏪",
}
BIOME_TIPS = {
    "SINGULARITY":"Rarest biome — extremely high value. Queue **all** accounts immediately.",
    "GLITCHED":"Unstable terrain. Expect visual anomalies. High-yield loot window.",
    "DREAMSPACE":"Peaceful zone, moderate loot. Good for lower-priority accounts.",
    "CYBERSPACE":"12-minute window — longest standard biome. Maximise queue depth.",
    "STARFALL":"Shooting-star mechanic active. Watch for bonus drop events.",
    "CORRUPTION":"PvP-enabled zone. Prioritise accounts with defensive loadouts.",
    "WINDY":"Short 2-minute window. Fast-cycle accounts only.",
    "SNOWY":"Short 2-minute window. Fast-cycle accounts only.",
    "RAINY":"Short 2-minute window. Fast-cycle accounts only.",
    "HELL":"Exactly 11m 06s. High-damage environment — use tank builds.",
    "SAND STORM":"Extended ~10m window. Great for farming mid-tier resources.",
    "HEAVEN":"4-minute soft window. Peaceful, bonus XP multiplier.",
    "NORMAL":"Standard biome. Rotate accounts freely.",
}
MERCHANT_TIPS = {
    "MARI (MERCHANT)":"Mari stocks rare accessories. Prioritise accounts needing gear upgrades.",
    "JESTER (MERCHANT)":"Jester sells randomised bundles — high variance, potentially best value.",
    "RIN (MERCHANT)":"Rin offers crafting materials. Queue crafting-focused accounts first.",
    "MYSTERIOUS MERCHANT":"Unknown stock — high-priority, treat as top-tier spawn.",
    "TRAVELING MERCHANT":"Rotating inventory. Check stock before committing all accounts.",
    "MERCHANT":"Standard merchant. Queue accounts with available currency.",
}

# ── 7. Core Helpers ───────────────────────────────────────────────────────────

def calculate_macro_capacity(event_name: str, avg: int = 40, buf: int = 15):
    total = EVENT_SESSION_LIMITS.get(event_name.upper())
    if total is None:
        return "Unknown"
    return max(0, (total - buf) // avg)

def _fmt_duration(s: float) -> str:
    m, sec = divmod(int(s), 60)
    return f"{m}m {sec}s"

def _fmt_uptime(dt: datetime) -> str:
    delta = datetime.now(timezone.utc) - dt
    h, rem = divmod(int(delta.total_seconds()), 3600)
    m, s   = divmod(rem, 60)
    d      = h // 24
    h      = h % 24
    if d:
        return f"{d}d {h}h {m}m {s}s"
    return f"{h}h {m}m {s}s"

def _is_monitored(ch: discord.TextChannel) -> bool:
    if "webhook" in ch.name.lower():
        return True
    if ch.guild.id in AUTO_DETECT_CONTAINERS:
        return True
    if ch.category_id and ch.category_id in AUTO_DETECT_CONTAINERS:
        return True
    return False

def _register_channel(ch: discord.TextChannel) -> bool:
    if _is_monitored(ch) and ch.id not in dynamic_detected_channels:
        dynamic_detected_channels.add(ch.id)
        log.info(f"AUTO-DETECT: Registered #{ch.name} ({ch.id})")
        return True
    return False

def _get_state_channel():
    sid = os.getenv("STATE_CHANNEL_ID")
    if sid:
        c = bot.get_channel(int(sid))
        if c:
            return c
    for g in bot.guilds:
        c = discord.utils.get(g.text_channels, name="telemetry-state-db")
        if c:
            return c
    return None

def _get_extended_log_channel():
    return bot.get_channel(EXTENDED_LOG_CHANNEL_ID)

def _get_embed_output_channel():
    return bot.get_channel(EMBED_OUTPUT_CHANNEL_ID)

def _get_cmd_channel():
    return bot.get_channel(CMD_CHANNEL_ID)

def _is_cmd_channel(ctx) -> bool:
    return ctx.channel.id == CMD_CHANNEL_ID

def _active_webhook_count() -> int:
    now = datetime.now(timezone.utc)
    return sum(
        1 for d in webhook_activity.values()
        if (now - datetime.fromisoformat(d["last_seen"])).total_seconds() / 60 <= 10
    )

# ── 8. Persistence ────────────────────────────────────────────────────────────

def load_persisted_metrics():
    global biome_counts, merchant_counts, webhook_activity
    if not os.path.exists(DATA_STORE_PATH):
        return
    try:
        with open(DATA_STORE_PATH, "r", encoding="utf-8") as f:
            s = json.load(f)
        biome_counts     = s.get("biomes", {})
        merchant_counts  = s.get("merchants", {})
        webhook_activity = s.get("webhook_activity", {})
        log.info(f"LOCAL ENGINE: Restored from {DATA_STORE_PATH}")
    except Exception as e:
        log.error(f"LOCAL ENGINE: Cache read error: {e}")

def save_persisted_metrics():
    global _last_save_time
    now = time.monotonic()
    if now - _last_save_time < SAVE_INTERVAL_S:
        return
    _last_save_time = now
    try:
        with open(DATA_STORE_PATH, "w", encoding="utf-8") as f:
            json.dump(
                {"biomes": biome_counts, "merchants": merchant_counts,
                 "webhook_activity": webhook_activity},
                f, ensure_ascii=False, indent=2,
            )
    except Exception as e:
        log.error(f"LOCAL ENGINE: Write error: {e}")

async def backup_state_to_discord_cloud():
    global _last_backup_time
    now = time.monotonic()
    if now - _last_backup_time < BACKUP_INTERVAL_S:
        return
    _last_backup_time = now
    ch = _get_state_channel()
    if not ch:
        return
    try:
        payload = {
            "biomes": biome_counts, "merchants": merchant_counts,
            "webhook_activity": webhook_activity,
            "active_live_events": active_live_events,
        }
        tmp = "cloud_backup.json"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        await ch.send(
            content=f"☁️ **CLOUD BACKUP** | `{datetime.now(timezone.utc).isoformat()}`",
            file=discord.File(tmp),
        )
        log.info("CLOUD DATABASE: State synced.")
        try: os.remove(tmp)
        except: pass
    except Exception as e:
        log.error(f"CLOUD DATABASE: Sync failed: {e}")

async def load_state_from_discord_cloud():
    global biome_counts, merchant_counts, webhook_activity, active_live_events
    ch = _get_state_channel()
    if not ch:
        return False
    try:
        log.info("CLOUD DATABASE: Scanning history...")
        async for msg in ch.history(limit=25):
            for att in msg.attachments:
                if att.filename.endswith(".json"):
                    d = json.loads((await att.read()).decode("utf-8"))
                    biome_counts       = d.get("biomes", {})
                    merchant_counts    = d.get("merchants", {})
                    webhook_activity   = d.get("webhook_activity", {})
                    active_live_events = d.get("active_live_events", {})
                    log.info("CLOUD DATABASE: Restored!")
                    return True
    except Exception as e:
        log.error(f"CLOUD DATABASE: Recovery error: {e}")
    return False

# ── 9. Metrics Payload ────────────────────────────────────────────────────────

def get_metrics_payload() -> dict:
    now           = datetime.now(timezone.utc)
    active_count  = 0
    active_list   = []
    for cid, d in webhook_activity.items():
        delta = (now - datetime.fromisoformat(d["last_seen"])).total_seconds() / 60
        if delta <= 10:
            active_count += 1
            active_list.append({
                "channel_id": cid, "name": d["name"],
                "last_seen_ago_mins": round(delta, 2),
                "accounts_count": len(d.get("accounts", {})),
            })
    return {
        "status": "ONLINE",
        "timestamp": now.isoformat(),
        "uptime": _fmt_uptime(BOT_START_TIME),
        "telemetry": {
            "total_registered_webhooks": len(webhook_activity),
            "active_webhooks_last_10m":  active_count,
            "grand_total_biomes":        sum(biome_counts.values()),
            "grand_total_merchants":     sum(merchant_counts.values()),
            "total_detected_channels":   len(dynamic_detected_channels),
            "active_live_events":        len(active_live_events),
        },
        "counters": {"biomes": biome_counts, "merchants": merchant_counts},
        "live_events":            list(active_live_events.values()),
        "active_webhook_streams": active_list,
        "raw_webhook_registry":   webhook_activity,
        "config": {
            "auto_detect_containers":    list(AUTO_DETECT_CONTAINERS),
            "missing_channel_whitelist": list(MISSING_CHANNEL_WHITELIST),
            "dynamic_detected_channels": list(dynamic_detected_channels),
            "merchant_warn_before_s":    MERCHANT_WARN_BEFORE_S,
            "save_interval_s":           SAVE_INTERVAL_S,
            "backup_interval_s":         BACKUP_INTERVAL_S,
        },
    }

# ── 10. Embed Builders ────────────────────────────────────────────────────────

def _zite_footer(label: str) -> str:
    return f"Zite Telemetry  •  {label}  •  {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"

def _build_biome_embed(biome_name, event_type, channel_name, guild_name,
                       account_identity, roblox_link, link_vector,
                       duration_str, exec_ms, macro_capacity, metrics,
                       started_at=None) -> discord.Embed:
    is_start   = event_type == "STARTED"
    emoji      = BIOME_EMOJIS.get(biome_name, "❓")
    color      = BIOME_COLORS.get(biome_name, 0x778899) if is_start else 0x36393F
    session_s  = EVENT_SESSION_LIMITS.get(biome_name, 0)
    tip        = BIOME_TIPS.get(biome_name, "Monitor and rotate accounts as needed.")
    icon       = "🟢" if is_start else "🔴"

    embed = discord.Embed(
        title=f"{emoji}  BIOME {event_type}  —  {biome_name}",
        description=(
            f"{icon} **Biome is {'now ACTIVE' if is_start else 'ENDED'}**\n\n"
            f"**📋 Tactical Note:**\n> {tip}"
        ),
        color=color,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="📡 Channel",        value=f"`#{channel_name}`",     inline=True)
    embed.add_field(name="🖥️ Server",         value=f"`{guild_name}`",         inline=True)
    embed.add_field(name="👤 Account",        value=f"`{account_identity}`",   inline=True)
    embed.add_field(name="⏱️ Session Limit",  value=f"`{_fmt_duration(session_s)}`", inline=True)
    embed.add_field(name="🔄 Duration",       value=f"`{duration_str}`",       inline=True)
    embed.add_field(name="⚡ Latency",        value=f"`{exec_ms:.1f}ms`",      inline=True)
    embed.add_field(name="🧮 Macro Capacity", value=f"`{macro_capacity} accs` *(40s+15s buf)*", inline=True)
    embed.add_field(name="📊 Active Feeds",
                    value=f"`{metrics['telemetry']['active_webhooks_last_10m']}/{metrics['telemetry']['total_registered_webhooks']}`",
                    inline=True)
    embed.add_field(name="🌍 Total Biomes",   value=f"`{metrics['telemetry']['grand_total_biomes']}`", inline=True)
    if roblox_link and roblox_link != "None":
        embed.add_field(name="🔗 Server Link",
                        value=f"[**Join →**]({roblox_link}) *(via {link_vector})*", inline=False)
    if is_start and started_at:
        embed.add_field(name="🕐 Expiry ETA",
                        value=f"`{started_at[11:19]} UTC + {_fmt_duration(session_s)}`", inline=False)
    embed.set_footer(text=_zite_footer(f"Biome Engine  •  {biome_name}"))
    return embed

def _build_merchant_embed(merchant_name, event_type, channel_name, guild_name,
                          account_identity, roblox_link, link_vector,
                          duration_str, exec_ms, macro_capacity, metrics,
                          started_at=None) -> discord.Embed:
    is_start  = event_type == "SPAWNED"
    emoji     = MERCHANT_EMOJIS.get(merchant_name, "🏪")
    color     = MERCHANT_COLORS.get(merchant_name, 0xF59E0B) if is_start else 0x36393F
    session_s = EVENT_SESSION_LIMITS.get(merchant_name, 180)
    tip       = MERCHANT_TIPS.get(merchant_name, "Queue accounts with available currency.")
    icon      = "🟢" if is_start else "🔴"

    embed = discord.Embed(
        title=f"{emoji}  MERCHANT {event_type}  —  {merchant_name}",
        description=(
            f"{icon} **Merchant {'SPAWNED — 3-min window open!' if is_start else 'DESPAWNED'}**\n\n"
            f"**💡 Intel:** {tip}\n\n"
            f"**📋 Protocol:**\n"
            f"> **1.** Queue accounts — window is exactly 3 min.\n"
            f"> **2.** Max **{macro_capacity}** accounts *(40s+15s buf)*.\n"
            f"> **3.** No new interactions in final 30s.\n"
            f"> **4.** After despawn, shift to next active channel."
        ),
        color=color,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="📡 Channel",         value=f"`#{channel_name}`",    inline=True)
    embed.add_field(name="🖥️ Server",          value=f"`{guild_name}`",        inline=True)
    embed.add_field(name="👤 Account",         value=f"`{account_identity}`",  inline=True)
    embed.add_field(name="⏱️ Window",          value=f"`{_fmt_duration(session_s)}`", inline=True)
    embed.add_field(name="🔄 Duration",        value=f"`{duration_str}`",      inline=True)
    embed.add_field(name="⚡ Latency",         value=f"`{exec_ms:.1f}ms`",     inline=True)
    embed.add_field(name="🧮 Safe Capacity",   value=f"`{macro_capacity} accs`", inline=True)
    embed.add_field(name="📊 Active Feeds",
                    value=f"`{metrics['telemetry']['active_webhooks_last_10m']}/{metrics['telemetry']['total_registered_webhooks']}`",
                    inline=True)
    embed.add_field(name="🏪 Total Merchants", value=f"`{metrics['telemetry']['grand_total_merchants']}`", inline=True)
    if roblox_link and roblox_link != "None":
        embed.add_field(name="🔗 Server Link",
                        value=f"[**Join →**]({roblox_link}) *(via {link_vector})*", inline=False)
    if is_start and started_at:
        embed.add_field(name="⏰ Despawn ETA",
                        value=f"`{started_at[11:19]} UTC + {_fmt_duration(session_s)}` — warn at T-30s",
                        inline=False)
    embed.set_footer(text=_zite_footer(f"Merchant Engine  •  {merchant_name}"))
    return embed

def _build_departure_embed(merchant_name, channel_name, account_id,
                           spawn_link, seconds_left, macro_capacity) -> discord.Embed:
    emoji = MERCHANT_EMOJIS.get(merchant_name, "🏪")
    embed = discord.Embed(
        title=f"⚠️  MERCHANT DEPARTING — {emoji} {merchant_name}",
        description=(
            f"**{merchant_name}** leaves in **~{seconds_left}s**!\n\n"
            f"**🚨 Departure Protocol:**\n"
            f"> **1.** Finish current interaction — do NOT start a new one.\n"
            f"> **2.** ~{seconds_left}s remaining — act fast.\n"
            f"> **3.** After despawn, wait for next spawn. Do not chase.\n"
            f"> **4.** Max safe: **{macro_capacity} accounts** *(40s+15s buf)*.\n"
            f"> **5.** Mark channel done, shift queue.\n\n"
            f"*Merchants always depart at exactly 3 minutes.*"
        ),
        color=0xFF4500,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name=f"{emoji} Merchant",  value=f"`{merchant_name}`",  inline=True)
    embed.add_field(name="📡 Channel",         value=f"`#{channel_name}`",  inline=True)
    embed.add_field(name="👤 Account",         value=f"`{account_id}`",     inline=True)
    embed.add_field(name="⏳ Time Left",       value=f"`~{seconds_left}s`", inline=True)
    embed.add_field(name="🧮 Safe Capacity",   value=f"`{macro_capacity} accs`", inline=True)
    if spawn_link and spawn_link != "None":
        embed.add_field(name="🔗 Link", value=f"[Join]({spawn_link})", inline=True)
    embed.set_footer(text=_zite_footer("Departure Alert"))
    return embed

def _build_extended_biome_log(biome_name, event_type, channel_name, guild_name,
                               account_identity, roblox_link, link_vector,
                               duration_str, exec_ms, macro_capacity, metrics) -> discord.Embed:
    is_start = event_type == "STARTED"
    emoji    = BIOME_EMOJIS.get(biome_name, "❓")
    color    = BIOME_COLORS.get(biome_name, 0x778899) if is_start else 0x2C2F33
    ts       = datetime.now(timezone.utc).strftime("%H:%M:%S")
    icon     = "🟢" if is_start else "🔴"
    lines = [
        f"`{ts} UTC`  {icon}  **{biome_name}** — {event_type}",
        f"Channel `#{channel_name}` | Server `{guild_name}` | Account `{account_identity}`",
        f"Capacity `{macro_capacity} accs` | Duration `{duration_str}` | Latency `{exec_ms:.1f}ms`",
        f"Active Feeds `{metrics['telemetry']['active_webhooks_last_10m']}/{metrics['telemetry']['total_registered_webhooks']}` | Total Biomes `{metrics['telemetry']['grand_total_biomes']}`",
    ]
    if roblox_link and roblox_link != "None":
        lines.append(f"[🔗 Server Link]({roblox_link}) *(via {link_vector})*")
    embed = discord.Embed(
        title=f"{emoji} BIOME LOG  •  {biome_name}",
        description="\n".join(lines),
        color=color,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text=_zite_footer(f"Extended Log  •  {biome_name}"))
    return embed

def _build_extended_merchant_log(merchant_name, event_type, channel_name, guild_name,
                                  account_identity, roblox_link, link_vector,
                                  duration_str, exec_ms, macro_capacity, metrics) -> discord.Embed:
    is_start = event_type == "SPAWNED"
    emoji    = MERCHANT_EMOJIS.get(merchant_name, "🏪")
    color    = MERCHANT_COLORS.get(merchant_name, 0xF59E0B) if is_start else 0x2C2F33
    ts       = datetime.now(timezone.utc).strftime("%H:%M:%S")
    icon     = "🟢" if is_start else "🔴"
    lines = [
        f"`{ts} UTC`  {icon}  **{merchant_name}** — {event_type}",
        f"Channel `#{channel_name}` | Server `{guild_name}` | Account `{account_identity}`",
        f"Capacity `{macro_capacity} accs` | Duration `{duration_str}` | Latency `{exec_ms:.1f}ms`",
        f"Active Feeds `{metrics['telemetry']['active_webhooks_last_10m']}/{metrics['telemetry']['total_registered_webhooks']}` | Total Merchants `{metrics['telemetry']['grand_total_merchants']}`",
    ]
    if roblox_link and roblox_link != "None":
        lines.append(f"[🔗 Server Link]({roblox_link}) *(via {link_vector})*")
    embed = discord.Embed(
        title=f"{emoji} MERCHANT LOG  •  {merchant_name}",
        description="\n".join(lines),
        color=color,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text=_zite_footer(f"Extended Log  •  {merchant_name}"))
    return embed

def _build_plain_to_rich_embed(message: discord.Message) -> discord.Embed:
    """Convert a plain-text message from website-output into a rich embed."""
    content = message.content or ""
    is_error   = any(w in content.upper() for w in ("ERROR", "FAIL", "EXCEPTION", "CRITICAL", "TRACEBACK"))
    is_warning = any(w in content.upper() for w in ("WARNING", "WARN", "CAUTION"))
    is_success = any(w in content.upper() for w in ("SUCCESS", "SYNCED", "RESTORED", "ONLINE", "BACKUP"))

    if is_error:
        color, icon, label = 0xFF2A2A, "🔴", "ERROR"
    elif is_warning:
        color, icon, label = 0xF59E0B, "⚠️", "WARNING"
    elif is_success:
        color, icon, label = 0x00FFA3, "✅", "SUCCESS"
    else:
        color, icon, label = 0x00E5FF, "📋", "LOG"

    # Try to split into lines for field display
    lines = [l.strip() for l in content.strip().splitlines() if l.strip()]
    title_line = lines[0][:200] if lines else "Log Entry"
    body       = "\n".join(lines[1:])[:1000] if len(lines) > 1 else ""

    embed = discord.Embed(
        title=f"{icon}  {label}  —  {title_line}",
        description=f"```\n{body}\n```" if body else None,
        color=color,
        timestamp=message.created_at,
    )
    embed.add_field(name="📡 Source Channel", value=f"`#{message.channel.name}`", inline=True)
    embed.add_field(name="👤 Author",         value=f"`{message.author.display_name}`", inline=True)
    embed.add_field(name="🕐 Timestamp",      value=f"`{message.created_at.strftime('%H:%M:%S UTC')}`", inline=True)
    embed.set_footer(text=_zite_footer("Auto-Formatter  •  website-output → embed-output"))
    return embed

# ── 11. Merchant Departure Watchdog ──────────────────────────────────────────

async def send_merchant_departure_warning(event_key, ev, seconds_left):
    _departure_warned.add(event_key)
    merchant_name = ev["name"]
    ch_name       = ev.get("channel_name", "unknown")
    acc           = ev.get("account_identity", "Unknown")
    link          = ev.get("link", "None")
    cap           = calculate_macro_capacity(merchant_name)
    embed         = _build_departure_embed(merchant_name, ch_name, acc, link, seconds_left, cap)

    dest = None
    if MERCHANT_DEPART_CHANNEL_ID:
        dest = bot.get_channel(int(MERCHANT_DEPART_CHANNEL_ID))
    if not dest:
        for g in bot.guilds:
            for c in g.text_channels:
                if c.name == ch_name:
                    dest = c; break
            if dest: break

    coros = []
    if dest:
        coros.append(dest.send(embed=embed))
        log.info(f"DEPARTURE WARNING → #{dest.name} | {merchant_name} | ~{seconds_left}s")
    log_ch = _get_extended_log_channel()
    if log_ch:
        coros.append(log_ch.send(embed=embed))
    if coros:
        await asyncio.gather(*coros, return_exceptions=True)

@tasks.loop(seconds=5)
async def merchant_departure_watchdog():
    now = datetime.now(timezone.utc)
    for key, ev in list(active_live_events.items()):
        if ev.get("type") != "merchant" or key in _departure_warned:
            continue
        limit     = EVENT_SESSION_LIMITS.get(ev["name"].upper(), 180)
        elapsed   = (now - datetime.fromisoformat(ev["started_at"])).total_seconds()
        left      = limit - elapsed
        if left <= MERCHANT_WARN_BEFORE_S:
            await send_merchant_departure_warning(key, ev, max(0, int(left)))

@merchant_departure_watchdog.before_loop
async def _before_watchdog():
    await bot.wait_until_ready()

# ── 12. Auto-Pin Error System ─────────────────────────────────────────────────

async def maybe_auto_pin_error(message: discord.Message):
    """If message in website-output looks like an error, pin it."""
    content_up = (message.content or "").upper()
    if any(w in content_up for w in ("ERROR", "FAIL", "EXCEPTION", "CRITICAL", "TRACEBACK")):
        try:
            await message.pin()
            log.info(f"AUTO-PIN: Pinned error message {message.id} in #{message.channel.name}")
            # Notify embed-output
            embed_ch = _get_embed_output_channel()
            if embed_ch:
                e = discord.Embed(
                    title="📌  ERROR AUTO-PINNED",
                    description=(
                        f"An error message was automatically pinned in "
                        f"<#{EXTENDED_LOG_CHANNEL_ID}>.\n\n"
                        f"**Preview:**\n```\n{message.content[:300]}\n```"
                    ),
                    color=0xFF2A2A,
                    timestamp=datetime.now(timezone.utc),
                )
                e.add_field(name="Message ID", value=f"`{message.id}`", inline=True)
                e.add_field(name="Jump Link",  value=f"[Go to message]({message.jump_url})", inline=True)
                e.set_footer(text=_zite_footer("Auto-Pin System"))
                await embed_ch.send(embed=e)
        except discord.Forbidden:
            log.warning("AUTO-PIN: Missing Manage Messages permission.")
        except Exception as ex:
            log.error(f"AUTO-PIN: {ex}")

# ── 13. website-output → embed-output Auto-Formatter ─────────────────────────
# Handled inside on_message by checking channel ID

# ── 14. Web Server ────────────────────────────────────────────────────────────

def _build_dashboard_html() -> str:
    data = get_metrics_payload()
    t    = data["telemetry"]
    html = (
        "<!DOCTYPE html><html><head>"
        '<meta charset="utf-8">'
        '<meta http-equiv="refresh" content="15">'
        "<title>Zite Telemetry Hub</title>"
        "<style>"
        ":root{--bg:#070810;--surface:#0f1117;--card:#161b27;--border:#1e2535;"
        "--cyan:#00e5ff;--purple:#a78bfa;--amber:#f59e0b;--red:#ff2a6d;"
        "--green:#00ffa3;--muted:#5a6a80;--text:#c5ccd8}"
        "*{box-sizing:border-box;margin:0;padding:0}"
        "body{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--text);padding:28px}"
        ".container{max-width:1280px;margin:0 auto}"
        "header{display:flex;align-items:center;justify-content:space-between;"
        "border-bottom:1px solid var(--border);padding-bottom:16px;margin-bottom:28px}"
        "header h1{font-size:22px;color:var(--cyan)}"
        "header small{font-size:12px;color:var(--muted);margin-left:12px}"
        ".badge{background:#0a2e1e;color:var(--green);border:1px solid var(--green);"
        "padding:4px 12px;border-radius:20px;font-size:12px;font-weight:700}"
        ".stat-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:16px;margin-bottom:32px}"
        ".stat-card{background:var(--card);border:1px solid var(--border);border-radius:10px;"
        "padding:18px 20px;border-top:3px solid var(--cyan)}"
        ".stat-label{font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--muted);margin-bottom:8px}"
        ".stat-val{font-size:32px;font-weight:800;color:#fff}"
        "section{margin-bottom:36px}"
        "section h2{font-size:13px;text-transform:uppercase;letter-spacing:2px;color:var(--muted);"
        "margin-bottom:14px;padding-bottom:8px;border-bottom:1px solid var(--border)}"
        ".live-row{background:var(--card);border:1px solid var(--border);border-left:3px solid var(--red);"
        "border-radius:8px;padding:14px 18px;margin-bottom:10px;display:flex;justify-content:space-between;align-items:center}"
        ".live-name{font-size:16px;font-weight:700;color:#fff}"
        ".live-meta{font-size:12px;color:var(--muted);margin-top:4px}"
        ".live-meta span{color:var(--cyan)}"
        ".pulse-badge{background:var(--red);color:#fff;padding:4px 10px;border-radius:20px;"
        "font-size:11px;font-weight:700;animation:pulse 1.8s ease-in-out infinite;white-space:nowrap}"
        "@keyframes pulse{0%,100%{opacity:.55}50%{opacity:1}}"
        ".webhook-block{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:18px 20px;margin-bottom:14px}"
        ".webhook-title{font-size:15px;font-weight:700;color:var(--cyan);display:flex;"
        "justify-content:space-between;margin-bottom:12px;padding-bottom:10px;border-bottom:1px solid var(--border)}"
        ".account-row{background:var(--surface);border-left:3px solid var(--purple);"
        "border-radius:6px;padding:12px 14px;margin-top:8px;font-size:13px}"
        ".account-name{font-weight:700;color:#fff;margin-bottom:6px}"
        ".session-tag{display:inline-block;background:#1a2035;border:1px solid var(--border);"
        "color:var(--cyan);padding:3px 8px;border-radius:4px;font-size:11px;margin:2px}"
        ".empty{color:var(--muted);font-style:italic;font-size:13px;padding:10px 0}"
        ".biome-tag{display:inline-block;background:#0d1f2d;border:1px solid #1e3a52;"
        "color:var(--cyan);padding:4px 10px;border-radius:4px;font-size:12px;margin:3px}"
        ".merchant-tag{display:inline-block;background:#1f1a0d;border:1px solid #52421e;"
        "color:var(--amber);padding:4px 10px;border-radius:4px;font-size:12px;margin:3px}"
        "</style></head><body>"
        '<div class="container">'
        f'<header><h1>⚡ Zite Telemetry Hub <small>uptime: {data["uptime"]}</small></h1>'
        '<span class="badge">● ONLINE</span></header>'
        '<div class="stat-grid">'
        f'<div class="stat-card" style="border-top-color:var(--purple)"><div class="stat-label">Grand Total Biomes</div><div class="stat-val" style="color:var(--purple)">{t["grand_total_biomes"]}</div></div>'
        f'<div class="stat-card" style="border-top-color:var(--amber)"><div class="stat-label">Grand Total Merchants</div><div class="stat-val" style="color:var(--amber)">{t["grand_total_merchants"]}</div></div>'
        f'<div class="stat-card"><div class="stat-label">Total Channels</div><div class="stat-val">{t["total_registered_webhooks"]}</div></div>'
        f'<div class="stat-card" style="border-top-color:var(--red)"><div class="stat-label">Active Webhooks (10m)</div><div class="stat-val" style="color:var(--red)">{t["active_webhooks_last_10m"]}</div></div>'
        f'<div class="stat-card" style="border-top-color:var(--green)"><div class="stat-label">Detected Channels</div><div class="stat-val" style="color:var(--green)">{t["total_detected_channels"]}</div></div>'
        f'<div class="stat-card" style="border-top-color:var(--cyan)"><div class="stat-label">Live Events</div><div class="stat-val" style="color:var(--cyan)">{t["active_live_events"]}</div></div>'
        '</div>'
    )

    # Biome counters
    html += '<section><h2>📊 Biome Event Counters</h2>'
    if data["counters"]["biomes"]:
        for name, cnt in sorted(data["counters"]["biomes"].items(), key=lambda x: -x[1]):
            emoji = BIOME_EMOJIS.get(name, "❓")
            html += f'<span class="biome-tag">{emoji} {name}: {cnt}</span>'
    else:
        html += '<p class="empty">No biome data recorded yet.</p>'
    html += '</section>'

    # Merchant counters
    html += '<section><h2>🏪 Merchant Event Counters</h2>'
    if data["counters"]["merchants"]:
        for name, cnt in sorted(data["counters"]["merchants"].items(), key=lambda x: -x[1]):
            emoji = MERCHANT_EMOJIS.get(name, "🏪")
            html += f'<span class="merchant-tag">{emoji} {name}: {cnt}</span>'
    else:
        html += '<p class="empty">No merchant data recorded yet.</p>'
    html += '</section>'

    # Live events
    html += '<section><h2>🔴 Real-Time Active Sessions</h2>'
    if not data["live_events"]:
        html += '<p class="empty">No active macro instances detected right now.</p>'
    else:
        for ev in data["live_events"]:
            html += (
                f'<div class="live-row"><div>'
                f'<div class="live-name">{ev["name"]} <small style="color:var(--muted);font-weight:400;">({ev["type"].upper()})</small></div>'
                f'<div class="live-meta">Channel: <span>#{ev["channel_name"]}</span> &nbsp;|&nbsp; Account: <span>{ev.get("account_identity","Unknown")}</span></div>'
                f'</div><span class="pulse-badge">LIVE since {ev["started_at"][11:19]} UTC</span></div>'
            )
    html += '</section>'

    # Channel profiles
    html += '<section><h2>📡 Channel Macro Profiles &amp; Session History</h2>'
    if not data["raw_webhook_registry"]:
        html += '<p class="empty">No channel stream history recorded yet.</p>'
    else:
        for cid, reg in sorted(data["raw_webhook_registry"].items(), key=lambda x: x[1]["name"]):
            accounts        = reg.get("accounts", {})
            active_accounts = {k: v for k, v in accounts.items() if v.get("completed_sessions")}
            html += (
                f'<div class="webhook-block">'
                f'<div class="webhook-title">'
                f'<span>#{reg["name"]} <small style="color:var(--muted);font-weight:400;">({reg["total_messages"]} frames)</small></span>'
                f'<span style="font-size:12px;color:var(--muted);">Accounts: {len(active_accounts)}</span></div>'
            )
            if not active_accounts:
                html += '<p class="empty">Waiting for first completed event...</p>'
            else:
                for lk, acc in active_accounts.items():
                    html += f'<div class="account-row"><div class="account-name">{acc["display_name"]}</div><div>'
                    for sess in reversed(acc.get("completed_sessions", [])):
                        html += f'<span class="session-tag">{sess["name"]}: {sess["duration"]}</span>'
                    html += '</div></div>'
            html += '</div>'
    html += '</section></div></body></html>'
    return html

class RenderHealthCheckHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path == "/api/metrics":
            body = json.dumps(get_metrics_payload(), ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(_build_dashboard_html().encode("utf-8"))

    def log_message(self, fmt, *args):
        pass

def keep_alive():
    port   = int(os.getenv("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), RenderHealthCheckHandler)
    log.info(f"WEB SERVER: Dashboard active on port {port}")
    server.serve_forever()

# ── 15. Core Message Processing ───────────────────────────────────────────────

def _extract_combined_text(message: discord.Message):
    combined    = message.content or ""
    link_vector = "None"
    if message.embeds:
        for emb in message.embeds:
            parts = [emb.title or "", emb.description or ""]
            for f in emb.fields:
                parts += [f.name or "", f.value or ""]
            combined += " " + " ".join(parts)
    if message.components:
        for row in message.components:
            for comp in row.children:
                if hasattr(comp, "url") and comp.url:
                    combined    += f" {comp.url}"
                    link_vector  = "Interaction Button Component Link"
    m    = ROBLOX_LINK_RE.search(combined)
    link = m.group(0) if m else None
    if link and link_vector == "None":
        link_vector = "Raw Message Text or Embed Block"
    return combined, link, link_vector

def _identify_biome(combined_text, combined_lower):
    m = BIOME_MATCH_RE.search(combined_text)
    if m:
        return m.group(1).upper()
    found = [b for b in KNOWN_BIOMES if b.lower() in combined_lower]
    if found:
        return "SINGULARITY" if "SINGULARITY" in found else found[0]
    words    = CLEAN_WORDS_RE.findall(combined_text)
    filtered = [w for w in words if w not in STOP_WORDS]
    name     = filtered[0] if filtered else "UNKNOWN BIOME"
    if name == "SAND":        return "SAND STORM"
    if name in ("UNKNOWN BIOME", "UNKNOWN"): return "NORMAL"
    return name

def _identify_merchant(combined_lower):
    if "mysterious" in combined_lower: return "MYSTERIOUS MERCHANT"
    if "traveling"  in combined_lower: return "TRAVELING MERCHANT"
    if "mari"       in combined_lower: return "MARI (MERCHANT)"
    if "jester"     in combined_lower: return "JESTER (MERCHANT)"
    if "rin"        in combined_lower: return "RIN (MERCHANT)"
    return "MERCHANT"

def _resolve_active_event(cid_str, account_identity, event_name):
    key = f"{cid_str}_{account_identity}_{event_name}"
    if key in active_live_events:
        return key, active_live_events[key], account_identity
    for k, ev in list(active_live_events.items()):
        if k.startswith(f"{cid_str}_") and ev["name"] == event_name:
            return k, ev, ev["account_identity"]
    return key, None, account_identity

async def _dispatch_embeds(origin_ch, embed, log_embed):
    coros = [origin_ch.send(embed=embed)]
    log_ch = _get_extended_log_channel()
    if log_ch:
        coros.append(log_ch.send(embed=log_embed))
    embed_ch = _get_embed_output_channel()
    if embed_ch:
        coros.append(embed_ch.send(embed=log_embed))
    results = await asyncio.gather(*coros, return_exceptions=True)
    for r in results:
        if isinstance(r, Exception):
            log.error(f"Embed dispatch error: {r}")

async def _process_merchant(message, combined_lower, is_start, cid_str,
                            now_iso, guild_name, roblox_link, link_vector,
                            account_identity, is_forwarder, t0):
    merchant_name = _identify_merchant(combined_lower)
    event_type    = "SPAWNED" if is_start else "DESPAWNED"
    event_key, found_start, account_identity = _resolve_active_event(
        cid_str, account_identity, merchant_name)

    if found_start and found_start.get("link", "None") != "None":
        roblox_link = found_start["link"]
        link_vector = "Smart Historical Profile Match"

    duration_str = "N/A"

    if is_start:
        if event_key not in active_live_events:
            merchant_counts[merchant_name] = merchant_counts.get(merchant_name, 0) + 1
        active_live_events[event_key] = {
            "type": "merchant", "name": merchant_name, "started_at": now_iso,
            "server": guild_name, "channel_name": message.channel.name,
            "account_identity": account_identity, "link": roblox_link or "None",
        }
        _departure_warned.discard(event_key)
    else:
        target_key = event_key
        if found_start:
            for k, ev in list(active_live_events.items()):
                if k.startswith(f"{cid_str}_") and ev["name"] == merchant_name:
                    target_key = k; break
            delta_secs   = (datetime.now(timezone.utc) - datetime.fromisoformat(found_start["started_at"])).total_seconds()
            duration_str = _fmt_duration(delta_secs)
            active_live_events.pop(target_key, None)
            _departure_warned.discard(target_key)
            link_key = roblox_link or found_start.get("link")
            if (not is_forwarder and link_key and link_key != "None"
                    and cid_str in webhook_activity
                    and link_key in webhook_activity[cid_str]["accounts"]):
                webhook_activity[cid_str]["accounts"][link_key]["completed_sessions"].append(
                    {"name": merchant_name, "duration": duration_str, "at": now_iso})
        else:
            duration_str = "N/A (Start missed)"

    asyncio.ensure_future(asyncio.to_thread(save_persisted_metrics))
    asyncio.ensure_future(backup_state_to_discord_cloud())

    metrics        = get_metrics_payload()
    exec_ms        = (time.perf_counter() - t0) * 1000
    macro_capacity = calculate_macro_capacity(merchant_name)

    print(f"\n[MERCHANT] {event_type} | {merchant_name} | {account_identity}")
    print(f"   Channel : #{message.channel.name}  ({guild_name})")
    if roblox_link:
        print(f"   Link    : {roblox_link}  [{link_vector}]")
    print(f"   Capacity: {macro_capacity} accounts  (40s macro + 15s buffer)")
    print(f"   Duration: {duration_str}  | {exec_ms:.1f}ms | Active: {metrics['telemetry']['active_webhooks_last_10m']}/{metrics['telemetry']['total_registered_webhooks']}")
    print("-" * 80)

    started_at_val = active_live_events.get(event_key, {}).get("started_at", now_iso)
    embed = _build_merchant_embed(merchant_name, event_type, message.channel.name, guild_name,
                                  account_identity, roblox_link, link_vector, duration_str,
                                  exec_ms, macro_capacity, metrics, started_at=started_at_val)
    log_embed = _build_extended_merchant_log(merchant_name, event_type, message.channel.name, guild_name,
                                             account_identity, roblox_link, link_vector, duration_str,
                                             exec_ms, macro_capacity, metrics)
    await _dispatch_embeds(message.channel, embed, log_embed)

async def _process_biome(message, combined_text, combined_lower, is_start,
                         cid_str, now_iso, guild_name, roblox_link, link_vector,
                         account_identity, is_forwarder, t0):
    biome_name = _identify_biome(combined_text, combined_lower)
    event_type = "STARTED" if is_start else "ENDED"
    event_key, found_start, account_identity = _resolve_active_event(
        cid_str, account_identity, biome_name)

    if found_start and found_start.get("link", "None") != "None":
        roblox_link = found_start["link"]
        link_vector = "Smart Historical Profile Match"

    duration_str = "N/A"

    if is_start:
        if event_key not in active_live_events:
            biome_counts[biome_name] = biome_counts.get(biome_name, 0) + 1
        active_live_events[event_key] = {
            "type": "biome", "name": biome_name, "started_at": now_iso,
            "server": guild_name, "channel_name": message.channel.name,
            "account_identity": account_identity, "link": roblox_link or "None",
        }
    else:
        target_key = event_key
        if found_start:
            for k, ev in list(active_live_events.items()):
                if k.startswith(f"{cid_str}_") and ev["name"] == biome_name:
                    target_key = k; break
            delta_secs   = (datetime.now(timezone.utc) - datetime.fromisoformat(found_start["started_at"])).total_seconds()
            duration_str = _fmt_duration(delta_secs)
            active_live_events.pop(target_key, None)
            link_key = roblox_link or found_start.get("link")
            if (not is_forwarder and link_key and link_key != "None"
                    and cid_str in webhook_activity
                    and link_key in webhook_activity[cid_str]["accounts"]):
                sessions = webhook_activity[cid_str]["accounts"][link_key]["completed_sessions"]
                if len(sessions) >= 10:
                    sessions.pop(0)
                sessions.append({"name": biome_name, "duration": duration_str, "at": now_iso})
        else:
            duration_str = "N/A (Start missed)"

    asyncio.ensure_future(asyncio.to_thread(save_persisted_metrics))
    asyncio.ensure_future(backup_state_to_discord_cloud())

    metrics        = get_metrics_payload()
    exec_ms        = (time.perf_counter() - t0) * 1000
    macro_capacity = calculate_macro_capacity(biome_name)

    print(f"\n[BIOME] {event_type} | {biome_name} | {account_identity}")
    print(f"   Channel : #{message.channel.name}  ({guild_name})")
    if roblox_link:
        print(f"   Link    : {roblox_link}  [{link_vector}]")
    print(f"   Capacity: {macro_capacity} accounts  (40s macro + 15s buffer)")
    print(f"   Duration: {duration_str}  | {exec_ms:.1f}ms | Active: {metrics['telemetry']['active_webhooks_last_10m']}/{metrics['telemetry']['total_registered_webhooks']}")
    print("-" * 80)

    started_at_val = active_live_events.get(event_key, {}).get("started_at", now_iso)
    embed = _build_biome_embed(biome_name, event_type, message.channel.name, guild_name,
                               account_identity, roblox_link, link_vector, duration_str,
                               exec_ms, macro_capacity, metrics, started_at=started_at_val)
    log_embed = _build_extended_biome_log(biome_name, event_type, message.channel.name, guild_name,
                                          account_identity, roblox_link, link_vector, duration_str,
                                          exec_ms, macro_capacity, metrics)
    await _dispatch_embeds(message.channel, embed, log_embed)

# ── 16. DISCORD COMMANDS ──────────────────────────────────────────────────────

def _cmd_guard(ctx):
    """Returns True if command should be processed (only in website-cmds)."""
    return ctx.channel.id == CMD_CHANNEL_ID

# ─────────────────────────── SYSTEM / UPTIME ──────────────────────────────────

@bot.command(name="uptime", aliases=["up"])
async def cmd_uptime(ctx):
    """Show bot + Render uptime."""
    if not _cmd_guard(ctx): return
    delta   = datetime.now(timezone.utc) - BOT_START_TIME
    uptime  = _fmt_uptime(BOT_START_TIME)
    try:
        mem  = psutil.Process().memory_info().rss / 1024 / 1024
        cpu  = psutil.cpu_percent(interval=0.2)
    except Exception:
        mem = cpu = 0
    embed = discord.Embed(title="⏱️  Bot & Render Uptime", color=0x00E5FF,
                          timestamp=datetime.now(timezone.utc))
    embed.add_field(name="🟢 Uptime",         value=f"`{uptime}`",             inline=True)
    embed.add_field(name="🚀 Started At",     value=f"`{BOT_START_TIME.strftime('%Y-%m-%d %H:%M:%S UTC')}`", inline=True)
    embed.add_field(name="💾 Memory Usage",   value=f"`{mem:.1f} MB`",          inline=True)
    embed.add_field(name="⚙️ CPU",            value=f"`{cpu:.1f}%`",            inline=True)
    embed.add_field(name="🐍 Python",         value=f"`{platform.python_version()}`", inline=True)
    embed.add_field(name="📦 discord.py",     value=f"`{discord.__version__}`", inline=True)
    embed.set_footer(text=_zite_footer("System"))
    await ctx.send(embed=embed)

@bot.command(name="status", aliases=["sys"])
async def cmd_status(ctx):
    """Full system status snapshot."""
    if not _cmd_guard(ctx): return
    m   = get_metrics_payload()
    t   = m["telemetry"]
    try:
        mem = psutil.Process().memory_info().rss / 1024 / 1024
        cpu = psutil.cpu_percent(interval=0.2)
    except Exception:
        mem = cpu = 0
    embed = discord.Embed(title="📊  System Status", color=0x00FFA3,
                          timestamp=datetime.now(timezone.utc))
    embed.add_field(name="🟢 Status",             value="`ONLINE`",                             inline=True)
    embed.add_field(name="⏱️ Uptime",             value=f"`{m['uptime']}`",                     inline=True)
    embed.add_field(name="💾 RAM",                value=f"`{mem:.1f} MB`",                      inline=True)
    embed.add_field(name="📡 Total Channels",     value=f"`{t['total_registered_webhooks']}`",  inline=True)
    embed.add_field(name="🔴 Active (10m)",       value=f"`{t['active_webhooks_last_10m']}`",   inline=True)
    embed.add_field(name="🔎 Detected Channels",  value=f"`{t['total_detected_channels']}`",    inline=True)
    embed.add_field(name="🌍 Total Biomes",       value=f"`{t['grand_total_biomes']}`",         inline=True)
    embed.add_field(name="🏪 Total Merchants",    value=f"`{t['grand_total_merchants']}`",       inline=True)
    embed.add_field(name="⚡ Live Events",        value=f"`{t['active_live_events']}`",          inline=True)
    embed.set_footer(text=_zite_footer("System Status"))
    await ctx.send(embed=embed)

@bot.command(name="ping")
async def cmd_ping(ctx):
    """Bot latency."""
    if not _cmd_guard(ctx): return
    latency = round(bot.latency * 1000)
    color   = 0x00FFA3 if latency < 100 else (0xF59E0B if latency < 300 else 0xFF2A2A)
    embed   = discord.Embed(title="🏓  Pong!", color=color)
    embed.add_field(name="Gateway Latency", value=f"`{latency}ms`", inline=True)
    embed.set_footer(text=_zite_footer("Ping"))
    await ctx.send(embed=embed)

# ──────────────────────────── WEBHOOKS ────────────────────────────────────────

@bot.command(name="webhooks", aliases=["wh"])
async def cmd_webhooks(ctx):
    """Total webhooks registered + active count."""
    if not _cmd_guard(ctx): return
    total  = len(webhook_activity)
    active = _active_webhook_count()
    embed  = discord.Embed(title="📡  Webhook Overview", color=0x00E5FF,
                           timestamp=datetime.now(timezone.utc))
    embed.add_field(name="📦 Total Registered", value=f"`{total}`",  inline=True)
    embed.add_field(name="🟢 Active (10m)",     value=f"`{active}`", inline=True)
    embed.add_field(name="🔴 Inactive",         value=f"`{total - active}`", inline=True)
    embed.set_footer(text=_zite_footer("Webhooks"))
    await ctx.send(embed=embed)

@bot.command(name="webhooklist", aliases=["whlist"])
async def cmd_webhook_list(ctx):
    """List all registered webhook channels with last-seen time."""
    if not _cmd_guard(ctx): return
    now = datetime.now(timezone.utc)
    if not webhook_activity:
        await ctx.send(embed=discord.Embed(description="No webhooks registered yet.", color=0x36393F))
        return
    lines = []
    for cid, d in sorted(webhook_activity.items(), key=lambda x: x[1]["name"]):
        delta_m = (now - datetime.fromisoformat(d["last_seen"])).total_seconds() / 60
        status  = "🟢" if delta_m <= 10 else "🔴"
        lines.append(f"{status} `#{d['name']}` — {len(d.get('accounts',{}))} accs — seen {delta_m:.1f}m ago")
    # paginate if needed (Discord limit ~4096 chars)
    chunks = []
    chunk  = []
    for l in lines:
        if sum(len(x) for x in chunk) + len(l) > 3800:
            chunks.append(chunk); chunk = []
        chunk.append(l)
    if chunk: chunks.append(chunk)
    for i, ch in enumerate(chunks):
        embed = discord.Embed(
            title=f"📡  Webhook Channel List  ({i+1}/{len(chunks)})",
            description="\n".join(ch), color=0x00E5FF,
            timestamp=datetime.now(timezone.utc))
        embed.set_footer(text=_zite_footer("Webhooks"))
        await ctx.send(embed=embed)

@bot.command(name="webhookinfo", aliases=["whinfo"])
async def cmd_webhook_info(ctx, *, channel_name: str):
    """Detailed info about a specific webhook channel: !webhookinfo channel-name"""
    if not _cmd_guard(ctx): return
    target = None
    for cid, d in webhook_activity.items():
        if d["name"].lower() == channel_name.lower().lstrip("#"):
            target = (cid, d); break
    if not target:
        await ctx.send(embed=discord.Embed(description=f"❌ No webhook found for `#{channel_name}`.", color=0xFF2A2A))
        return
    cid, d    = target
    now       = datetime.now(timezone.utc)
    delta_m   = (now - datetime.fromisoformat(d["last_seen"])).total_seconds() / 60
    accounts  = d.get("accounts", {})
    total_ses = sum(len(a.get("completed_sessions", [])) for a in accounts.values())
    embed     = discord.Embed(title=f"📡  #{d['name']} — Webhook Detail", color=0x00E5FF,
                              timestamp=datetime.now(timezone.utc))
    embed.add_field(name="Channel ID",       value=f"`{cid}`",               inline=True)
    embed.add_field(name="Total Frames",     value=f"`{d['total_messages']}`",inline=True)
    embed.add_field(name="Last Seen",        value=f"`{delta_m:.1f}m ago`",   inline=True)
    embed.add_field(name="Status",           value="`🟢 Active`" if delta_m <= 10 else "`🔴 Idle`", inline=True)
    embed.add_field(name="Accounts Tracked", value=f"`{len(accounts)}`",      inline=True)
    embed.add_field(name="Total Sessions",   value=f"`{total_ses}`",          inline=True)
    # List each account
    for lk, acc in list(accounts.items())[:8]:
        sessions_preview = ", ".join(
            f"{s['name']}({s['duration']})" for s in acc.get("completed_sessions", [])[-3:]
        ) or "None yet"
        embed.add_field(
            name=f"👤 {acc['display_name']}",
            value=f"Sessions: `{len(acc.get('completed_sessions',[]))}`\nLast 3: `{sessions_preview}`",
            inline=False,
        )
    embed.set_footer(text=_zite_footer("Webhook Info"))
    await ctx.send(embed=embed)

@bot.command(name="webhookaccounts", aliases=["whacc"])
async def cmd_webhook_accounts(ctx, *, channel_name: str):
    """List all tracked accounts in a webhook channel."""
    if not _cmd_guard(ctx): return
    target = None
    for cid, d in webhook_activity.items():
        if d["name"].lower() == channel_name.lower().lstrip("#"):
            target = (cid, d); break
    if not target:
        await ctx.send(embed=discord.Embed(description=f"❌ Not found: `#{channel_name}`.", color=0xFF2A2A))
        return
    cid, d   = target
    accounts = d.get("accounts", {})
    if not accounts:
        await ctx.send(embed=discord.Embed(description="No accounts tracked yet.", color=0x36393F))
        return
    lines = []
    for lk, acc in accounts.items():
        sess_count = len(acc.get("completed_sessions", []))
        lines.append(f"**{acc['display_name']}** — `{sess_count}` sessions")
    embed = discord.Embed(title=f"👤  Accounts in #{d['name']}",
                          description="\n".join(lines), color=0xA78BFA,
                          timestamp=datetime.now(timezone.utc))
    embed.set_footer(text=_zite_footer("Webhook Accounts"))
    await ctx.send(embed=embed)

# ────────────────────────── CHANNELS ─────────────────────────────────────────

@bot.command(name="channels", aliases=["ch"])
async def cmd_channels(ctx):
    """Total detected channel count breakdown."""
    if not _cmd_guard(ctx): return
    embed = discord.Embed(title="🔎  Detected Channels Overview", color=0x00FFA3,
                          timestamp=datetime.now(timezone.utc))
    embed.add_field(name="🔎 Auto-Detected",      value=f"`{len(dynamic_detected_channels)}`",  inline=True)
    embed.add_field(name="📋 Whitelist (static)",  value=f"`{len(MISSING_CHANNEL_WHITELIST)}`",  inline=True)
    embed.add_field(name="📦 Container Guilds",    value=f"`{len(AUTO_DETECT_CONTAINERS)}`",     inline=True)
    embed.add_field(name="📡 Webhook Registry",    value=f"`{len(webhook_activity)}`",           inline=True)
    embed.add_field(name="🔴 Active (10m)",        value=f"`{_active_webhook_count()}`",         inline=True)
    embed.set_footer(text=_zite_footer("Channel Overview"))
    await ctx.send(embed=embed)

@bot.command(name="channellist", aliases=["chlist"])
async def cmd_channel_list(ctx):
    """List every auto-detected channel ID and name."""
    if not _cmd_guard(ctx): return
    lines = []
    for cid in sorted(dynamic_detected_channels):
        ch = bot.get_channel(cid)
        name = f"#{ch.name}" if ch else "Unknown"
        lines.append(f"`{cid}` — {name}")
    if not lines:
        lines = ["No channels auto-detected yet."]
    embed = discord.Embed(title="🔎  Auto-Detected Channels",
                          description="\n".join(lines[:30]), color=0x00FFA3,
                          timestamp=datetime.now(timezone.utc))
    embed.set_footer(text=_zite_footer("Channel List"))
    await ctx.send(embed=embed)

@bot.command(name="channelinfo", aliases=["chinfo"])
async def cmd_channel_info(ctx, channel: discord.TextChannel = None):
    """Info about a specific channel: !channelinfo #channel"""
    if not _cmd_guard(ctx): return
    ch = channel or ctx.channel
    cid_str = str(ch.id)
    wh_data = webhook_activity.get(cid_str)
    in_detected   = ch.id in dynamic_detected_channels
    in_whitelist  = ch.id in MISSING_CHANNEL_WHITELIST
    in_container  = ch.guild.id in AUTO_DETECT_CONTAINERS
    embed = discord.Embed(title=f"📡  Channel Info — #{ch.name}", color=0x00E5FF,
                          timestamp=datetime.now(timezone.utc))
    embed.add_field(name="Channel ID",      value=f"`{ch.id}`",            inline=True)
    embed.add_field(name="Category",        value=f"`{ch.category}`",      inline=True)
    embed.add_field(name="Guild",           value=f"`{ch.guild.name}`",    inline=True)
    embed.add_field(name="Auto-Detected",   value="✅" if in_detected else "❌", inline=True)
    embed.add_field(name="Whitelisted",     value="✅" if in_whitelist else "❌", inline=True)
    embed.add_field(name="Container Guild", value="✅" if in_container else "❌", inline=True)
    if wh_data:
        now      = datetime.now(timezone.utc)
        delta_m  = (now - datetime.fromisoformat(wh_data["last_seen"])).total_seconds() / 60
        embed.add_field(name="Total Frames",   value=f"`{wh_data['total_messages']}`", inline=True)
        embed.add_field(name="Last Seen",      value=f"`{delta_m:.1f}m ago`",          inline=True)
        embed.add_field(name="Accounts",       value=f"`{len(wh_data.get('accounts',{}))}`", inline=True)
    embed.set_footer(text=_zite_footer("Channel Info"))
    await ctx.send(embed=embed)

# ─────────────────────── CONFIG MANAGEMENT ────────────────────────────────────

@bot.command(name="config", aliases=["cfg"])
async def cmd_config(ctx):
    """View current detection config."""
    if not _cmd_guard(ctx): return
    embed = discord.Embed(title="⚙️  Detection Configuration", color=0xA78BFA,
                          timestamp=datetime.now(timezone.utc))
    embed.add_field(name="🏛️ Container Guild IDs",
                    value="\n".join(f"`{x}`" for x in AUTO_DETECT_CONTAINERS) or "None",
                    inline=False)
    embed.add_field(name="📋 Static Whitelist Channel IDs",
                    value="\n".join(f"`{x}`" for x in MISSING_CHANNEL_WHITELIST) or "None",
                    inline=False)
    embed.add_field(name="⏱️ Save Interval",    value=f"`{SAVE_INTERVAL_S}s`",       inline=True)
    embed.add_field(name="☁️ Backup Interval",  value=f"`{BACKUP_INTERVAL_S}s`",     inline=True)
    embed.add_field(name="⚠️ Depart Warn",      value=f"`{MERCHANT_WARN_BEFORE_S}s`",inline=True)
    embed.add_field(name="🔎 Detected Channels",value=f"`{len(dynamic_detected_channels)}`", inline=True)
    embed.set_footer(text=_zite_footer("Config"))
    await ctx.send(embed=embed)

@bot.command(name="addcontainer")
async def cmd_add_container(ctx, guild_id: int):
    """Add a guild/category ID to auto-detect containers: !addcontainer <id>"""
    if not _cmd_guard(ctx): return
    AUTO_DETECT_CONTAINERS.add(guild_id)
    embed = discord.Embed(
        title="✅  Container Added",
        description=f"Guild/Category ID `{guild_id}` added to auto-detect containers.",
        color=0x00FFA3, timestamp=datetime.now(timezone.utc))
    embed.set_footer(text=_zite_footer("Config"))
    await ctx.send(embed=embed)
    log.info(f"CONFIG: Added container {guild_id}")

@bot.command(name="removecontainer")
async def cmd_remove_container(ctx, guild_id: int):
    """Remove a guild/category from auto-detect containers: !removecontainer <id>"""
    if not _cmd_guard(ctx): return
    AUTO_DETECT_CONTAINERS.discard(guild_id)
    embed = discord.Embed(
        title="🗑️  Container Removed",
        description=f"ID `{guild_id}` removed from containers.",
        color=0xF59E0B, timestamp=datetime.now(timezone.utc))
    embed.set_footer(text=_zite_footer("Config"))
    await ctx.send(embed=embed)

@bot.command(name="addwhitelist")
async def cmd_add_whitelist(ctx, channel_id: int):
    """Add a channel ID to the static whitelist: !addwhitelist <id>"""
    if not _cmd_guard(ctx): return
    MISSING_CHANNEL_WHITELIST.add(channel_id)
    embed = discord.Embed(
        title="✅  Whitelist Updated",
        description=f"Channel ID `{channel_id}` added to static whitelist.",
        color=0x00FFA3, timestamp=datetime.now(timezone.utc))
    embed.set_footer(text=_zite_footer("Config"))
    await ctx.send(embed=embed)

@bot.command(name="removewhitelist")
async def cmd_remove_whitelist(ctx, channel_id: int):
    """Remove a channel ID from the static whitelist: !removewhitelist <id>"""
    if not _cmd_guard(ctx): return
    MISSING_CHANNEL_WHITELIST.discard(channel_id)
    embed = discord.Embed(
        title="🗑️  Whitelist Updated",
        description=f"Channel ID `{channel_id}` removed from whitelist.",
        color=0xF59E0B, timestamp=datetime.now(timezone.utc))
    embed.set_footer(text=_zite_footer("Config"))
    await ctx.send(embed=embed)

@bot.command(name="addchannel")
async def cmd_add_channel(ctx, channel: discord.TextChannel):
    """Manually add a channel to the detection set: !addchannel #channel"""
    if not _cmd_guard(ctx): return
    was_new = channel.id not in dynamic_detected_channels
    dynamic_detected_channels.add(channel.id)
    embed = discord.Embed(
        title="✅  Channel Registered" if was_new else "ℹ️  Already Registered",
        description=f"<#{channel.id}> (`{channel.id}`) is now monitored.",
        color=0x00FFA3 if was_new else 0xA78BFA,
        timestamp=datetime.now(timezone.utc))
    embed.set_footer(text=_zite_footer("Config"))
    await ctx.send(embed=embed)

@bot.command(name="removechannel")
async def cmd_remove_channel(ctx, channel: discord.TextChannel):
    """Remove a channel from the detection set: !removechannel #channel"""
    if not _cmd_guard(ctx): return
    dynamic_detected_channels.discard(channel.id)
    embed = discord.Embed(
        title="🗑️  Channel Removed",
        description=f"<#{channel.id}> removed from monitored channels.",
        color=0xF59E0B, timestamp=datetime.now(timezone.utc))
    embed.set_footer(text=_zite_footer("Config"))
    await ctx.send(embed=embed)

@bot.command(name="setwarntime")
async def cmd_set_warn_time(ctx, seconds: int):
    """Set merchant departure warning time: !setwarntime 30"""
    if not _cmd_guard(ctx): return
    global MERCHANT_WARN_BEFORE_S
    MERCHANT_WARN_BEFORE_S = max(5, min(seconds, 120))
    embed = discord.Embed(
        title="⚙️  Warn Time Updated",
        description=f"Merchant departure warning now fires at **{MERCHANT_WARN_BEFORE_S}s** remaining.",
        color=0x00FFA3, timestamp=datetime.now(timezone.utc))
    embed.set_footer(text=_zite_footer("Config"))
    await ctx.send(embed=embed)

# ─────────────────────────── BIOME COMMANDS ───────────────────────────────────

@bot.command(name="biomes")
async def cmd_biomes(ctx):
    """All biome event counts sorted by frequency."""
    if not _cmd_guard(ctx): return
    if not biome_counts:
        await ctx.send(embed=discord.Embed(description="No biome data yet.", color=0x36393F))
        return
    lines = [
        f"{BIOME_EMOJIS.get(k,'❓')} **{k}**: `{v}` events  *(cap: {calculate_macro_capacity(k)} accs)*"
        for k, v in sorted(biome_counts.items(), key=lambda x: -x[1])
    ]
    embed = discord.Embed(title="🌍  Biome Event Counters",
                          description="\n".join(lines), color=0x9B59B6,
                          timestamp=datetime.now(timezone.utc))
    embed.add_field(name="Grand Total", value=f"`{sum(biome_counts.values())}`", inline=True)
    embed.set_footer(text=_zite_footer("Biome Stats"))
    await ctx.send(embed=embed)

@bot.command(name="biomeinfo")
async def cmd_biome_info(ctx, *, name: str):
    """Detailed info about a biome: !biomeinfo SINGULARITY"""
    if not _cmd_guard(ctx): return
    bname  = name.upper()
    limit  = EVENT_SESSION_LIMITS.get(bname)
    tip    = BIOME_TIPS.get(bname, "No tactical data available.")
    emoji  = BIOME_EMOJIS.get(bname, "❓")
    color  = BIOME_COLORS.get(bname, 0x778899)
    cap    = calculate_macro_capacity(bname)
    count  = biome_counts.get(bname, 0)
    embed  = discord.Embed(title=f"{emoji}  Biome Info — {bname}", color=color,
                           timestamp=datetime.now(timezone.utc))
    embed.add_field(name="⏱️ Session Limit", value=f"`{_fmt_duration(limit)}`" if limit else "`Unknown`", inline=True)
    embed.add_field(name="🧮 Macro Capacity",value=f"`{cap} accs`", inline=True)
    embed.add_field(name="📊 Total Seen",    value=f"`{count}`",    inline=True)
    embed.add_field(name="💡 Tip",           value=tip,             inline=False)
    embed.set_footer(text=_zite_footer("Biome Info"))
    await ctx.send(embed=embed)

@bot.command(name="livebiomes")
async def cmd_live_biomes(ctx):
    """Show all currently active biome sessions."""
    if not _cmd_guard(ctx): return
    live = [ev for ev in active_live_events.values() if ev.get("type") == "biome"]
    if not live:
        await ctx.send(embed=discord.Embed(description="No active biome sessions.", color=0x36393F))
        return
    now   = datetime.now(timezone.utc)
    lines = []
    for ev in live:
        elapsed = (now - datetime.fromisoformat(ev["started_at"])).total_seconds()
        limit   = EVENT_SESSION_LIMITS.get(ev["name"], 0)
        left    = max(0, limit - elapsed)
        emoji   = BIOME_EMOJIS.get(ev["name"], "❓")
        lines.append(
            f"{emoji} **{ev['name']}** — `#{ev['channel_name']}` | `{ev.get('account_identity','?')}`"
            f"\n   ⏳ Elapsed: `{_fmt_duration(elapsed)}` | Remaining: `{_fmt_duration(left)}`"
        )
    embed = discord.Embed(title=f"🟢  Live Biome Sessions ({len(live)})",
                          description="\n\n".join(lines), color=0x00FFA3,
                          timestamp=datetime.now(timezone.utc))
    embed.set_footer(text=_zite_footer("Live Biomes"))
    await ctx.send(embed=embed)

# ─────────────────────────── MERCHANT COMMANDS ────────────────────────────────

@bot.command(name="merchants")
async def cmd_merchants(ctx):
    """All merchant event counts."""
    if not _cmd_guard(ctx): return
    if not merchant_counts:
        await ctx.send(embed=discord.Embed(description="No merchant data yet.", color=0x36393F))
        return
    lines = [
        f"{MERCHANT_EMOJIS.get(k,'🏪')} **{k}**: `{v}` events  *(cap: {calculate_macro_capacity(k)} accs)*"
        for k, v in sorted(merchant_counts.items(), key=lambda x: -x[1])
    ]
    embed = discord.Embed(title="🏪  Merchant Event Counters",
                          description="\n".join(lines), color=0xF59E0B,
                          timestamp=datetime.now(timezone.utc))
    embed.add_field(name="Grand Total", value=f"`{sum(merchant_counts.values())}`", inline=True)
    embed.set_footer(text=_zite_footer("Merchant Stats"))
    await ctx.send(embed=embed)

@bot.command(name="merchantinfo")
async def cmd_merchant_info(ctx, *, name: str):
    """Detailed info about a merchant: !merchantinfo MARI"""
    if not _cmd_guard(ctx): return
    # fuzzy match
    upper = name.upper()
    mname = None
    for key in MERCHANT_TIPS:
        if upper in key or key in upper:
            mname = key; break
    if not mname:
        mname = "MERCHANT"
    emoji  = MERCHANT_EMOJIS.get(mname, "🏪")
    color  = MERCHANT_COLORS.get(mname, 0xF59E0B)
    tip    = MERCHANT_TIPS.get(mname, "Standard merchant.")
    limit  = EVENT_SESSION_LIMITS.get(mname, 180)
    cap    = calculate_macro_capacity(mname)
    count  = merchant_counts.get(mname, 0)
    embed  = discord.Embed(title=f"{emoji}  Merchant Info — {mname}", color=color,
                           timestamp=datetime.now(timezone.utc))
    embed.add_field(name="⏱️ Session Window", value=f"`{_fmt_duration(limit)}`", inline=True)
    embed.add_field(name="🧮 Macro Capacity", value=f"`{cap} accs`",             inline=True)
    embed.add_field(name="📊 Total Seen",     value=f"`{count}`",                inline=True)
    embed.add_field(name="💡 Intel",          value=tip,                          inline=False)
    embed.set_footer(text=_zite_footer("Merchant Info"))
    await ctx.send(embed=embed)

@bot.command(name="livemerchants")
async def cmd_live_merchants(ctx):
    """Show all currently active merchant sessions."""
    if not _cmd_guard(ctx): return
    live = [ev for ev in active_live_events.values() if ev.get("type") == "merchant"]
    if not live:
        await ctx.send(embed=discord.Embed(description="No active merchant sessions.", color=0x36393F))
        return
    now   = datetime.now(timezone.utc)
    lines = []
    for ev in live:
        elapsed = (now - datetime.fromisoformat(ev["started_at"])).total_seconds()
        limit   = EVENT_SESSION_LIMITS.get(ev["name"], 180)
        left    = max(0, limit - elapsed)
        emoji   = MERCHANT_EMOJIS.get(ev["name"], "🏪")
        cap     = calculate_macro_capacity(ev["name"])
        lines.append(
            f"{emoji} **{ev['name']}** — `#{ev['channel_name']}` | `{ev.get('account_identity','?')}`"
            f"\n   ⏳ Elapsed: `{_fmt_duration(elapsed)}` | Remaining: `{_fmt_duration(left)}` | Cap: `{cap} accs`"
        )
    embed = discord.Embed(title=f"🟢  Live Merchant Sessions ({len(live)})",
                          description="\n\n".join(lines), color=0xF59E0B,
                          timestamp=datetime.now(timezone.utc))
    embed.set_footer(text=_zite_footer("Live Merchants"))
    await ctx.send(embed=embed)

# ─────────────────────────── LIVE / ALL EVENTS ────────────────────────────────

@bot.command(name="live")
async def cmd_live(ctx):
    """All currently active events (biomes + merchants)."""
    if not _cmd_guard(ctx): return
    if not active_live_events:
        await ctx.send(embed=discord.Embed(description="No active events right now.", color=0x36393F))
        return
    now   = datetime.now(timezone.utc)
    lines = []
    for ev in active_live_events.values():
        elapsed = (now - datetime.fromisoformat(ev["started_at"])).total_seconds()
        limit   = EVENT_SESSION_LIMITS.get(ev["name"], 0)
        left    = max(0, limit - elapsed)
        is_m    = ev.get("type") == "merchant"
        emoji   = MERCHANT_EMOJIS.get(ev["name"], "🏪") if is_m else BIOME_EMOJIS.get(ev["name"], "❓")
        icon    = "🏪" if is_m else "🌍"
        lines.append(
            f"{icon}{emoji} **{ev['name']}** `[{ev['type'].upper()}]` — `#{ev['channel_name']}`"
            f"\n   `{ev.get('account_identity','?')}` | Elapsed `{_fmt_duration(elapsed)}` | Left `{_fmt_duration(left)}`"
        )
    embed = discord.Embed(title=f"⚡  All Live Events ({len(active_live_events)})",
                          description="\n\n".join(lines), color=0xFF2A2A,
                          timestamp=datetime.now(timezone.utc))
    embed.set_footer(text=_zite_footer("Live Events"))
    await ctx.send(embed=embed)

# ─────────────────────────── WEBSITE / METRICS ────────────────────────────────

@bot.command(name="metrics")
async def cmd_metrics(ctx):
    """Full metrics snapshot (mirrors /api/metrics)."""
    if not _cmd_guard(ctx): return
    m = get_metrics_payload()
    t = m["telemetry"]
    embed = discord.Embed(title="📈  Full Metrics Snapshot", color=0x00E5FF,
                          timestamp=datetime.now(timezone.utc))
    embed.add_field(name="🟢 Status",           value=f"`{m['status']}`",                  inline=True)
    embed.add_field(name="⏱️ Uptime",           value=f"`{m['uptime']}`",                  inline=True)
    embed.add_field(name="🕐 Timestamp",        value=f"`{m['timestamp'][11:19]} UTC`",     inline=True)
    embed.add_field(name="📡 Total Channels",   value=f"`{t['total_registered_webhooks']}`",inline=True)
    embed.add_field(name="🔴 Active (10m)",     value=f"`{t['active_webhooks_last_10m']}`", inline=True)
    embed.add_field(name="🔎 Detected",         value=f"`{t['total_detected_channels']}`",  inline=True)
    embed.add_field(name="🌍 Total Biomes",     value=f"`{t['grand_total_biomes']}`",        inline=True)
    embed.add_field(name="🏪 Total Merchants",  value=f"`{t['grand_total_merchants']}`",     inline=True)
    embed.add_field(name="⚡ Live Events",      value=f"`{t['active_live_events']}`",        inline=True)
    embed.add_field(name="📊 Biome Breakdown",
                    value="\n".join(f"`{k}`: {v}" for k, v in sorted(
                        biome_counts.items(), key=lambda x: -x[1])[:8]) or "None",
                    inline=False)
    embed.add_field(name="🏪 Merchant Breakdown",
                    value="\n".join(f"`{k}`: {v}" for k, v in sorted(
                        merchant_counts.items(), key=lambda x: -x[1])[:6]) or "None",
                    inline=False)
    embed.set_footer(text=_zite_footer("Metrics"))
    await ctx.send(embed=embed)

@bot.command(name="metricsraw")
async def cmd_metrics_raw(ctx):
    """Export raw metrics as a JSON file."""
    if not _cmd_guard(ctx): return
    payload = get_metrics_payload()
    tmp     = "metrics_export.json"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    await ctx.send(
        content="📦 Raw metrics export:",
        file=discord.File(tmp),
    )
    try: os.remove(tmp)
    except: pass

@bot.command(name="website")
async def cmd_website(ctx):
    """Get the website dashboard URL and API endpoint."""
    if not _cmd_guard(ctx): return
    render_url = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:10000")
    embed      = discord.Embed(title="🌐  Website & API Info", color=0x00E5FF,
                               timestamp=datetime.now(timezone.utc))
    embed.add_field(name="🖥️ Dashboard",  value=f"`{render_url}/`",           inline=False)
    embed.add_field(name="📡 API",        value=f"`{render_url}/api/metrics`", inline=False)
    embed.add_field(name="⏱️ Uptime",    value=f"`{_fmt_uptime(BOT_START_TIME)}`", inline=True)
    embed.add_field(name="🔄 Refresh",   value="`Every 15s (auto)`",           inline=True)
    embed.set_footer(text=_zite_footer("Website"))
    await ctx.send(embed=embed)

# ─────────────────────────── DATABASE / BACKUP ────────────────────────────────

@bot.command(name="backup")
async def cmd_backup(ctx):
    """Force a cloud backup right now."""
    if not _cmd_guard(ctx): return
    global _last_backup_time
    _last_backup_time = 0.0   # reset throttle
    await backup_state_to_discord_cloud()
    embed = discord.Embed(title="☁️  Cloud Backup Triggered",
                          description="State has been uploaded to `telemetry-state-db`.",
                          color=0x00FFA3, timestamp=datetime.now(timezone.utc))
    embed.set_footer(text=_zite_footer("Backup"))
    await ctx.send(embed=embed)

@bot.command(name="restore")
async def cmd_restore(ctx):
    """Force restore from cloud backup."""
    if not _cmd_guard(ctx): return
    ok = await load_state_from_discord_cloud()
    embed = discord.Embed(
        title="✅  Restored from Cloud" if ok else "❌  Restore Failed",
        description="State loaded from latest attachment." if ok else "No valid backup found in `telemetry-state-db`.",
        color=0x00FFA3 if ok else 0xFF2A2A, timestamp=datetime.now(timezone.utc))
    embed.set_footer(text=_zite_footer("Restore"))
    await ctx.send(embed=embed)

@bot.command(name="savemetrics")
async def cmd_save_metrics(ctx):
    """Force-save metrics to local disk now."""
    if not _cmd_guard(ctx): return
    global _last_save_time
    _last_save_time = 0.0
    save_persisted_metrics()
    embed = discord.Embed(title="💾  Metrics Saved",
                          description=f"Written to `{DATA_STORE_PATH}`.",
                          color=0x00FFA3, timestamp=datetime.now(timezone.utc))
    embed.set_footer(text=_zite_footer("Save"))
    await ctx.send(embed=embed)

@bot.command(name="clearevents")
async def cmd_clear_events(ctx):
    """Clear all active live events (use with caution)."""
    if not _cmd_guard(ctx): return
    count = len(active_live_events)
    active_live_events.clear()
    _departure_warned.clear()
    embed = discord.Embed(title="🗑️  Live Events Cleared",
                          description=f"Removed `{count}` active event(s).",
                          color=0xFF4500, timestamp=datetime.now(timezone.utc))
    embed.set_footer(text=_zite_footer("Clear"))
    await ctx.send(embed=embed)

# ─────────────────────────── CAPACITY CALCULATOR ──────────────────────────────

@bot.command(name="capacity", aliases=["cap"])
async def cmd_capacity(ctx, *, event_name: str):
    """Calculate macro capacity for any event: !capacity SINGULARITY"""
    if not _cmd_guard(ctx): return
    name_up = event_name.upper()
    cap_40  = calculate_macro_capacity(name_up, avg=40, buf=15)
    cap_30  = calculate_macro_capacity(name_up, avg=30, buf=15)
    cap_60  = calculate_macro_capacity(name_up, avg=60, buf=15)
    limit   = EVENT_SESSION_LIMITS.get(name_up)
    is_m    = any(k in name_up for k in ("MERCHANT","MARI","JESTER","RIN"))
    emoji   = MERCHANT_EMOJIS.get(name_up, "🏪") if is_m else BIOME_EMOJIS.get(name_up, "❓")
    color   = MERCHANT_COLORS.get(name_up, 0xF59E0B) if is_m else BIOME_COLORS.get(name_up, 0x778899)
    embed   = discord.Embed(title=f"{emoji}  Capacity — {name_up}", color=color,
                            timestamp=datetime.now(timezone.utc))
    embed.add_field(name="⏱️ Session Limit", value=f"`{_fmt_duration(limit)}`" if limit else "`Unknown`", inline=True)
    embed.add_field(name="🧮 30s cycle",     value=f"`{cap_30} accounts`",   inline=True)
    embed.add_field(name="🧮 40s cycle",     value=f"`{cap_40} accounts`",   inline=True)
    embed.add_field(name="🧮 60s cycle",     value=f"`{cap_60} accounts`",   inline=True)
    embed.set_footer(text=_zite_footer("Capacity Calculator"))
    await ctx.send(embed=embed)

@bot.command(name="sessionlimits", aliases=["limits"])
async def cmd_session_limits(ctx):
    """Show all known event session time limits."""
    if not _cmd_guard(ctx): return
    biome_lines    = []
    merchant_lines = []
    for name, sec in sorted(EVENT_SESSION_LIMITS.items(), key=lambda x: -x[1]):
        is_m = any(k in name for k in ("MERCHANT","MARI","JESTER","RIN"))
        emoji = MERCHANT_EMOJIS.get(name,"🏪") if is_m else BIOME_EMOJIS.get(name,"❓")
        line  = f"{emoji} **{name}**: `{_fmt_duration(sec)}`  *(cap: {calculate_macro_capacity(name)} accs)*"
        if is_m:
            merchant_lines.append(line)
        else:
            biome_lines.append(line)
    embed = discord.Embed(title="⏱️  Session Time Limits", color=0xA78BFA,
                          timestamp=datetime.now(timezone.utc))
    embed.add_field(name="🌍 Biomes",    value="\n".join(biome_lines)    or "None", inline=False)
    embed.add_field(name="🏪 Merchants", value="\n".join(merchant_lines) or "None", inline=False)
    embed.set_footer(text=_zite_footer("Session Limits"))
    await ctx.send(embed=embed)

# ─────────────────────────── DISCORD MANAGER ──────────────────────────────────

@bot.command(name="serverinfo")
async def cmd_server_info(ctx):
    """Info about the current Discord server."""
    if not _cmd_guard(ctx): return
    g     = ctx.guild
    embed = discord.Embed(title=f"🏛️  Server Info — {g.name}", color=0x5865F2,
                          timestamp=datetime.now(timezone.utc))
    embed.add_field(name="ID",             value=f"`{g.id}`",           inline=True)
    embed.add_field(name="Owner",          value=f"`{g.owner}`",        inline=True)
    embed.add_field(name="Members",        value=f"`{g.member_count}`", inline=True)
    embed.add_field(name="Text Channels",  value=f"`{len(g.text_channels)}`",  inline=True)
    embed.add_field(name="Voice Channels", value=f"`{len(g.voice_channels)}`", inline=True)
    embed.add_field(name="Roles",          value=f"`{len(g.roles)}`",   inline=True)
    embed.add_field(name="Boost Level",    value=f"`{g.premium_tier}`", inline=True)
    embed.add_field(name="Boosts",         value=f"`{g.premium_subscription_count}`", inline=True)
    embed.add_field(name="Created",        value=f"`{g.created_at.strftime('%Y-%m-%d')}`", inline=True)
    if g.icon:
        embed.set_thumbnail(url=g.icon.url)
    embed.set_footer(text=_zite_footer("Server Info"))
    await ctx.send(embed=embed)

@bot.command(name="guilds")
async def cmd_guilds(ctx):
    """List all guilds the bot is in."""
    if not _cmd_guard(ctx): return
    lines = [f"`{g.id}` — **{g.name}** ({g.member_count} members)" for g in bot.guilds]
    embed = discord.Embed(title=f"🏛️  Guilds ({len(bot.guilds)})",
                          description="\n".join(lines), color=0x5865F2,
                          timestamp=datetime.now(timezone.utc))
    embed.set_footer(text=_zite_footer("Guilds"))
    await ctx.send(embed=embed)

@bot.command(name="pinned")
async def cmd_pinned(ctx, channel: discord.TextChannel = None):
    """List pinned messages in a channel: !pinned #channel"""
    if not _cmd_guard(ctx): return
    ch      = channel or ctx.channel
    pins    = await ch.pins()
    if not pins:
        await ctx.send(embed=discord.Embed(description=f"No pinned messages in <#{ch.id}>.", color=0x36393F))
        return
    lines = [
        f"`{p.id}` — {p.author.display_name}: {p.content[:60] or '[embed]'}"
        for p in pins[:15]
    ]
    embed = discord.Embed(title=f"📌  Pinned Messages in #{ch.name} ({len(pins)})",
                          description="\n".join(lines), color=0xFFD700,
                          timestamp=datetime.now(timezone.utc))
    embed.set_footer(text=_zite_footer("Pinned"))
    await ctx.send(embed=embed)

# ─────────────────────────── HELP ─────────────────────────────────────────────

@bot.command(name="help", aliases=["h", "commands", "cmds"])
async def cmd_help(ctx):
    """Show all available commands."""
    if not _cmd_guard(ctx): return
    embed = discord.Embed(
        title="📖  Zite Telemetry Bot — Command Reference",
        description=f"All commands must be used in <#{CMD_CHANNEL_ID}>.\nPrefix: `!`",
        color=0x00E5FF,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="⏱️ System",
        value=(
            "`!uptime` `!status` `!ping`\n"
            "`!metrics` `!metricsraw` `!website`"
        ), inline=False)
    embed.add_field(name="📡 Webhooks",
        value=(
            "`!webhooks` `!webhooklist`\n"
            "`!webhookinfo <name>` `!webhookaccounts <name>`"
        ), inline=False)
    embed.add_field(name="🔎 Channels",
        value=(
            "`!channels` `!channellist`\n"
            "`!channelinfo [#ch]` `!addchannel #ch` `!removechannel #ch`"
        ), inline=False)
    embed.add_field(name="⚙️ Config",
        value=(
            "`!config`\n"
            "`!addcontainer <id>` `!removecontainer <id>`\n"
            "`!addwhitelist <id>` `!removewhitelist <id>`\n"
            "`!setwarntime <s>`"
        ), inline=False)
    embed.add_field(name="🌍 Biomes",
        value=(
            "`!biomes` `!biomeinfo <name>`\n"
            "`!livebiomes`"
        ), inline=False)
    embed.add_field(name="🏪 Merchants",
        value=(
            "`!merchants` `!merchantinfo <name>`\n"
            "`!livemerchants`"
        ), inline=False)
    embed.add_field(name="⚡ Live",
        value="`!live` `!clearevents`", inline=False)
    embed.add_field(name="🧮 Calculator",
        value="`!capacity <name>` `!sessionlimits`", inline=False)
    embed.add_field(name="☁️ Data",
        value="`!backup` `!restore` `!savemetrics`", inline=False)
    embed.add_field(name="🏛️ Discord",
        value="`!serverinfo` `!guilds` `!pinned [#ch]`", inline=False)
    embed.set_footer(text=_zite_footer("Help"))
    await ctx.send(embed=embed)

# ── 17. Bot Events ────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    load_persisted_metrics()
    await load_state_from_discord_cloud()
    for guild in bot.guilds:
        for channel in guild.text_channels:
            _register_channel(channel)
    log.info(f"AUTO-DETECT: Cached {len(dynamic_detected_channels)} monitored channels.")
    log.info(f"SYSTEM ONLINE — {bot.user} ready.")
    if not merchant_departure_watchdog.is_running():
        merchant_departure_watchdog.start()

@bot.event
async def on_guild_channel_create(channel):
    if isinstance(channel, discord.TextChannel):
        _register_channel(channel)

@bot.event
async def on_guild_channel_update(before, after):
    if isinstance(after, discord.TextChannel):
        _register_channel(after)

@bot.event
async def on_command_error(ctx, error):
    if not _cmd_guard(ctx):
        return
    embed = discord.Embed(
        title="❌  Command Error",
        description=f"```\n{str(error)[:900]}\n```",
        color=0xFF2A2A, timestamp=datetime.now(timezone.utc))
    embed.add_field(name="Command", value=f"`{ctx.message.content[:100]}`", inline=False)
    embed.set_footer(text=_zite_footer("Error Handler"))
    await ctx.send(embed=embed)

@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return

    # ── website-output → embed-output auto-format ──────────────────────────
    if message.channel.id == EXTENDED_LOG_CHANNEL_ID and message.content:
        # Auto-pin errors
        await maybe_auto_pin_error(message)
        # Forward as rich embed to embed-output
        embed_ch = _get_embed_output_channel()
        if embed_ch:
            try:
                rich_embed = _build_plain_to_rich_embed(message)
                await embed_ch.send(embed=rich_embed)
            except Exception as e:
                log.error(f"Auto-format error: {e}")

    # ── Allow commands (only in CMD channel) ─────────────────────────────────
    await bot.process_commands(message)

    # ── Skip own messages and non-monitored channels ─────────────────────────
    channel_name_lower = message.channel.name.lower()
    if "webhook" in channel_name_lower and message.channel.id not in dynamic_detected_channels:
        _register_channel(message.channel)

    is_monitored = (
        message.channel.id in MISSING_CHANNEL_WHITELIST
        or message.channel.id in dynamic_detected_channels
        or "webhook" in channel_name_lower
    )
    if not is_monitored:
        return

    t0           = time.perf_counter()
    cid_str      = str(message.channel.id)
    now_iso      = datetime.now(timezone.utc).isoformat()
    is_forwarder = False

    combined_full, roblox_link, link_vector = _extract_combined_text(message)

    if not is_forwarder:
        if cid_str not in webhook_activity:
            webhook_activity[cid_str] = {
                "name": message.channel.name, "last_seen": now_iso,
                "total_messages": 1, "accounts": {},
            }
        else:
            webhook_activity[cid_str]["last_seen"]       = now_iso
            webhook_activity[cid_str]["total_messages"] += 1
            webhook_activity[cid_str].setdefault("accounts", {})

        if roblox_link:
            acc_reg = webhook_activity[cid_str]["accounts"]
            if roblox_link not in acc_reg:
                acc_reg[roblox_link] = {
                    "display_name": f"Account {len(acc_reg)+1}",
                    "biomes": {}, "merchants": {}, "completed_sessions": [],
                }
            account_identity = acc_reg[roblox_link]["display_name"]
        else:
            account_identity = "Account 1"
    else:
        account_identity = "Forwarder Source"

    if not message.embeds:
        return

    guild_name = message.guild.name if message.guild else "Private Guild"

    for emb in message.embeds:
        parts = []
        if emb.title:                        parts.append(emb.title)
        if emb.description:                  parts.append(emb.description)
        if emb.author and emb.author.name:   parts.append(emb.author.name)
        for f in emb.fields:
            if f.name:  parts.append(f.name)
            if f.value: parts.append(f.value)

        combined_text  = " ".join(parts)
        combined_lower = combined_text.lower()
        is_start       = bool(EVENT_START_RE.search(combined_lower))
        is_end         = bool(EVENT_END_RE.search(combined_lower))

        if is_end:
            print(f"DEBUG: END trigger -> {combined_lower[:60]}")
        if not is_start and not is_end:
            continue

        is_merchant = any(kw in combined_lower for kw in ("merchant","mari","jester","rin"))
        if is_merchant:
            await _process_merchant(message, combined_lower, is_start, cid_str,
                                    now_iso, guild_name, roblox_link, link_vector,
                                    account_identity, is_forwarder, t0)
        else:
            await _process_biome(message, combined_text, combined_lower, is_start,
                                 cid_str, now_iso, guild_name, roblox_link, link_vector,
                                 account_identity, is_forwarder, t0)

# ── Boot ──────────────────────────────────────────────────────────────────────
threading.Thread(target=keep_alive, daemon=True).start()

TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)
else:
    print("Error: DISCORD_TOKEN environment variable not set.")
