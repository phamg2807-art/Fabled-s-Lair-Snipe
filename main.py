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

# --- CONFIGURATION ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S %p')
intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.message_content = True 

bot = commands.Bot(command_prefix="!", intents=intents)
DATA_STORE_PATH = "metrics_store.json"
AUTO_DETECT_CONTAINERS = {1501595856493740162, 1511360799996907710, 1509915924663238776}
manually_added_channels = set()
active_live_events = {}
webhook_activity = {}
biome_counts = {}
merchant_counts = {}
metrics_cache = {}

# --- REGEX & LIMITS ---
ROBLOX_LINK_RE = re.compile(r"https://www\.roblox\.com/share\?\S+")
EVENT_START_RE = re.compile(r"\b(started|start|spawned|arrived|appeared|has arrived|is here)\b", re.IGNORECASE)
EVENT_END_RE = re.compile(r"\b(ended|end|despawned|left|gone|has left|disappeared|expired|timed out)\b", re.IGNORECASE)

EVENT_SESSION_LIMITS = {
    "WINDY": 120, "SNOWY": 120, "RAINY": 120, "SAND STORM": 650, "HELL": 666, 
    "STARFALL": 650, "HEAVEN": 240, "NULL": 99, "GLITCHED": 164, "DREAMSPACE": 192, 
    "CYBERSPACE": 720, "SINGULARITY": 1200, "MARI (MERCHANT)": 180, 
    "JESTER (MERCHANT)": 180, "RIN (MERCHANT)": 180, "MYSTERIOUS MERCHANT": 180, 
    "TRAVELING MERCHANT": 180, "MERCHANT": 180
}

# --- CORE ENGINE FUNCTIONS ---

def update_metrics_cache():
    """Pre-calculates data so the Dashboard remains lightning fast."""
    global metrics_cache
    now = datetime.now(timezone.utc)
    metrics_cache = {
        "status": "ONLINE",
        "telemetry": {
            "total_registered_webhooks": len(webhook_activity),
            "grand_total_biomes": sum(biome_counts.values()),
            "grand_total_merchants": sum(merchant_counts.values())
        },
        "live_events": list(active_live_events.values()),
        "raw_webhook_registry": webhook_activity
    }

def cleanup_expired_sessions():
    """Automatically removes events that have exceeded their hard-coded time limits."""
    now = datetime.now(timezone.utc)
    changed = False
    for key, event in list(active_live_events.items()):
        start_time = datetime.fromisoformat(event['started_at'])
        limit = EVENT_SESSION_LIMITS.get(event['name'].upper(), 300) # Default 5m
        if (now - start_time).total_seconds() > limit:
            active_live_events.pop(key, None)
            changed = True
    if changed:
        update_metrics_cache()

def save_data():
    data = {
        "biomes": biome_counts,
        "merchants": merchant_counts,
        "webhook_activity": webhook_activity,
        "manually_added_channels": list(manually_added_channels)
    }
    with open(DATA_STORE_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    update_metrics_cache()

def load_data():
    global biome_counts, merchant_counts, webhook_activity, manually_added_channels
    if os.path.exists(DATA_STORE_PATH):
        try:
            with open(DATA_STORE_PATH, 'r', encoding='utf-8') as f:
                d = json.load(f)
                biome_counts = d.get("biomes", {})
                merchant_counts = d.get("merchants", {})
                webhook_activity = d.get("webhook_activity", {})
                manually_added_channels = set(d.get("manually_added_channels", []))
                update_metrics_cache()
        except: pass

# --- WEB SERVER ---

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(metrics_cache).encode())

def keep_alive():
    server = HTTPServer(('0.0.0.0', int(os.getenv("PORT", 10000))), HealthHandler)
    server.serve_forever()

# --- BOT LOGIC ---

@bot.command()
async def addchannel(ctx, channel: discord.TextChannel = None):
    if not channel: return
    manually_added_channels.add(channel.id)
    save_data()
    await ctx.send(f"✅ Tracking: #{channel.name}")

@bot.event
async def on_ready():
    load_data()
    logging.info("Bot Online & Tracking.")

@bot.event
async def on_message(message):
    if message.author == bot.user: return
    await bot.process_commands(message)

    # 1. Filter Channels
    is_monitored = message.channel.id in manually_added_channels or "webhook" in message.channel.name.lower()
    if not is_monitored: return

    # 2. Cleanup expired sessions before processing
    cleanup_expired_sessions()

    # 3. Parse Message
    txt = (message.content or "") + " " + " ".join([e.title or "" for e in message.embeds])
    txt_lower = txt.lower()
    
    # Identify Event
    is_start = bool(EVENT_START_RE.search(txt_lower))
    is_end = bool(EVENT_END_RE.search(txt_lower))
    if not is_start and not is_end: return

    # Identify Name (Merchant or Biome)
    found_name = None
    for m in ["MARI", "JESTER", "RIN", "MYSTERIOUS", "TRAVELING", "MERCHANT"]:
        if m.lower() in txt_lower: found_name = f"{m} (MERCHANT)"
    if not found_name:
        for b in EVENT_SESSION_LIMITS:
            if b.lower() in txt_lower: found_name = b

    if not found_name: return

    # 4. State Management
    key = f"{message.channel.id}_{found_name}"
    
    if is_start:
        active_live_events[key] = {
            "name": found_name,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "channel_name": message.channel.name
        }
        if "MERCHANT" in found_name: merchant_counts[found_name] = merchant_counts.get(found_name, 0) + 1
        else: biome_counts[found_name] = biome_counts.get(found_name, 0) + 1
        
    elif is_end:
        active_live_events.pop(key, None)

    save_data()

# Run
threading.Thread(target=keep_alive, daemon=True).start()
bot.run(os.getenv("DISCORD_TOKEN"))
