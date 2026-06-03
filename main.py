import discord
import requests
import re
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from discord.ext import commands

# --- TINY WEB SERVER FOR RENDER FREE TIER ---
class HealthCheckServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

def run_health_server():
    # Render passes a PORT variable automatically on the free tier
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckServer)
    print(f"🌐 Internal web server listening on port {port}")
    server.serve_forever()

# Start the web server in a separate background thread so it doesn't block the Discord bot
threading.Thread(target=run_health_server, daemon=True).start()
# --------------------------------------------

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TARGET_CHANNELS = [int(cid.strip()) for cid in os.getenv("CHANNEL_IDS", "").split(",") if cid.strip()]

if not TOKEN:
    print("❌ ERROR: DISCORD_BOT_TOKEN environment variable is missing!")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

def clean_biome_name(raw_text):
    if not raw_text:
        return "Normal"
    text = raw_text.upper()
    if "ENDED" in text or "LEFT" in text:
        return None
    text = text.replace("BIOME STARTED", "").replace("HAS STARTED!", "").replace("PRIVATE SERVER", "")
    text = re.sub(r'[:\-\[\]\(\)]', '', text).strip()
    return text.capitalize() if text else "Normal"

@bot.event
async def on_ready():
    print(f"🟢 Fabled's Lair Multi-Macro Bot is online as {bot.user}")
    print(f"📢 Monitoring Channels: {TARGET_CHANNELS}")

@bot.event
async def on_message(message):
    if message.channel.id in TARGET_CHANNELS and message.webhook_id:
        biome = "Normal"
        roblox_link = None
        raw_title = ""
        
        if message.embeds:
            for embed in message.embeds:
                embed_dict = embed.to_dict()
                if embed.title:
                    raw_title = embed.title
                elif embed.description and not raw_title:
                    raw_title = embed.description
                links = re.findall(r'(https://www.roblox.com/share?code=[^s"\'>]+)', str(embed_dict))
                if links:
                    roblox_link = links[0].split(')')[0].split(']')[0]

        if not roblox_link:
            links = re.findall(r'(https://www.roblox.com/share?code=[^s"\'>]+)', message.content)
            if links:
                roblox_link = links[0]
            if message.content and not raw_title:
                raw_title = message.content

        biome = clean_biome_name(raw_title)
        if biome is None:
            return

        if roblox_link:
            print(f"🎯 Snipe detected! Parsed Biome: {biome}")
            if not SUPABASE_URL or not SUPABASE_KEY:
                print(f"⚠️ Supabase setup pending. Link: {roblox_link}")
                return
            headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates"}
            payload = {"server_link": roblox_link, "biome_name": biome}
            try:
                response = requests.post(SUPABASE_URL, json=payload, headers=headers)
                print(f"📊 Database sync status: {response.status_code}")
            except Exception as e:
                print(f"❌ Database error: {e}")

    await bot.process_commands(message)

if TOKEN:
    bot.run(TOKEN)
