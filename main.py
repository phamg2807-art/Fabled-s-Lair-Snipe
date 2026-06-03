import discord
from discord.ext import commands
import logging
import re
import os

# 1. Setup instant, real-time unbuffered logging format
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S %p'
)

# 2. Configure Gateway Intents (Requires Message Content enabled in Developer Portal)
intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.message_content = True 

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    logging.info("SYSTEM ONLINE: Fabled's Helper logged into Discord Gateway successfully.")
    logging.info("--- START OF VISIBLE CHANNELS CHECKLIST ---")
    
    for guild in bot.guilds:
        logging.info(f"Server: {guild.name}")
        for channel in guild.text_channels:
            c_name_lower = channel.name.lower()
            
            # Exclude forward/found channels from target matching per instruction
            if "forward" in c_name_lower or "found" in c_name_lower:
                tag = "[ . ] Text Context"
            elif "webhook" in c_name_lower:
                tag = "[🔥 TARGET MATCH]"
            else:
                tag = "[ . ] Text Context"
            
            # FIXED: Converted channel.id to string to fix the 'int' object has no attribute 'ljust' bug
            logging.info(f"  {tag} ID: {str(channel.id).ljust(19)} | #{channel.name}")
            
    logging.info("--- END OF VISIBLE CHANNELS CHECKLIST ---")
    logging.info("Your service is live 🚀")

@bot.event
async def on_message(message):
    # Prevent the bot from processing its own messages
    if message.author == bot.user:
        return

    channel_name = message.channel.name.lower()
    
    # FILTER: Instantly ignore any message originating from Forward or Found channels
    if "forward" in channel_name or "found" in channel_name:
        logging.info(f"[FILTERED] Msg from '{message.author}' in #{message.channel.name} dropped (Forward/Found channels ignored).")
        return

    # Only parse channels containing 'webhook'
    if "webhook" not in channel_name:
        return

    # Check for embed structures
    if not message.embeds:
        return

    logging.info(f"[DEBUG] Bot captured an event from '{message.author}' in Channel: #{message.channel.name} (ID: {message.channel.id})")
    logging.info(f"[DEBUG] Message contains {len(message.embeds)} embed structure(s). Parsing content fields...")

    for embed in message.embeds:
        title = embed.title if embed.title else ""
        description = embed.description if embed.description else ""
        
        # Combine visible text fields to ensure accurate keyword capturing
        combined_text = f"{title} {description}"
        logging.info(f"  ♦ Title parsed: {title}")

        # Check for event keywords
        is_start = bool(re.search(r"started", combined_text, re.IGNORECASE))
        is_end = bool(re.search(r"ended", combined_text, re.IGNORECASE))

        if not is_start and not is_end:
            logging.info(f"[DEBUG] Message dropped inside monitored channel; neither 'Biome Started' nor 'Biome Ended' keywords found.")
            continue

        # Extract Biome Name (Handles both "Biome Started: NAME" and "Biome Started - NAME")
        biome_match = re.search(r"(?:Biome\s+(?:Started|Ended)(?:\s*:\s*|\s*-\s*))([A-Z_]+)", combined_text, re.IGNORECASE)
        if biome_match:
            biome_name = biome_match.group(1).upper()
        else:
            # Fallback regex to pick up capitalized keywords if the structure shifts
            words = re.findall(r"\b[A-Z]{4,}\b", combined_text)
            biome_name = words[0] if words else "UNKNOWN BIOME"

        event_type = "STARTED" if is_start else "ENDED"
        roblox_link = "None"

        # SMART LINK LOGIC: Extract the Roblox server link strictly on Biome Start events
        if is_start:
            # Aggregate all possible fields inside embed to scan for the invite URL
            search_pool = combined_text
            for field in embed.fields:
                search_pool += f" {field.name} {field.value}"
            
            link_match = re.search(r"https://www\.roblox\.com/share\?\S+", search_pool)
            if link_match:
                roblox_link = link_match.group(0)
            else:
                logging.warning(f"⚠ Biome matched, but no Roblox share link was found in the text data.")

        # Clean, streamlined console extraction logging format
        print("—" * 60)
        print(f"🔮 EXTRACTION LOG - BIOME {event_type}")
        print("—" * 60)
        print(f"🏰 Server Name  : {message.guild.name if message.guild else 'Private Guild'}")
        print(f"💬 Channel      : #{message.channel.name} (ID: {message.channel.id})")
        print(f"👤 Author       : {message.author}")
        print(f"🧩 Parsed Item  : {biome_name} ({event_type})")
        print(f"🔗 Link Found   : {roblox_link}")
        print("—" * 60)

# Pulls your Discord token securely from Render's Environment Variables
TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)
else:
    print("ERROR: Missing 'DISCORD_TOKEN' variable inside your Render Environment Settings!")
