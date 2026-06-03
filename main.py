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
    format='[%(levelname)s] %(message)s',
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
        logging.info("🔗 Successfully connected to the Supabase database backend!")
    except Exception as e:
        logging.error(f"❌ Failed to connect to Supabase: {e}")
else:
    logging.warning("⚠️ Supabase credentials missing. Data will log to console but won't save to the database.")

# ==========================================
# 3. DISCORD BOT SETUP
# ==========================================
intents = discord.Intents.default()
intents.message_content = True  
bot = commands.Bot(command_prefix="!", intents=intents)

raw_channels = os.getenv("CHANNEL_IDS", "")
MONITORED_CHANNELS = [int(cid.strip()) for cid in raw_channels.split(",") if cid.strip().isdigit()]

def extract_roblox_link(text):
    match = re.search(r'https://www.roblox.com/share?code=[^s]+', text)
    return match.group(0) if match else None

@bot.event
async def on_ready():
    logging.info(f"🚀 {bot.user.name} has successfully logged into Discord Gateway!")
    logging.info(f"📢 Target Monitored IDs from Render: {MONITORED_CHANNELS}")
    
    # 👇 DIAGNOSTIC TRACKER: Prints every single channel the bot can actually access
    logging.info("📋 --- START OF VISIBLE CHANNELS CHECKLIST ---")
    for guild in bot.guilds:
        logging.info(f"🏰 Server Name: {guild.name}")
        for channel in guild.text_channels:
            logging.info(f"   🔹 ID: {channel.id} | Name: #{channel.name}")
    logging.info("📋 --- END OF VISIBLE CHANNELS CHECKLIST ---")

@bot.event
async def on_message(message):
    # Forced streaming trace tracker
    logging.info(f"📩 [DEBUG] Bot captured an event from '{message.author}' in Channel ID: {message.channel.id}")
    
    if message.channel.id not in MONITORED_CHANNELS:
        return

    text_to_search = message.content or ""
    
    if message.embeds:
        logging.info(f"📦 [DEBUG] Message contains {len(message.embeds)} embed structure(s). Parsing content fields...")
        for embed in message.embeds:
            if embed.title:
                text_to_search += f"\n{embed.title}"
                logging.info(f"   🔹 Title parsed: {embed.title}")
            if embed.description:
                text_to_search += f"\n{embed.description}"
            for field in embed.fields:
                text_to_search += f"\n{field.name} {field.value}"

    if not text_to_search.strip():
        logging.warning("⚠️ [DEBUG] Captured message text content is completely empty.")
        return

    if "Biome Started" in text_to_search:
        biome_match = re.search(r'(?:Biome Started[:\-]\s*)([A-Z_a-z0-9\s]+)', text_to_search)
        biome_name = biome_match.group(1).strip() if biome_match else "Unknown Biome"
        
        if "\n" in biome_name:
            biome_name = biome_name.split("\n")[0].strip()
            
        roblox_link = extract_roblox_link(text_to_search)
        
        logging.info(f"🎯 Snipe detected! Parsed Biome: {biome_name}")
        
        if roblox_link:
            logging.info(f"🔗 Server Link: {roblox_link}")
            
            if supabase:
                try:
                    data, count = supabase.table("servers").insert({
                        "server_link": roblox_link, 
                        "biome_name": biome_name
                    }).execute()
                    logging.info("✅ Successfully pushed new server entry to Supabase backend!")
                except Exception as db_err:
                    logging.error(f"❌ Database insert failed: {db_err}")
        else:
            logging.warning("⚠️ Biome matched, but no Roblox share link was found in the text data.")
    else:
        logging.info("❌ [DEBUG] Message dropped inside monitored channel, but 'Biome Started' phrase keyword was missing.")

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
