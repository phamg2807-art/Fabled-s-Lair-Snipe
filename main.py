import discord
import requests
import re
import os
from discord.ext import commands

# Retrieve configurations from Render Environment Variables safely
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Read targeted channel IDs from environment variable (comma-separated string, e.g., "12345,67890")
TARGET_CHANNELS = [int(cid.strip()) for cid in os.getenv("CHANNEL_IDS", "").split(",") if cid.strip()]

if not TOKEN:
    print("❌ ERROR: DISCORD_BOT_TOKEN environment variable is missing!")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

def clean_biome_name(raw_text):
    """
    Cleans up titles from various macros (SolsScope, DroidScope, Slaoq's, etc.)
    Example: 'Biome Started - SNOWY' -> 'Snowy'
    Example: 'Biome Started: WINDY' -> 'Windy'
    """
    if not raw_text:
        return "Normal"
        
    text = raw_text.upper()
    
    # Ignore 'Biome Ended' logs entirely so they don't overwrite active biomes awkwardly
    if "ENDED" in text or "LEFT" in text:
        return None

    # Remove known common macro filler text phrases
    text = text.replace("BIOME STARTED", "")
    text = text.replace("HAS STARTED!", "")
    text = text.replace("PRIVATE SERVER", "")
    
    # Strip out leftover symbols like colons, dashes, and extra whitespace
    text = re.sub(r'[:\-\[\]\(\)]', '', text)
    text = text.strip()
    
    return text.capitalize() if text else "Normal"

@bot.event
async def on_ready():
    print(f"🟢 Fabled's Lair Multi-Macro Bot is online as {bot.user}")
    print(f"📢 Monitoring Channels: {TARGET_CHANNELS}")

@bot.event
async def on_message(message):
    # Process if message is from a webhook inside our specified tracking channels
    if message.channel.id in TARGET_CHANNELS and message.webhook_id:
        biome = "Normal"
        roblox_link = None
        raw_title = ""
        
        # 1. Look inside Embeds (Where almost all Sol's RNG macros output data)
        if message.embeds:
            for embed in message.embeds:
                embed_dict = embed.to_dict()
                
                if embed.title:
                    raw_title = embed.title
                elif embed.description and not raw_title:
                    raw_title = embed.description
                
                links = re.findall(r'(https://www\.roblox\.com/share\?code=[^\s"\'>]+)', str(embed_dict))
                if links:
                    roblox_link = links[0].split(')')[0].split(']')[0]

        # 2. Fallback to plaintext message scanning
        if not roblox_link:
            links = re.findall(r'(https://www\.roblox\.com/share\?code=[^\s"\'>]+)', message.content)
            if links:
                roblox_link = links[0]
            if message.content and not raw_title:
                raw_title = message.content

        # 3. Clean up the extracted biome name
        biome = clean_biome_name(raw_title)
        
        if biome is None:
            print("🛑 Biome ended log skipped.")
            return

        # 4. Process and push to database
        if roblox_link:
            print(f"🎯 Snipe detected! Parsed Biome: {biome}")
            
            if not SUPABASE_URL or not SUPABASE_KEY:
                print(f"⚠️ Supabase environment variables not set yet. Link captured: {roblox_link}")
                return

            headers = {
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "resolution=merge-duplicates"
            }
            
            payload = {
                "server_link": roblox_link,
                "biome_name": biome
            }
            
            try:
                response = requests.post(SUPABASE_URL, json=payload, headers=headers)
                print(f"📊 Database sync status code: {response.status_code}")
            except Exception as e:
                print(f"❌ Failed to sync data to Supabase: {e}")

    await bot.process_commands(message)

if TOKEN:
    bot.run(TOKEN)
