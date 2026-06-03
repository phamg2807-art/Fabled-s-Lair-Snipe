import os
import re
import asyncio
from flask import Flask
from threading import Thread
import discord
from discord.ext import commands

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
# 2. DISCORD BOT SETUP
# ==========================================
intents = discord.Intents.default()
intents.message_content = True  # Crucial for reading message data
bot = commands.Bot(command_code="!", intents=intents)

# Fetch channel IDs from environment variable
raw_channels = os.getenv("CHANNEL_IDS", "")
MONITORED_CHANNELS = [int(cid.strip()) for cid in raw_channels.split(",") if cid.strip().isdigit()]

def extract_roblox_link(text):
    """Helper to find Roblox server links in text structures."""
    match = re.search(r'https://www\.roblox\.com/share\?code=[^\s\s]+', text)
    return match.group(0) if match else None

@bot.event
async def on_ready():
    print(f"🚀 {bot.user.name} has successfully logged into Discord Gateway!")
    print(f"📢 Active Monitoring Channels: {MONITORED_CHANNELS}")

@bot.event
async def on_message(message):
    # Ensure the message is arriving in one of our target channel IDs
    if message.channel.id not in MONITORED_CHANNELS:
        return

    text_to_search = message.content or ""
    
    # --- WEBHOOK EMBED PARSING ---
    # Extract data if the macro message is formatted inside an embed structure
    if message.embeds:
        for embed in message.embeds:
            if embed.title:
                text_to_search += f"\n{embed.title}"
            if embed.description:
                text_to_search += f"\n{embed.description}"
            for field in embed.fields:
                text_to_search += f"\n{field.name} {field.value}"

    # If there's no usable text data, skip processing
    if not text_to_search.strip():
        return

    # Look for biome trigger phrases
    if "Biome Started" in text_to_search or "Biome Started:" in text_to_search:
        # Pull out the biome name using regex patterns
        biome_match = re.search(r'(?:Biome Started[:\-]\s*)([A-Z_a-z0-9\s]+)', text_to_search)
        biome_name = biome_match.group(1).strip() if biome_match else "Unknown Biome"
        
        # Clean up common secondary text lines from the match
        if "\n" in biome_name:
            biome_name = biome_name.split("\n")[0].strip()
            
        roblox_link = extract_roblox_link(text_to_search)
        
        print(f"🎯 Snipe detected! Parsed Biome: {biome_name}")
        if roblox_link:
            print(f"🔗 Server Link: {roblox_link}")
        else:
            print("⚠️ Biome matched, but no Roblox share link was found in the text data.")

    await bot.process_commands(message)

# ==========================================
# 3. EXECUTION LAYOUT
# ==========================================
if __name__ == "__main__":
    # Start up the web ping utility thread
    server_thread = Thread(target=run_server)
    server_thread.daemon = True
    server_thread.start()
    
    # Fire up the Discord Gateway
    token = os.getenv("DISCORD_BOT_TOKEN")
    if token:
        bot.run(token)
    else:
        print("❌ CRITICAL ERROR: 'DISCORD_BOT_TOKEN' environment variable is missing!")
