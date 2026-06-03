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

# --- CONFIG & INTENTS ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S %p')
intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
DATA_STORE_PATH = "metrics_store.json"
AUTO_DETECT_CONTAINERS = {1501595856493740162, 1511360799996907710, 1509915924663238776}
dynamic_detected_channels = set()

# --- GLOBAL STORAGE ---
biome_counts = {}
merchant_counts = {}
webhook_activity = {}
active_live_events = {} 
_departure_warned = set()

# --- REGEX & LIMITS ---
ROBLOX_LINK_RE = re.compile(r"https://www\.roblox\.com/share\?\S+")
EVENT_START_RE = re.compile(r"\b(started|start|spawned|arrived|appeared|has arrived|is here)\b", re.IGNORECASE)
EVENT_END_RE = re.compile(r"\b(ended|end|despawned|left|gone|has left|disappeared|expired|timed out)\b", re.IGNORECASE)
BIOME_MATCH_RE = re.compile(r"(?:Biome\s+(?:Started|Ended)(?:\s*:\s*|\s*-\s*))([A-Z_]+)", re.IGNORECASE)

EVENT_SESSION_LIMITS = {
    "WINDY": 120, "SNOWY": 120, "RAINY": 120, "SAND STORM": 650, "HELL": 666, 
    "STARFALL": 650, "HEAVEN": 240, "NULL": 99, "GLITCHED": 164, "DREAMSPACE": 192, 
    "CYBERSPACE": 720, "SINGULARITY": 1200, "MARI (MERCHANT)": 180, 
    "JESTER (MERCHANT)": 180, "RIN (MERCHANT)": 180, "MYSTERIOUS MERCHANT": 180, 
    "TRAVELING MERCHANT": 180, "MERCHANT": 180
}

# --- CORE FUNCTIONS ---

def save_persisted_metrics():
    try:
        payload = {"biomes": biome_counts, "merchants": merchant_counts, "webhook_activity": webhook_activity}
        with open(DATA_STORE_PATH, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logging.error(f"Failed writing to disk: {e}")

def load_persisted_metrics():
    global biome_counts, merchant_counts, webhook_activity
    if os.path.exists(DATA_STORE_PATH):
        try:
            with open(DATA_STORE_PATH, 'r', encoding='utf-8') as f:
                stored = json.load(f)
                biome_counts = stored.get("biomes", {})
                merchant_counts = stored.get("merchants", {})
                webhook_activity = stored.get("webhook_activity", {})
        except: pass

def get_metrics_payload():
    now = datetime.now(timezone.utc)
    # Ghost session cleaner: Remove items that have exceeded their timeout
    for key, ev in list(active_live_events.items()):
        start_time = datetime.fromisoformat(ev['started_at'])
        limit = EVENT_SESSION_LIMITS.get(ev['name'].upper(), 300)
        if (now - start_time).total_seconds() > limit:
            active_live_events.pop(key, None)

    return {
        "status": "ONLINE",
        "telemetry": {
            "total_registered_webhooks": len(webhook_activity),
            "grand_total_biomes": sum(biome_counts.values()),
            "grand_total_merchants": sum(merchant_counts.values()),
        },
        "live_events": list(active_live_events.values()),
        "raw_webhook_registry": webhook_activity,
    }

# --- WEB SERVER ---
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(get_metrics_payload(), ensure_ascii=False).encode())

def keep_alive():
    server = HTTPServer(('0.0.0.0', int(os.getenv("PORT", 10000))), HealthHandler)
    server.serve_forever()

# --- BOT LOGIC ---
@bot.event
async def on_ready():
    load_persisted_metrics()
    logging.info("System Online. Tracking active.")

@bot.event
async def on_message(message):
    if message.author == bot.user: return
    
    # 1. Parsing
    combined_text = (message.content or "") + " " + " ".join([e.title or "" for e in message.embeds])
    combined_lower = combined_text.lower()
    
    is_start = bool(EVENT_START_RE.search(combined_lower))
    is_end = bool(EVENT_END_RE.search(combined_lower))
    
    if not is_start and not is_end: return

    # 2. Identify
    is_merchant = any(m in combined_lower for m in ["merchant", "mari", "jester", "rin"])
    
    if is_merchant:
        if "mysterious" in combined_lower: name = "MYSTERIOUS MERCHANT"
        elif "traveling" in combined_lower: name = "TRAVELING MERCHANT"
        elif "mari" in combined_lower: name = "MARI (MERCHANT)"
        elif "jester" in combined_lower: name = "JESTER (MERCHANT)"
        elif "rin" in combined_lower: name = "RIN (MERCHANT)"
        else: name = "MERCHANT"
    else:
        # Simple biome detection
        name = "UNKNOWN BIOME"
        for b in EVENT_SESSION_LIMITS:
            if b.lower() in combined_lower: name = b

    # 3. State Management
    key = f"{message.channel.id}_{name}"
    
    if is_start:
        active_live_events[key] = {
            "name": name,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "channel_name": message.channel.name,
            "type": "merchant" if is_merchant else "biome"
        }
        if is_merchant: merchant_counts[name] = merchant_counts.get(name, 0) + 1
        else: biome_counts[name] = biome_counts.get(name, 0) + 1
    
    elif is_end:
        active_live_events.pop(key, None)

    save_persisted_metrics()

# Run
threading.Thread(target=keep_alive, daemon=True).start()
bot.run(os.getenv("DISCORD_TOKEN"))
