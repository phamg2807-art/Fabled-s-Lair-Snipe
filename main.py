import os
import re
import logging
from flask import Flask
from threading import Thread
import discord
from discord.ext import commands
from supabase import create_client, Client

# ==========================================
# 0. STREAM LOGGING & SILENCE FLASK SPAM
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[logging.StreamHandler()]
)

# This line completely shuts up the annoying "GET / HTTP/1.1" console logs
logging.getLogger('werkzeug').setLevel(logging.ERROR)

# ==========================================
# 1. HEALTH CHECK SERVER FOR RENDER
# ==========================================
app = Flask('')

@app.route('/')
def home():
    return "Your Fabled Helper Bot is completely alive!", 200

@app.route('/healthz')
def healthz():
    return "OK", 200

def run_server():
    app.run(host='0.0.0.0', port=8080)

# ==========================================
# 2. SUPABASE DATABASE SETUP
# ==========================================
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
supabase: Client = None

if supabase_url and supabase_key:
    try:
        supabase = create_client(supabase_url, supabase_key)
        logging.info("🔗 Connected securely to the Supabase database backend cluster.")
    except Exception as e:
        logging.error(f"❌ Failed to connect to Supabase: {e}")
else:
    logging.warning("⚠️ Supabase credentials missing. Running in standalone local logging mode.")

# ==========================================
# 3. DISCORD BOT SETUP
# ==========================================
intents = discord.Intents.default()
intents.message_content = True  
bot = commands.Bot(command_prefix="!", intents=intents)

raw_channels = os.getenv("CHANNEL_IDS", "")
MONITORED_CHANNELS = [int(cid.strip()) for cid in raw_channels.split(",") if cid.strip().isdigit()]

# The list of keywords that identify a snipe/drop channel dynamically
TARGET_KEYWORDS = ["webhook", "forward", "found", "macro"]

def extract_roblox_link(text):
    # Upgraded Regex: Captures any variant of roblox.com links while safely ignoring trailing markdown ) or ]
    match = re.search(r'https://(?:[a-zA-Z0-9\-]+\.)?roblox\.com/[^\s\)\}\]\"\']+', text)
    return match.group(0) if match else None

def clean_entity_name(raw_name):
    """Deep cleans names by removing markdown artifacts, formatting leaks, and stray emojis."""
    if not raw_name:
        return ""
    # Strip markdown emphasis blocks
    clean = raw_name.replace("**", "").replace("*", "").replace("__", "").replace("`", "").strip()
    # Strip custom Discord timestamps/tags like <t:1780458194:F>
    clean = re.sub(r'<[^>]+>', '', clean).strip()
    # Strip leading weird symbols, non-alphanumeric clutter, and layout emojis
    clean = re.sub(r'^[^A-Za-z0-9\s\(]+', '', clean).strip()
    # Collapse multiple consecutive blank spaces into a single space
    clean = re.sub(r'\s+', ' ', clean)
    
    # Catch structural edge cases where a label header leaks into the field value
    if clean.lower() in ["started", "ended", "spawned", "arrived", "unknown", ""]:
        return ""
    return clean

@bot.event
async def on_ready():
    print("\n" + "="*60)
    logging.info(f"🚀 SYSTEM ONLINE: {bot.user.name} logged into Discord Gateway successfully.")
    logging.info(f"📢 Active Hardcoded Fallbacks: {MONITORED_CHANNELS}")
    print("="*60)
    
    logging.info("📋 --- START OF VISIBLE CHANNELS CHECKLIST ---")
    for guild in bot.guilds:
        logging.info(f"🏰 Server: {guild.name}")
        for channel in guild.text_channels:
            is_target = any(keyword in channel.name.lower() for keyword in TARGET_KEYWORDS)
            tag = "[🔥 TARGET MATCH]" if is_target else "[🔹 Text Context]"
            # FIXED: Converted channel.id to string before running string space justification padding
            logging.info(f"   {tag} ID: {str(channel.id).ljust(19)} | #{channel.name}")
    logging.info("📋 --- END OF VISIBLE CHANNELS CHECKLIST ---")
    print("="*60 + "\n")

@bot.event
async def on_message(message):
    # Ignore messages sent by the bot itself to prevent infinite loops
    if message.author == bot.user:
        return

    # Fetch channel metadata safely
    channel_name = getattr(message.channel, "name", "").lower()
    guild_name = getattr(message.channel.guild, "name", "Direct Message / Unknown")
    
    # Check if the channel matches any of our dynamic target keywords OR the backup ID list
    is_target_channel = any(keyword in channel_name for keyword in TARGET_KEYWORDS)
    is_fallback_id = message.channel.id in MONITORED_CHANNELS

    # If it fails both checks, drop it immediately without logging to keep streaming output pristine
    if not (is_target_channel or is_fallback_id):
        return

    text_to_search = message.content or ""
    
    # Restructured tracking labels to break down separate embed elements elegantly
    if message.embeds:
        for embed in message.embeds:
            if embed.title:
                text_to_search += f"\nTitle: {embed.title}"
            if embed.description:
                text_to_search += f"\nDescription: {embed.description}"
            for field in embed.fields:
                text_to_search += f"\nField Name: {field.name}\nField Value: {field.value}"

    if not text_to_search.strip():
        return

    # Dynamic parsing logic for both Biomes and Traveling Merchants
    is_biome = "Biome Started" in text_to_search
    is_merchant = any(k in text_to_search for k in ["Merchant", "Mari", "Jester"])

    if is_biome or is_merchant:
        entity_name = ""
        event_type = "BIOME DROP" if is_biome else "MERCHANT SPAWN"
        
        # ------------------------------------------------------------
        # STRATIFIED BIOME EXTRACTION LAYER
        # ------------------------------------------------------------
        if is_biome:
            # Strategy A: Same-line extraction
            biome_match = re.search(r'Biome\s*Started[\s\*\:\-]*([^\n]+)', text_to_search, re.IGNORECASE)
            if biome_match:
                entity_name = clean_entity_name(biome_match.group(1))
            
            # Strategy B: Multi-line / Separate Field layout translation
            if not entity_name:
                lines = text_to_search.split("\n")
                for i, line in enumerate(lines):
                    if "biome started" in line.lower() and i + 1 < len(lines):
                        next_line = lines[i+1]
                        if "field value:" in next_line.lower():
                            entity_name = clean_entity_name(next_line.split("Field Value:", 1)[1])
                            break
                        else:
                            entity_name = clean_entity_name(next_line)
                            if entity_name: 
                                break

            # Strategy C: General structural keyword fallback catch
            if not entity_name:
                for line in text_to_search.split("\n"):
                    if "biome:" in line.lower() and "started" not in line.lower():
                        entity_name = clean_entity_name(line.split("Biome:", 1)[1])
                        if entity_name: 
                            break
            
            if not entity_name:
                entity_name = "Unknown Biome"
            
        # ------------------------------------------------------------
        # STRATIFIED MERCHANT EXTRACTION LAYER
        # ------------------------------------------------------------
        else:
            if "Mari" in text_to_search:
                entity_name = "Merchant (Mari)"
            elif "Jester" in text_to_search:
                entity_name = "Merchant (Jester)"
            else:
                # Strategy A: Same-line extraction
                merchant_match = re.search(r'Merchant(?:s)?(?:[\s\w]+)?[\s\*\:\-]*([^\n]+)', text_to_search, re.IGNORECASE)
                if merchant_match:
                    entity_name = clean_entity_name(merchant_match.group(1))
                
                # Strategy B: Multi-line layout translation
                if not entity_name:
                    lines = text_to_search.split("\n")
                    for i, line in enumerate(lines):
                        if "merchant" in line.lower() and i + 1 < len(lines):
                            next_line = lines[i+1]
                            if "field value:" in next_line.lower():
                                entity_name = clean_entity_name(next_line.split("Field Value:", 1)[1])
                                break
                            else:
                                entity_name = clean_entity_name(next_line)
                                if entity_name: 
                                    break
                
                if not entity_name:
                    entity_name = "Traveling Merchant"
            
        roblox_link = extract_roblox_link(text_to_search)
        
        # ------------------------------------------------------------
        # CLEAN & DETAILED VISUAL TERMINAL DASHBOARD
        # ------------------------------------------------------------
        print("\n" + "═"*60)
        print(f" 🎯 EXTRACTION LOG - {event_type}")
        print("─"*60)
        print(f" 🏰 Server Name : {guild_name}")
        print(f" 📺 Channel     : #{getattr(message.channel, 'name', 'Unknown')} (ID: {message.channel.id})")
        print(f" 👤 Author      : {message.author}")
        print(f" ✨ Parsed Item : {entity_name}")
        print(f" 🔗 Link Found  : {roblox_link if roblox_link else 'None'}")
        print("─"*60)
        
        if roblox_link:
            if supabase:
                try:
                    data, count = supabase.table("servers").insert({
                        "server_link": roblox_link, 
                        "biome_name": entity_name
                    }).execute()
                    print(" ✅ STATUS      : Successfully pushed to Supabase DB Backend!")
                except Exception as db_err:
                    print(f" ❌ STATUS      : Supabase Database Write Failure: {db_err}")
            else:
                print(" ⚠️ STATUS      : Skipped DB save (Supabase client uninitialized)")
        else:
            print(" ⚠️ STATUS      : Aborted DB save due to missing Roblox server link.")
        print("═"*60 + "\n")
        
    else:
        # Structured fine-grained trace logs for messages that dropped without matched triggers
        logging.info(f"📥 [FILTERED] Msg from '{message.author}' in #{getattr(message.channel, 'name', 'Unknown')} dropped (No keyword matches found).")

    await bot.process_commands(message)

# ==========================================
# 4. EXECUTION LAYOUT
# ==========================================
if __name__ == "__main__":
    server_thread = Thread(target=run_server)
    server_thread.daemon = True
    server_thread.start()
    
    token = os.getenv("DISCORD_BOT_TOKEN")
    if token:
        bot.run(token)
    else:
        logging.error("❌ CRITICAL ERROR: 'DISCORD_BOT_TOKEN' environment variable is missing!")
