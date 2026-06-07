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
from datetime import datetime, timezone, timedelta

# ── psutil is optional — graceful fallback if not installed ───────────────────
try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False

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

AUTO_DETECT_CONTAINERS    = {1501595856493740162, 1511360799996907710, 1509915924663238776}
MISSING_CHANNEL_WHITELIST = {1511359721632694363, 1511365304624877568,
                              1511335720239759361, 1511362877322432792}
dynamic_detected_channels: set = set()

EXTENDED_LOG_CHANNEL_ID  = 1512287503141306570
CMD_CHANNEL_ID           = 1512289164786401500
EMBED_OUTPUT_CHANNEL_ID  = 1512290157179703426
WELCOME_CHANNEL_ID       = 1512300518695895120
SERVER_OUTPUT_CHANNEL_ID = 1512300518695895120

MERCHANT_DEPART_CHANNEL_ID = os.getenv("MERCHANT_DEPART_CHANNEL_ID")
MERCHANT_WARN_BEFORE_S     = 30
_departure_warned: set     = set()

SAVE_INTERVAL_S   = 15
BACKUP_INTERVAL_S = 60

# ── Role IDs ──────────────────────────────────────────────────────────────────
WANTS_TO_MACRO_ROLE_ID     = 1509772223932796928
MACRO_TRAIL_VERIFYING_ROLE = 1509768047127429170

# ── 4. Global State ───────────────────────────────────────────────────────────
biome_counts:       dict  = {}
merchant_counts:    dict  = {}
webhook_activity:   dict  = {}
active_live_events: dict  = {}
_last_save_time:    float = 0.0
_last_backup_time:  float = 0.0

# Track claimed macro applications: message_id -> user_id
claimed_applications: dict = {}

# ── 5. Regex & Lookups ────────────────────────────────────────────────────────
ROBLOX_LINK_RE = re.compile(r"https://www\.roblox\.com/share\?\S+")
ROBLOX_PRIVATE_RE = re.compile(
    r"https?://www\.roblox\.com/(?:games/|share\?)[^\s<>\"']+(?:privateServerLinkCode|AccessCode)[^\s<>\"']*",
    re.IGNORECASE,
)

BIOME_MATCH_RE = re.compile(
    r"(?:Biome\s+(?:Started|Ended)(?:\s*[:\-]\s*))([A-Z_]+)", re.IGNORECASE
)
EVENT_START_RE = re.compile(
    r"\b(started|start|spawned|arrived|appeared|has arrived|is here|arrive)\b", re.IGNORECASE
)
EVENT_END_RE = re.compile(
    r"\b(ended|end|despawned|left|gone|has left|disappeared|expired|timed out|depart)\b",
    re.IGNORECASE,
)
CLEAN_WORDS_RE = re.compile(r"\b[A-Z]{4,}\b")

KNOWN_BIOMES = [
    "SINGULARITY","GLITCHED","DREAMSPACE","CYBERSPACE",
    "STARFALL","CORRUPTION","WINDY","SNOWY","RAINY","HELL","NORMAL","SAND",
    "SANDSTORM","HEAVEN","NULL","BLAZING",
]
STOP_WORDS = frozenset({
    "START","STARTED","ENDED","BIOME","TIME","INVITE",
    "SERVER","PRIVATE","LINK","WARNING","DETECTION","SOURCE",
    "JOIN","ARRIVED","ISLAND","MERCHANT",
})

EVENT_SESSION_LIMITS: dict = {
    "WINDY": 120, "SNOWY": 120, "RAINY": 120, "SAND STORM": 650,
    "SANDSTORM": 650, "HELL": 666, "STARFALL": 650, "HEAVEN": 240,
    "NULL": 99, "NORMAL": 60, "GLITCHED": 164, "DREAMSPACE": 192,
    "CYBERSPACE": 720, "SINGULARITY": 1200, "BLAZING SUN": 300,
    "MARI (MERCHANT)": 180, "JESTER (MERCHANT)": 180, "RIN (MERCHANT)": 180,
    "MYSTERIOUS MERCHANT": 180, "TRAVELING MERCHANT": 180, "MERCHANT": 180,
    "BLACK MERCHANT": 180,
}

# ── 6. Cosmetics ──────────────────────────────────────────────────────────────
BIOME_COLORS = {
    "SINGULARITY":0x9B59B6,"GLITCHED":0x00FF88,"DREAMSPACE":0xFF69B4,
    "CYBERSPACE":0x00E5FF,"STARFALL":0xFFD700,"CORRUPTION":0x8B0000,
    "WINDY":0xADD8E6,"SNOWY":0xE0F7FA,"RAINY":0x4682B4,"HELL":0xFF2A2A,
    "SAND STORM":0xC2A35A,"SANDSTORM":0xC2A35A,"HEAVEN":0xFFFACD,
    "NORMAL":0x778899,"NULL":0x36393F,"BLAZING SUN":0xFF8C00,
}
BIOME_EMOJIS = {
    "SINGULARITY":"🌀","GLITCHED":"⚠️","DREAMSPACE":"💤","CYBERSPACE":"🖥️",
    "STARFALL":"🌠","CORRUPTION":"☠️","WINDY":"💨","SNOWY":"❄️","RAINY":"🌧️",
    "HELL":"🔥","SAND STORM":"🏜️","SANDSTORM":"🏜️","HEAVEN":"☁️",
    "NORMAL":"🌿","NULL":"⬛","BLAZING SUN":"☀️","UNKNOWN":"❓",
}
MERCHANT_COLORS = {
    "MARI (MERCHANT)":0xFF69B4,"JESTER (MERCHANT)":0xFFA500,
    "RIN (MERCHANT)":0x00CED1,"MYSTERIOUS MERCHANT":0x6A0DAD,
    "TRAVELING MERCHANT":0x228B22,"MERCHANT":0xF59E0B,
    "BLACK MERCHANT":0x1a1a2e,
}
MERCHANT_EMOJIS = {
    "MARI (MERCHANT)":"🌸","JESTER (MERCHANT)":"🃏","RIN (MERCHANT)":"🎐",
    "MYSTERIOUS MERCHANT":"🔮","TRAVELING MERCHANT":"🧳","MERCHANT":"🏪",
    "BLACK MERCHANT":"🖤",
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
    "SANDSTORM":"Extended ~10m window. Great for farming mid-tier resources.",
    "HEAVEN":"4-minute soft window. Peaceful, bonus XP multiplier.",
    "NORMAL":"Standard biome. Rotate accounts freely.",
    "NULL":"99-second window. Breakthrough is essentially impossible here.",
    "BLAZING SUN":"Daytime-only biome. 5-minute window.",
}
MERCHANT_TIPS = {
    "MARI (MERCHANT)":"Mari stocks rare accessories. Prioritise accounts needing gear upgrades.",
    "JESTER (MERCHANT)":"Jester sells randomised bundles — high variance, potentially best value.",
    "RIN (MERCHANT)":"Rin offers crafting materials. Queue crafting-focused accounts first.",
    "MYSTERIOUS MERCHANT":"Unknown stock — high-priority, treat as top-tier spawn.",
    "TRAVELING MERCHANT":"Rotating inventory. Check stock before committing all accounts.",
    "MERCHANT":"Standard merchant. Queue accounts with available currency.",
    "BLACK MERCHANT":"Rare black merchant — appears with low probability. High-priority spawn.",
}

# ── 7. Macro Source Detection ─────────────────────────────────────────────────
# Each entry: (name, patterns_to_match_in_combined_text, link_field_names)
MACRO_SOURCE_PATTERNS = [
    # Coteab / Noteab Macro — "Mari has arrived!" title + "Detection Source" field + "Coteab Macro" footer
    {
        "name": "Coteab Macro",
        "title_patterns": [r"has arrived", r"biome started", r"biome ended",
                           r"merchant spawned", r"merchant despawned"],
        "field_patterns": [r"detection source", r"coteab macro", r"noteab macro"],
        "link_fields": ["join server", "private server", "server link"],
        "footer_patterns": [r"coteab macro", r"noteab macro", r"coteab v"],
        "private_server_patterns": [r"private server", r"ps link", r"join server"],
    },
    # MultiScope V1/V2
    {
        "name": "MultiScope",
        "title_patterns": [r"multiscope", r"biome alert", r"merchant alert"],
        "field_patterns": [r"multiscope", r"scope"],
        "link_fields": ["private server", "server link", "join"],
        "footer_patterns": [r"multiscope"],
        "private_server_patterns": [r"private server", r"server link"],
    },
    # SolsScope
    {
        "name": "SolsScope",
        "title_patterns": [r"solsscope", r"sols scope"],
        "field_patterns": [r"solsscope", r"sols scope"],
        "link_fields": ["private server", "server link"],
        "footer_patterns": [r"solsscope"],
        "private_server_patterns": [r"private server"],
    },
    # FishScope
    {
        "name": "FishScope",
        "title_patterns": [r"fishscope", r"fish scope"],
        "field_patterns": [r"fishscope"],
        "link_fields": ["private server", "server link"],
        "footer_patterns": [r"fishscope"],
        "private_server_patterns": [r"private server"],
    },
    # FishSol
    {
        "name": "FishSol",
        "title_patterns": [r"fishsol", r"fish sol"],
        "field_patterns": [r"fishsol"],
        "link_fields": ["private server", "server link"],
        "footer_patterns": [r"fishsol"],
        "private_server_patterns": [r"private server"],
    },
    # Maxstellar
    {
        "name": "Maxstellar",
        "title_patterns": [r"maxstellar"],
        "field_patterns": [r"maxstellar"],
        "link_fields": ["private server", "server link"],
        "footer_patterns": [r"maxstellar"],
        "private_server_patterns": [r"private server"],
    },
    # Radiance
    {
        "name": "Radiance Macro",
        "title_patterns": [r"radiance macro", r"radiance"],
        "field_patterns": [r"radiance"],
        "link_fields": ["private server", "server link"],
        "footer_patterns": [r"radiance"],
        "private_server_patterns": [r"private server"],
    },
    # DroidScope
    {
        "name": "DroidScope",
        "title_patterns": [r"droidscope", r"droid scope"],
        "field_patterns": [r"droidscope"],
        "link_fields": ["private server", "server link"],
        "footer_patterns": [r"droidscope"],
        "private_server_patterns": [r"private server"],
    },
    # Slaoq
    {
        "name": "Slaoq Sniper",
        "title_patterns": [r"slaoq", r"sols rng sniper"],
        "field_patterns": [r"slaoq"],
        "link_fields": ["private server", "server link"],
        "footer_patterns": [r"slaoq"],
        "private_server_patterns": [r"private server"],
    },
    # RNGsus
    {
        "name": "RNGsus",
        "title_patterns": [r"rngsus"],
        "field_patterns": [r"rngsus"],
        "link_fields": ["private server", "server link"],
        "footer_patterns": [r"rngsus"],
        "private_server_patterns": [r"private server"],
    },
    # StayActive
    {
        "name": "StayActive",
        "title_patterns": [r"stayactive", r"stay active"],
        "field_patterns": [r"stayactive", r"stay active"],
        "link_fields": ["private server", "server link"],
        "footer_patterns": [r"stayactive"],
        "private_server_patterns": [r"private server"],
    },
    # Oyster Detector
    {
        "name": "Oyster Detector",
        "title_patterns": [r"oyster"],
        "field_patterns": [r"oyster"],
        "link_fields": ["private server", "server link"],
        "footer_patterns": [r"oyster"],
        "private_server_patterns": [r"private server"],
    },
]

# ── 8. Core Helpers ───────────────────────────────────────────────────────────

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

def _get_sys_stats():
    if _PSUTIL:
        try:
            mem = psutil.Process().memory_info().rss / 1024 / 1024
            cpu = psutil.cpu_percent(interval=0.2)
            return mem, cpu
        except Exception:
            pass
    return 0.0, 0.0

# ── 9. Macro Source Detection Helper ─────────────────────────────────────────

def _detect_macro_source(embed: discord.Embed) -> str:
    """Detect which macro software sent this embed."""
    combined = ""
    if embed.title:       combined += " " + embed.title
    if embed.description: combined += " " + embed.description
    if embed.footer and embed.footer.text:
        combined += " " + embed.footer.text
    if embed.author and embed.author.name:
        combined += " " + embed.author.name
    for f in embed.fields:
        combined += " " + (f.name or "") + " " + (f.value or "")
    combined_lower = combined.lower()

    for macro in MACRO_SOURCE_PATTERNS:
        matched = False
        # Check footer patterns (most reliable)
        for pat in macro.get("footer_patterns", []):
            if re.search(pat, combined_lower):
                matched = True
                break
        if not matched:
            # Check field patterns
            for pat in macro.get("field_patterns", []):
                if re.search(pat, combined_lower):
                    matched = True
                    break
        if matched:
            return macro["name"]
    return "Unknown Macro"

def _extract_private_server_link(embed: discord.Embed, macro_source: str) -> tuple:
    """
    Extract the private server Roblox link from an embed,
    handling all known macro formats. Returns (link, link_vector).
    """
    combined_full = ""
    if embed.title:       combined_full += " " + embed.title
    if embed.description: combined_full += " " + embed.description
    for f in embed.fields:
        name_low = (f.name or "").lower()
        val      = f.value or ""

        # Coteab Macro: "Join Server" field contains the link as a hyperlink
        if any(kw in name_low for kw in ["join server", "private server",
                                          "server link", "ps link", "join"]):
            # Extract URL from markdown hyperlink [text](url) or raw
            m = re.search(r'\(?(https?://[^\s\)]+)\)?', val)
            if m:
                return m.group(1), f"Embed Field: {f.name} [{macro_source}]"
            # Also check raw roblox links
            m = ROBLOX_LINK_RE.search(val)
            if m:
                return m.group(0), f"Embed Field: {f.name} [{macro_source}]"
        combined_full += " " + val

    if embed.description:
        combined_full += " " + embed.description

    # Fallback: scan for any Roblox share link in the whole embed
    m = ROBLOX_LINK_RE.search(combined_full)
    if m:
        return m.group(0), f"Embed Text Scan [{macro_source}]"

    # Check message components / buttons (handled outside, but try URL fields)
    return None, "None"

# ── 10. Persistence ───────────────────────────────────────────────────────────

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

# ── 11. Metrics Payload ───────────────────────────────────────────────────────

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

def get_zite_payload() -> dict:
    m = get_metrics_payload()
    t = m["telemetry"]
    return {
        "status":           "ONLINE",
        "timestamp":        m["timestamp"],
        "uptime":           m["uptime"],
        "bot_started_at":   BOT_START_TIME.isoformat(),
        "webhooks":         t["total_registered_webhooks"],
        "active":           t["active_webhooks_last_10m"],
        "total_biomes":     t["grand_total_biomes"],
        "total_merchants":  t["grand_total_merchants"],
        "detected_channels": t["total_detected_channels"],
        "live_events":      t["active_live_events"],
        "grand_biomes":     sum(m["counters"]["biomes"].values()),
        "grand_merchants":  sum(m["counters"]["merchants"].values()),
        "streams": [
            {
                "name":     s["name"],
                "accounts": s["accounts_count"],
                "last_seen_ago_mins": s["last_seen_ago_mins"],
            }
            for s in m["active_webhook_streams"]
        ],
        "live_event_list": [
            {
                "name":       ev["name"],
                "type":       ev["type"],
                "channel":    ev["channel_name"],
                "account":    ev.get("account_identity", "Unknown"),
                "started_at": ev["started_at"],
            }
            for ev in m["live_events"]
        ],
        "biome_breakdown":    m["counters"]["biomes"],
        "merchant_breakdown": m["counters"]["merchants"],
    }

# ── 12. Embed Builders ────────────────────────────────────────────────────────

def _zite_footer(label: str) -> str:
    return f"Zite Telemetry  •  {label}  •  {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"

def _build_biome_embed(biome_name, event_type, channel_name, guild_name,
                       account_identity, roblox_link, link_vector,
                       duration_str, exec_ms, macro_capacity, metrics,
                       macro_source="Unknown", started_at=None) -> discord.Embed:
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
    embed.add_field(name="🤖 Macro Source",   value=f"`{macro_source}`", inline=True)
    if roblox_link and roblox_link != "None":
        embed.add_field(name="🔗 Private Server",
                        value=f"[**Join →**]({roblox_link}) *(via {link_vector})*", inline=False)
    if is_start and started_at:
        embed.add_field(name="🕐 Expiry ETA",
                        value=f"`{started_at[11:19]} UTC + {_fmt_duration(session_s)}`", inline=False)
    embed.set_footer(text=_zite_footer(f"Biome Engine  •  {biome_name}"))
    return embed

def _build_merchant_embed(merchant_name, event_type, channel_name, guild_name,
                          account_identity, roblox_link, link_vector,
                          duration_str, exec_ms, macro_capacity, metrics,
                          macro_source="Unknown", started_at=None) -> discord.Embed:
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
    embed.add_field(name="🤖 Macro Source",    value=f"`{macro_source}`", inline=True)
    if roblox_link and roblox_link != "None":
        embed.add_field(name="🔗 Private Server",
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

# ── 13. Merchant Departure Watchdog ──────────────────────────────────────────

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

@tasks.loop(seconds=30)
async def live_event_cleanup():
    now = datetime.now(timezone.utc)
    to_remove = []
    for key, ev in list(active_live_events.items()):
        elapsed = (now - datetime.fromisoformat(ev["started_at"])).total_seconds()
        if elapsed > 1200:
            to_remove.append(key)
    for key in to_remove:
        ev = active_live_events.pop(key, None)
        _departure_warned.discard(key)
        if ev:
            log.info(f"AUTO-EXPIRE: Removed stale event '{ev['name']}' after 20min (key={key})")

@live_event_cleanup.before_loop
async def _before_cleanup():
    await bot.wait_until_ready()

# ── 14. Auto-Pin Error System ─────────────────────────────────────────────────

async def maybe_auto_pin_error(message: discord.Message):
    content_up = (message.content or "").upper()
    if any(w in content_up for w in ("ERROR", "FAIL", "EXCEPTION", "CRITICAL", "TRACEBACK")):
        try:
            await message.pin()
            log.info(f"AUTO-PIN: Pinned error message {message.id} in #{message.channel.name}")
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

# ── 15. Web Server ────────────────────────────────────────────────────────────

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

    html += '<section><h2>📊 Biome Event Counters</h2>'
    if data["counters"]["biomes"]:
        for name, cnt in sorted(data["counters"]["biomes"].items(), key=lambda x: -x[1]):
            emoji = BIOME_EMOJIS.get(name, "❓")
            html += f'<span class="biome-tag">{emoji} {name}: {cnt}</span>'
    else:
        html += '<p class="empty">No biome data recorded yet.</p>'
    html += '</section>'

    html += '<section><h2>🏪 Merchant Event Counters</h2>'
    if data["counters"]["merchants"]:
        for name, cnt in sorted(data["counters"]["merchants"].items(), key=lambda x: -x[1]):
            emoji = MERCHANT_EMOJIS.get(name, "🏪")
            html += f'<span class="merchant-tag">{emoji} {name}: {cnt}</span>'
    else:
        html += '<p class="empty">No merchant data recorded yet.</p>'
    html += '</section>'

    html += '<section><h2>🔴 Real-Time Active Sessions</h2>'
    if not data["live_events"]:
        html += '<p class="empty">No active macro instances detected right now.</p>'
    else:
        for ev in data["live_events"]:
            macro_src = ev.get("macro_source", "Unknown")
            ps_link   = ev.get("link", "None")
            ps_html   = f'&nbsp;|&nbsp; <a href="{ps_link}" target="_blank" style="color:var(--cyan)">Private Server</a>' if ps_link and ps_link != "None" else ""
            html += (
                f'<div class="live-row"><div>'
                f'<div class="live-name">{ev["name"]} <small style="color:var(--muted);font-weight:400;">({ev["type"].upper()})</small></div>'
                f'<div class="live-meta">Channel: <span>#{ev["channel_name"]}</span> &nbsp;|&nbsp; Account: <span>{ev.get("account_identity","Unknown")}</span>'
                f' &nbsp;|&nbsp; Source: <span>{macro_src}</span>{ps_html}</div>'
                f'</div><span class="pulse-badge">LIVE since {ev["started_at"][11:19]} UTC</span></div>'
            )
    html += '</section>'

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
                    ps_btn = ""
                    if lk and lk.startswith("http"):
                        ps_btn = f' <a href="{lk}" target="_blank" style="color:var(--cyan);font-size:11px;">[PS Link]</a>'
                    html += f'<div class="account-row"><div class="account-name">{acc["display_name"]}{ps_btn}</div><div>'
                    for sess in reversed(acc.get("completed_sessions", [])):
                        src = sess.get("macro_source", "")
                        html += f'<span class="session-tag">{sess["name"]}: {sess["duration"]}{" · " + src if src else ""}</span>'
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
        if self.path == "/api/zite":
            body = json.dumps(get_zite_payload(), ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
            return
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

# ── 16. Core Message Processing ───────────────────────────────────────────────

def _extract_combined_text(message: discord.Message):
    """
    Extract combined text from message + embeds.
    Also handles Coteab Macro's embed structure where the private server
    link is in a 'Join Server' button or embed field.
    """
    combined    = message.content or ""
    link_vector = "None"
    roblox_link = None

    # Check message-level components (buttons)
    if message.components:
        for row in message.components:
            for comp in getattr(row, 'children', []):
                if hasattr(comp, "url") and comp.url:
                    url = comp.url
                    combined += f" {url}"
                    if "roblox.com" in url.lower():
                        roblox_link = url
                        link_vector = "Interaction Button Component Link"

    if message.embeds:
        for emb in message.embeds:
            parts = [emb.title or "", emb.description or ""]
            if emb.footer and emb.footer.text:
                parts.append(emb.footer.text)
            if emb.author and emb.author.name:
                parts.append(emb.author.name)
            for f in emb.fields:
                parts += [f.name or "", f.value or ""]
                # Coteab Macro: extract URL from "Join Server" field
                name_low = (f.name or "").lower()
                val      = f.value or ""
                if any(kw in name_low for kw in
                       ["join server", "private server", "server link", "ps link"]):
                    # Try markdown link first: [text](url)
                    m = re.search(r'\[.*?\]\((https?://[^\s\)]+)\)', val)
                    if m and "roblox.com" in m.group(1):
                        roblox_link = m.group(1)
                        link_vector = f"Embed Field [{f.name}] (Coteab-style)"
                    else:
                        m2 = ROBLOX_LINK_RE.search(val)
                        if m2:
                            roblox_link = m2.group(0)
                            link_vector = f"Embed Field [{f.name}]"
            combined += " " + " ".join(parts)

    # Fallback: scan raw content for Roblox link
    if not roblox_link:
        m = ROBLOX_LINK_RE.search(combined)
        if m:
            roblox_link = m.group(0)
            link_vector = "Raw Message Text or Embed Block"

    return combined, roblox_link, link_vector

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
    if name in ("BLAZING",):  return "BLAZING SUN"
    if name in ("UNKNOWN BIOME", "UNKNOWN"): return "NORMAL"
    return name

def _identify_merchant(combined_lower):
    if "black merchant" in combined_lower: return "BLACK MERCHANT"
    if "mysterious" in combined_lower:     return "MYSTERIOUS MERCHANT"
    if "traveling" in combined_lower:      return "TRAVELING MERCHANT"
    if "mari" in combined_lower:           return "MARI (MERCHANT)"
    if "jester" in combined_lower:         return "JESTER (MERCHANT)"
    if "rin" in combined_lower:            return "RIN (MERCHANT)"
    return "MERCHANT"

def _resolve_active_event(cid_str, account_identity, event_name):
    key = f"{cid_str}_{account_identity}_{event_name}"
    if key in active_live_events:
        return key, active_live_events[key], account_identity
    for k, ev in list(active_live_events.items()):
        if k.startswith(f"{cid_str}_") and ev["name"] == event_name:
            return k, ev, ev["account_identity"]
    return key, None, account_identity

async def _process_merchant(message, combined_lower, is_start, cid_str,
                            now_iso, guild_name, roblox_link, link_vector,
                            account_identity, is_forwarder, t0, macro_source):
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
            "macro_source": macro_source,
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
                    {"name": merchant_name, "duration": duration_str,
                     "at": now_iso, "macro_source": macro_source})
        else:
            duration_str = "N/A (Start missed)"

    asyncio.ensure_future(asyncio.to_thread(save_persisted_metrics))
    asyncio.ensure_future(backup_state_to_discord_cloud())

    metrics        = get_metrics_payload()
    exec_ms        = (time.perf_counter() - t0) * 1000
    macro_capacity = calculate_macro_capacity(merchant_name)

    print(f"[ZITE_DATA] type=merchant event={event_type} name={merchant_name} "
          f"channel={message.channel.name} account={account_identity} "
          f"duration={duration_str} capacity={macro_capacity} "
          f"macro_source={macro_source} ps_link={roblox_link} "
          f"active={metrics['telemetry']['active_webhooks_last_10m']} "
          f"total={metrics['telemetry']['total_registered_webhooks']} "
          f"grand_merchants={metrics['telemetry']['grand_total_merchants']} "
          f"live={metrics['telemetry']['active_live_events']}")

    print(f"\n[MERCHANT] {event_type} | {merchant_name} | {account_identity} | [{macro_source}]")
    print(f"   Channel : #{message.channel.name}  ({guild_name})")
    if roblox_link:
        print(f"   PS Link : {roblox_link}  [{link_vector}]")
    print(f"   Capacity: {macro_capacity} accounts  (40s macro + 15s buffer)")
    print(f"   Duration: {duration_str}  | {exec_ms:.1f}ms | Active: {metrics['telemetry']['active_webhooks_last_10m']}/{metrics['telemetry']['total_registered_webhooks']}")
    print("-" * 80)

async def _process_biome(message, combined_text, combined_lower, is_start,
                         cid_str, now_iso, guild_name, roblox_link, link_vector,
                         account_identity, is_forwarder, t0, macro_source):
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
            "macro_source": macro_source,
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
                sessions.append({"name": biome_name, "duration": duration_str,
                                  "at": now_iso, "macro_source": macro_source})
        else:
            duration_str = "N/A (Start missed)"

    asyncio.ensure_future(asyncio.to_thread(save_persisted_metrics))
    asyncio.ensure_future(backup_state_to_discord_cloud())

    metrics        = get_metrics_payload()
    exec_ms        = (time.perf_counter() - t0) * 1000
    macro_capacity = calculate_macro_capacity(biome_name)

    print(f"[ZITE_DATA] type=biome event={event_type} name={biome_name} "
          f"channel={message.channel.name} account={account_identity} "
          f"duration={duration_str} capacity={macro_capacity} "
          f"macro_source={macro_source} ps_link={roblox_link} "
          f"active={metrics['telemetry']['active_webhooks_last_10m']} "
          f"total={metrics['telemetry']['total_registered_webhooks']} "
          f"grand_biomes={metrics['telemetry']['grand_total_biomes']} "
          f"live={metrics['telemetry']['active_live_events']}")

    print(f"\n[BIOME] {event_type} | {biome_name} | {account_identity} | [{macro_source}]")
    print(f"   Channel : #{message.channel.name}  ({guild_name})")
    if roblox_link:
        print(f"   PS Link : {roblox_link}  [{link_vector}]")
    print(f"   Capacity: {macro_capacity} accounts  (40s macro + 15s buffer)")
    print(f"   Duration: {duration_str}  | {exec_ms:.1f}ms | Active: {metrics['telemetry']['active_webhooks_last_10m']}/{metrics['telemetry']['total_registered_webhooks']}")
    print("-" * 80)


# ═══════════════════════════════════════════════════════════════════════════════
# ── 17.  MACRO APPLICATION SYSTEM  ────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

DESKTOP_MACROS = [
    ("FishScope",        "https://github.com/cresqnt-sys/FishScope-Macro/releases/tag/2.4-Beta3",                    False),
    ("FishSol ✅",       "https://github.com/ivelchampion249/FishSol-Macro/releases/tag/v1.9.7-1",                   True),
    ("MultiScope V2 ✅", "https://github.com/cresqnt-sys/MultiScope",                                               True),
    ("RNGsus ❌",        "https://github.com/0bl1terate3/RNGsus",                                                    False),
    ("MultiScope V1 ✅", "https://github.com/cresqnt-sys/MultiScope-V1/releases/tag/0.9.9.1-Stable",                True),
    ("SolsScope",        "https://github.com/bazthedev/SolsScope/releases/latest",                                  False),
    ("StayActive",       "https://github.com/0bl1terate3/StayActive/releases/tag/v0.1.8",                           False),
    ("Oyster Detector",  "https://github.com/vexsyx/OysterDetector/releases/tag/v1.1.7",                            False),
    ("Coteab ✅",        "https://github.com/xVapure/Noteab-Macro/releases/tag/v2.1.8-hotfix1",                     True),
    ("Maxstellar ✅",    "https://github.com/maxstellar/maxstellar-Biome-Macro/releases",                           True),
    ("Radiance",         "https://github.com/raandomdev/Radiance-Macro/releases/tag/v1.1.4",                        False),
]

MOBILE_MACROS = [
    ("Slaoq",     "https://github.com/gustaslaoq/Sols-RNG-Sniper",       False),
    ("DroidScope","https://github.com/ScopeDevelopment/DroidScope",       False),
]

# In-memory application state per user
# app_state[user_id] = { "step": ..., "device": ..., "macro": ..., "macro_url": ..., "hours": ..., "msg_id": ... }
app_state: dict = {}

# ─── Views ────────────────────────────────────────────────────────────────────

class ClaimedView(discord.ui.View):
    """Replaces the application view after someone claims it — shows locked message."""
    def __init__(self, claimant: discord.Member):
        super().__init__(timeout=None)
        btn = discord.ui.Button(
            label=f"🔒 Claimed by {claimant.display_name}",
            style=discord.ButtonStyle.secondary,
            disabled=True,
        )
        self.add_item(btn)


class DeviceSelectView(discord.ui.View):
    """Step 1 — choose Desktop or Mobile."""
    def __init__(self, owner_id: int):
        super().__init__(timeout=300)
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        msg_id = str(interaction.message.id)
        # If already claimed by someone else
        if msg_id in claimed_applications:
            if claimed_applications[msg_id] != interaction.user.id:
                await interaction.response.send_message(
                    "❌ This application has already been claimed by another user.",
                    ephemeral=True,
                )
                return False
        return True

    @discord.ui.button(label="🖥️ Desktop", style=discord.ButtonStyle.primary, custom_id="dev_desktop")
    async def desktop(self, interaction: discord.Interaction, button: discord.ui.Button):
        msg_id = str(interaction.message.id)
        # Claim this application
        claimed_applications[msg_id] = interaction.user.id
        # Check role
        if not _has_wants_to_macro_role(interaction.user):
            await interaction.response.send_message(
                "❌ You need the **Wants to Macro** role to use this application.",
                ephemeral=True,
            )
            return
        app_state[interaction.user.id] = {"step": "macro", "device": "Desktop", "msg_id": interaction.message.id}
        view = MacroSelectView(interaction.user.id, "Desktop")
        embed = _appli_embed(
            "📋  Step 2 — Choose Your Macro (Desktop)",
            "Select the macro software you are using. Links are provided for download.\n\n"
            "✅ = **Recommended** | ❌ = **Not Recommended**",
            0x5865F2,
        )
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="📱 Mobile", style=discord.ButtonStyle.success, custom_id="dev_mobile")
    async def mobile(self, interaction: discord.Interaction, button: discord.ui.Button):
        msg_id = str(interaction.message.id)
        claimed_applications[msg_id] = interaction.user.id
        if not _has_wants_to_macro_role(interaction.user):
            await interaction.response.send_message(
                "❌ You need the **Wants to Macro** role to use this application.",
                ephemeral=True,
            )
            return
        app_state[interaction.user.id] = {"step": "macro", "device": "Mobile", "msg_id": interaction.message.id}
        view = MacroSelectView(interaction.user.id, "Mobile")
        embed = _appli_embed(
            "📋  Step 2 — Choose Your Macro (Mobile)",
            "Select the macro software you are using on mobile.",
            0x57F287,
        )
        await interaction.response.edit_message(embed=embed, view=view)


class MacroSelectView(discord.ui.View):
    """Step 2 — select a macro from a dropdown."""
    def __init__(self, owner_id: int, device: str):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.device   = device
        macro_list = DESKTOP_MACROS if device == "Desktop" else MOBILE_MACROS
        options = []
        for name, url, recommended in macro_list:
            clean = name.replace(" ✅", "").replace(" ❌", "")
            desc  = "✅ Recommended" if recommended else ("❌ Not recommended" if "❌" in name else "")
            options.append(discord.SelectOption(label=name, value=clean, description=desc[:50]))
        options.append(discord.SelectOption(label="Others — I'll type the name", value="__others__", description="My macro isn't listed here"))
        self.add_item(MacroDropdown(options, owner_id, device))
        self.add_item(BackToDeviceButton(owner_id))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "❌ This application has been claimed by someone else.", ephemeral=True)
            return False
        return True


class MacroDropdown(discord.ui.Select):
    def __init__(self, options, owner_id, device):
        super().__init__(placeholder="🔽 Select your macro...", options=options, min_values=1, max_values=1)
        self.owner_id = owner_id
        self.device   = device

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ This isn't your application.", ephemeral=True)
            return
        choice = self.values[0]
        if choice == "__others__":
            # Ask user to type the macro name via a modal
            modal = OthersMacroModal(self.owner_id, self.device)
            await interaction.response.send_modal(modal)
            return
        # Find URL
        macro_list = DESKTOP_MACROS if self.device == "Desktop" else MOBILE_MACROS
        url = "N/A"
        for name, u, _ in macro_list:
            clean = name.replace(" ✅", "").replace(" ❌", "")
            if clean == choice:
                url = u
                break
        app_state[self.owner_id].update({"macro": choice, "macro_url": url, "step": "hours"})
        view  = HoursInputView(self.owner_id)
        embed = _appli_embed(
            "📋  Step 3 — AFK Hours",
            f"You selected **{choice}**.\n\n"
            f"How many hours can you **AFK per day**?\n"
            f"Please enter a number (e.g. `3`, `4.5`).",
            0x00CED1,
        )
        embed.add_field(name="📥 How to answer", value="Click the button below to enter your hours.", inline=False)
        await interaction.response.edit_message(embed=embed, view=view)


class OthersMacroModal(discord.ui.Modal, title="Tell us your macro name"):
    macro_name = discord.ui.TextInput(
        label="Macro name",
        placeholder="e.g. MyCustomMacro",
        max_length=80,
    )

    def __init__(self, owner_id: int, device: str):
        super().__init__()
        self.owner_id = owner_id
        self.device   = device

    async def on_submit(self, interaction: discord.Interaction):
        name = self.macro_name.value.strip()
        app_state[self.owner_id].update({"macro": name, "macro_url": "N/A", "step": "hours"})
        view  = HoursInputView(self.owner_id)
        embed = _appli_embed(
            "📋  Step 3 — AFK Hours",
            f"You selected **{name}**.\n\n"
            f"How many hours can you **AFK per day**?\n"
            f"Please click the button below to enter your hours.",
            0x00CED1,
        )
        await interaction.response.edit_message(embed=embed, view=view)


class HoursInputView(discord.ui.View):
    """Step 3 — enter hours via modal."""
    def __init__(self, owner_id: int):
        super().__init__(timeout=300)
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ This isn't your application.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="⏰ Enter my AFK hours", style=discord.ButtonStyle.primary)
    async def enter_hours(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(HoursModal(self.owner_id))


class HoursModal(discord.ui.Modal, title="How many hours can you AFK per day?"):
    hours_input = discord.ui.TextInput(
        label="Hours per day (e.g. 3, 4.5, 8)",
        placeholder="Enter a number like 3 or 4.5",
        max_length=5,
    )

    def __init__(self, owner_id: int):
        super().__init__()
        self.owner_id = owner_id

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.hours_input.value.strip().replace(",", ".")
        try:
            hours = float(raw)
        except ValueError:
            await interaction.response.send_message(
                "❌ Please enter a valid number (e.g. `3` or `4.5`).", ephemeral=True)
            return

        app_state[self.owner_id]["hours"] = hours
        app_state[self.owner_id]["step"]  = "confirm_hours"

        # Calculate feedback
        if hours < 1:
            feedback = "⚠️ That's under 1 hour. **Try re-managing your time, okay?**"
            color    = 0xFF4500
            can_proceed = False
        elif hours < 3:
            feedback = "💛 That's under 3 hours. **A little higher would be better, okay?**"
            color    = 0xF59E0B
            can_proceed = False
        else:
            feedback = f"✅ {hours}h/day — **You will be a Trial Macroer, okay?**"
            color    = 0x00FFA3
            can_proceed = True

        # Calculate what time window they'd need to hit 3h
        if hours >= 3:
            needed_start = "Any time works!"
        else:
            needed_start = f"You would need to rearrange your day to find a solid **3-hour window**."

        view  = HoursConfirmView(self.owner_id, can_proceed)
        embed = _appli_embed(
            "📋  Step 3 — AFK Hours Result",
            f"You said: **{hours} hours/day**\n\n{feedback}\n\n📅 {needed_start}",
            color,
        )
        await interaction.response.edit_message(embed=embed, view=view)


class HoursConfirmView(discord.ui.View):
    """Step 3 confirm — Yes/No whether to continue."""
    def __init__(self, owner_id: int, can_proceed: bool):
        super().__init__(timeout=300)
        self.owner_id    = owner_id
        self.can_proceed = can_proceed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ This isn't your application.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="✅ Yes, continue", style=discord.ButtonStyle.success)
    async def yes_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.can_proceed:
            # Not enough hours — decline
            embed = _appli_embed(
                "❌  Application Declined",
                "Your available AFK time is too low to qualify.\n\n"
                "You need at least **3 hours/day** to become a Trial Macroer.\n"
                "Please re-manage your schedule and try again later!",
                0xFF2A2A,
            )
            await interaction.response.edit_message(embed=embed, view=None)
            return
        # Enough hours — show the note/agreement
        view  = AgreementView(self.owner_id)
        embed = _appli_embed(
            "📋  Step 4 — Server Agreement",
            "**ENG:**\nHi! Thank you for choosing my server as a place to macro! "
            "In order to gain access, you'll need to macro **3 hours** first to gain access, "
            "and then macro at least **4 hours each day** to maintain it. "
            "Please send your private server and ping a staff member. "
            "**Do you agree with that?**\n\n"
            "**VN:**\nChào! Cảm ơn bạn đã chọn máy chủ của tôi để chạy macro! "
            "Để được cấp quyền truy cập, bạn cần chạy macro **3 giờ** trước, "
            "sau đó chạy macro ít nhất **4 giờ mỗi ngày** để duy trì quyền đó. "
            "Vui lòng gửi private server của bạn và nhắn tin cho Staff. "
            "**Bạn có và đồng ý với điều này không?**",
            0x5865F2,
        )
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="❌ No, cancel", style=discord.ButtonStyle.danger)
    async def no_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = _appli_embed(
            "❌  Application Declined",
            "You chose not to continue. Your application has been declined.\n"
            "Feel free to apply again when you're ready!",
            0xFF2A2A,
        )
        await interaction.response.edit_message(embed=embed, view=None)
        app_state.pop(interaction.user.id, None)


class AgreementView(discord.ui.View):
    """Step 4 — agree to server rules then ask for afk time window."""
    def __init__(self, owner_id: int):
        super().__init__(timeout=300)
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ This isn't your application.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="✅ I Agree / Tôi Đồng Ý", style=discord.ButtonStyle.success)
    async def agree(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TimeWindowModal(self.owner_id))

    @discord.ui.button(label="❌ I Disagree / Không", style=discord.ButtonStyle.danger)
    async def disagree(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = _appli_embed(
            "❌  Application Declined",
            "You did not agree to the server terms.\n\n"
            "Your application has been **declined**.\n"
            "You may apply again whenever you change your mind!",
            0xFF2A2A,
        )
        await interaction.response.edit_message(embed=embed, view=None)
        app_state.pop(interaction.user.id, None)


class TimeWindowModal(discord.ui.Modal, title="When can you AFK? (Time window)"):
    time_window = discord.ui.TextInput(
        label="Your daily AFK time window",
        placeholder="e.g. 8 PM – 11 PM, or 20:00–23:00 UTC+7",
        max_length=100,
        style=discord.TextStyle.short,
    )

    def __init__(self, owner_id: int):
        super().__init__()
        self.owner_id = owner_id

    async def on_submit(self, interaction: discord.Interaction):
        window = self.time_window.value.strip()
        app_state[self.owner_id]["time_window"] = window
        app_state[self.owner_id]["step"]        = "final_confirm"

        view  = FinalConfirmView(self.owner_id)
        state = app_state[self.owner_id]
        embed = _build_application_summary_embed(interaction.user, state, preview=True)
        await interaction.response.edit_message(embed=embed, view=view)


class FinalConfirmView(discord.ui.View):
    """Step 5 — final yes/no to submit."""
    def __init__(self, owner_id: int):
        super().__init__(timeout=300)
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ This isn't your application.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="✅ Submit Application", style=discord.ButtonStyle.success)
    async def submit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _finalize_application(interaction)

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = _appli_embed(
            "❌  Application Cancelled",
            "Your application was cancelled at the final step.\nFeel free to apply again!",
            0xFF2A2A,
        )
        await interaction.response.edit_message(embed=embed, view=None)
        app_state.pop(interaction.user.id, None)


class BackToDeviceButton(discord.ui.Button):
    def __init__(self, owner_id):
        super().__init__(label="← Back", style=discord.ButtonStyle.secondary, row=1)
        self.owner_id = owner_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ This isn't your application.", ephemeral=True)
            return
        view  = DeviceSelectView(self.owner_id)
        embed = _build_application_start_embed()
        await interaction.response.edit_message(embed=embed, view=view)


# ─── Application Helpers ──────────────────────────────────────────────────────

def _has_wants_to_macro_role(member: discord.Member) -> bool:
    return any(r.id == WANTS_TO_MACRO_ROLE_ID for r in member.roles)

def _appli_embed(title: str, desc: str, color: int) -> discord.Embed:
    e = discord.Embed(title=title, description=desc, color=color,
                      timestamp=datetime.now(timezone.utc))
    e.set_footer(text="Macro Application  •  Zite Bot  •  Sol's RNG")
    return e

def _build_application_start_embed() -> discord.Embed:
    e = discord.Embed(
        title="📝  Macro Setup Application",
        description=(
            "Welcome to the **Macro Setup Application**!\n\n"
            "This survey helps our server managers understand your macro setup "
            "and availability.\n\n"
            "**Requirements:**\n"
            "> • You must have the **Wants to Macro** role\n"
            "> • You need at least **3 hours/day** to AFK\n"
            "> • You must agree to macro for **4+ hours/day** to maintain access\n\n"
            "**Select your device to begin:**"
        ),
        color=0x5865F2,
        timestamp=datetime.now(timezone.utc),
    )
    e.set_footer(text="Macro Application  •  Zite Bot  •  Sol's RNG")
    return e

def _build_application_summary_embed(member: discord.Member, state: dict, preview=False) -> discord.Embed:
    macro_list = DESKTOP_MACROS if state.get("device") == "Desktop" else MOBILE_MACROS
    macro_url  = state.get("macro_url", "N/A")
    # Try to find URL if it's from the known list
    for name, url, _ in macro_list:
        clean = name.replace(" ✅", "").replace(" ❌", "")
        if clean == state.get("macro"):
            macro_url = url
            break

    hours  = state.get("hours", "?")
    window = state.get("time_window", "Not specified")
    device = state.get("device", "?")
    macro  = state.get("macro", "?")

    color  = 0x00FFA3 if not preview else 0xF59E0B
    title  = ("📋  Application Summary (Preview)" if preview
               else f"✅  Application Submitted — {member.display_name}")

    e = discord.Embed(title=title, color=color, timestamp=datetime.now(timezone.utc))
    e.set_thumbnail(url=member.display_avatar.url)
    e.add_field(name="👤 Applicant",      value=f"{member.mention} (`{member}`)", inline=True)
    e.add_field(name="🆔 User ID",        value=f"`{member.id}`",                 inline=True)
    e.add_field(name="📅 Applied At",     value=f"`{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}`", inline=True)
    e.add_field(name="🖥️ Device",         value=f"`{device}`",                    inline=True)
    e.add_field(name="🤖 Macro Software", value=f"[{macro}]({macro_url})" if macro_url != "N/A" else f"`{macro}`", inline=True)
    e.add_field(name="⏰ AFK Hours/Day",  value=f"`{hours}h`",                    inline=True)
    e.add_field(name="🕐 AFK Time Window",value=f"`{window}`",                    inline=False)
    e.add_field(name="📌 Status",
                value="`🟡 Pending Review`" if preview else "`🟢 Submitted — Awaiting Staff`",
                inline=False)
    if not preview:
        e.add_field(
            name="📣 Next Steps",
            value=(
                "✅ You have been given the **Macro Trail Verifying** role.\n"
                "Please **send your private server link** and **ping a Staff member** to get started.\n\n"
                "💬 If you have any questions or struggles with the macro, "
                "**our staffs are here to help you!**"
            ),
            inline=False,
        )
    e.set_footer(text="Macro Application  •  Zite Bot  •  Sol's RNG")
    return e


async def _finalize_application(interaction: discord.Interaction):
    """Grant role, send DM, send to server-output, update message."""
    member = interaction.user
    state  = app_state.get(member.id, {})

    # Grant Macro Trail Verifying role
    guild = interaction.guild
    role  = guild.get_role(MACRO_TRAIL_VERIFYING_ROLE) if guild else None
    role_granted = False
    if role:
        try:
            await member.add_roles(role, reason="Macro application approved")
            role_granted = True
        except discord.Forbidden:
            log.warning(f"APPLI: Cannot grant role to {member}")

    # Build summary embed
    summary_embed = _build_application_summary_embed(member, state, preview=False)

    # Update the application message
    await interaction.response.edit_message(embed=summary_embed, view=None)

    # Send summary to user DM
    try:
        await member.send(
            content=(
                "✅ **Your Macro Application has been submitted!**\n\n"
                "If you have any questions or struggles with the macro, "
                "**our staffs are here to help you!** 🙌"
            ),
            embed=summary_embed,
        )
    except discord.Forbidden:
        log.warning(f"APPLI: Cannot DM {member} — DMs closed.")

    # Send copy to server-output
    server_output_ch = bot.get_channel(SERVER_OUTPUT_CHANNEL_ID)
    if server_output_ch:
        notif_embed = discord.Embed(
            title="📬  New Macro Application Submitted",
            description=f"{member.mention} has submitted a macro application!",
            color=0x00FFA3,
            timestamp=datetime.now(timezone.utc),
        )
        notif_embed.set_thumbnail(url=member.display_avatar.url)
        notif_embed.add_field(name="👤 User",          value=f"{member.mention} (`{member.id}`)", inline=True)
        notif_embed.add_field(name="🖥️ Device",        value=f"`{state.get('device','?')}`",      inline=True)
        notif_embed.add_field(name="🤖 Macro",         value=f"`{state.get('macro','?')}`",        inline=True)
        notif_embed.add_field(name="⏰ Hours/Day",     value=f"`{state.get('hours','?')}h`",        inline=True)
        notif_embed.add_field(name="🕐 AFK Window",   value=f"`{state.get('time_window','?')}`",   inline=True)
        notif_embed.add_field(name="🎭 Role Granted",  value="✅ Yes" if role_granted else "❌ Failed", inline=True)
        notif_embed.set_footer(text=f"Macro Application  •  Zite Bot  •  {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")
        await server_output_ch.send(embed=notif_embed)
        await server_output_ch.send(embed=summary_embed)

    log.info(f"APPLI: {member} submitted macro application | "
             f"device={state.get('device')} macro={state.get('macro')} "
             f"hours={state.get('hours')} role_granted={role_granted}")

    app_state.pop(member.id, None)


# ── 18. Bot Commands ──────────────────────────────────────────────────────────

@bot.command(name="macrosappli")
async def cmd_macros_appli(ctx):
    """
    Admin-deployable macro application form.
    Can be used in any channel whose name contains '-ticket'.
    """
    # Must be in a ticket channel
    if "-ticket" not in ctx.channel.name.lower():
        await ctx.send(
            embed=discord.Embed(
                description="❌ This command can only be used in ticket channels (channel name must contain `-ticket`).",
                color=0xFF2A2A,
            ),
            delete_after=10,
        )
        return

    # Delete the invoking message to keep the channel clean
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass

    embed = _build_application_start_embed()
    view  = DeviceSelectView(owner_id=0)   # owner_id=0 means "anyone can claim"
    msg   = await ctx.send(embed=embed, view=view)

    log.info(f"APPLI: Application posted in #{ctx.channel.name} by {ctx.author} (msg={msg.id})")


# ── 19. Bot Events ────────────────────────────────────────────────────────────

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
    if not live_event_cleanup.is_running():
        live_event_cleanup.start()


@bot.event
async def on_member_join(member: discord.Member):
    dest = bot.get_channel(WELCOME_CHANNEL_ID)
    if not dest:
        log.warning("WELCOME: server-output channel not found — skipping.")
        return

    joined_at        = member.joined_at or datetime.now(timezone.utc)
    created_at       = member.created_at
    account_age_days = (datetime.now(timezone.utc) - created_at).days

    embed = discord.Embed(
        title=f"👋  Welcome to {member.guild.name}!",
        description=(
            f"Hey {member.mention}, glad you're here! 🎉\n\n"
            f"**Getting started:**\n"
            f"> **1.** Read the server rules in your rules channel.\n"
            f"> **2.** Use `!macrosappli` in your ticket channel to apply to macro.\n"
            f"> **3.** Use `!live` to see all active biome & merchant sessions.\n\n"
            f"If you need help, tag a moderator or ask in the right channel. Have fun! 🚀"
        ),
        color=0x00FFA3,
        timestamp=joined_at,
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="👤 Username",    value=f"`{member}`",                   inline=True)
    embed.add_field(name="🆔 User ID",     value=f"`{member.id}`",                inline=True)
    embed.add_field(name="📅 Account Age", value=f"`{account_age_days} days`",    inline=True)
    embed.add_field(name="👥 Member #",    value=f"`{member.guild.member_count}`", inline=True)
    embed.set_footer(text=f"Welcome  •  {member.guild.name}  •  {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")

    try:
        await dest.send(embed=embed)
        log.info(f"WELCOME: Sent welcome to {member} in #{dest.name}")
    except discord.Forbidden:
        log.warning(f"WELCOME: Missing permission to send in #{dest.name}")
    except Exception as e:
        log.error(f"WELCOME: {e}")


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
    if isinstance(error, commands.CommandNotFound):
        return
    log.error(f"CMD ERROR in #{ctx.channel.name}: {error}")


@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return

    # ── website-output: auto-pin errors ──────────────────────────────────
    if message.channel.id == EXTENDED_LOG_CHANNEL_ID and message.content:
        await maybe_auto_pin_error(message)

    # ── Allow commands ────────────────────────────────────────────────────
    await bot.process_commands(message)

    # ── Skip non-monitored channels ───────────────────────────────────────
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

    # Detect macro source from first embed (most reliable)
    macro_source = "Unknown Macro"
    if message.embeds:
        macro_source = _detect_macro_source(message.embeds[0])

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

        # Use roblox_link as account key, or fallback to account number
        if roblox_link:
            acc_reg = webhook_activity[cid_str]["accounts"]
            if roblox_link not in acc_reg:
                acc_reg[roblox_link] = {
                    "display_name": f"Account {len(acc_reg)+1}",
                    "biomes": {}, "merchants": {}, "completed_sessions": [],
                    "macro_source": macro_source,
                }
            account_identity = acc_reg[roblox_link]["display_name"]
        else:
            # Coteab and others may not have PS link in start message
            # Try to find an existing account or create one per channel
            acc_reg = webhook_activity[cid_str]["accounts"]
            # Use a sentinel key per macro source so we can still track
            sentinel_key = f"__no_link_{macro_source}_{cid_str}__"
            if sentinel_key not in acc_reg:
                acc_reg[sentinel_key] = {
                    "display_name": f"Account {len(acc_reg)+1} [{macro_source}]",
                    "biomes": {}, "merchants": {}, "completed_sessions": [],
                    "macro_source": macro_source,
                }
            account_identity = acc_reg[sentinel_key]["display_name"]
    else:
        account_identity = "Forwarder Source"

    if not message.embeds:
        return

    guild_name = message.guild.name if message.guild else "Private Guild"

    for emb in message.embeds:
        # Per-embed link extraction (Coteab puts PS in embed field)
        emb_link, emb_vector = _extract_private_server_link(emb, macro_source)
        if emb_link:
            roblox_link = emb_link
            link_vector = emb_vector
            # Re-register under the correct PS link key
            if not is_forwarder and roblox_link:
                acc_reg = webhook_activity[cid_str]["accounts"]
                if roblox_link not in acc_reg:
                    acc_reg[roblox_link] = {
                        "display_name": f"Account {len(acc_reg)+1}",
                        "biomes": {}, "merchants": {}, "completed_sessions": [],
                        "macro_source": macro_source,
                    }
                account_identity = acc_reg[roblox_link]["display_name"]

        parts = []
        if emb.title:                       parts.append(emb.title)
        if emb.description:                 parts.append(emb.description)
        if emb.author and emb.author.name:  parts.append(emb.author.name)
        if emb.footer and emb.footer.text:  parts.append(emb.footer.text)
        for f in emb.fields:
            if f.name:  parts.append(f.name)
            if f.value: parts.append(f.value)

        combined_text  = " ".join(parts)
        combined_lower = combined_text.lower()
        is_start       = bool(EVENT_START_RE.search(combined_lower))
        is_end         = bool(EVENT_END_RE.search(combined_lower))

        if not is_start and not is_end:
            continue

        is_merchant = any(kw in combined_lower for kw in
                          ("merchant", "mari", "jester", "rin", "black merchant"))
        if is_merchant:
            await _process_merchant(message, combined_lower, is_start, cid_str,
                                    now_iso, guild_name, roblox_link, link_vector,
                                    account_identity, is_forwarder, t0, macro_source)
        else:
            await _process_biome(message, combined_text, combined_lower, is_start,
                                 cid_str, now_iso, guild_name, roblox_link, link_vector,
                                 account_identity, is_forwarder, t0, macro_source)


# ── Boot ──────────────────────────────────────────────────────────────────────
threading.Thread(target=keep_alive, daemon=True).start()

TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)
else:
    print("Error: DISCORD_TOKEN environment variable not set.")
