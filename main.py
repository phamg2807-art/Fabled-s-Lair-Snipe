import discord
from discord.ext import commands
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import logging
import re
import os

# 1. Setup real-time unbuffered logging format
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S %p'
)

# 2. Configure Gateway Intents
intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.message_content = True 

bot = commands.Bot(command_prefix="!", intents=intents)

# 3. Lightweight Web Server to satisfy Render's Port Binding & Health Checks
class RenderHealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Fabled Helper: System Online and Listening.")
        
    def log_message(self, format, *args):
        # Keeps your Render log clean by not printing every single health check ping
        pass

def keep_alive():
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), RenderHealthCheckHandler)
    logging.info(f"WEB SERVER: Health check listener bound to port {port}")
    server.serve_forever()

@bot.event
async def on_ready():
    logging.info("SYSTEM ONLINE: logged into Discord Gateway successfully.")
    logging.info("--- START OF VISIBLE CHANNELS CHECKLIST ---")
    
    for guild in bot.guilds:
        logging.info(f"Server: {guild.name}")
        for channel in guild.text_channels:
            c_name_lower = channel.name.lower()
            
            if "forward" in c_name_lower or "found" in c_name_lower:
                tag = "[ . ] Text Context"
            elif "webhook" in c_name_lower:
                tag = "[🔥 TARGET MATCH]"
            else:
                tag = "[ . ] Text Context"
            
            # Guarantees no int object ljust attribute crashes
            logging.info(f"  {tag} ID: {str(channel.id).ljust(19)} | #{channel.name}")
            
    logging.info("--- END OF VISIBLE CHANNELS CHECKLIST ---")
    logging.info("Your service is live and tracking 🚀")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    channel_name = message.channel.name.lower()
    
    # FILTER: Instantly ignore any forward or found channel rooms
    if "forward" in channel_name or "found" in channel_name:
        return

    # Target webhook designated monitoring logs
    if "webhook" not in channel_name:
        return

    if not message.embeds:
        return

    for embed in message.embeds:
        # Aggressive Text Aggregation: Collect text from ALL areas of the embed 
        # to ensure timestamps in titles don't bypass keyword captures.
        text_elements = []
        if embed.title: text_elements.append(embed.title)
        if embed.description: text_elements.append(embed.description)
        if embed.author and embed.author.name: text_elements.append(embed.author.name)
        
        for field in embed.fields:
            if field.name: text_elements.append(field.name)
            if field.value: text_elements.append(field.value)
            
        combined_text = " ".join(text_elements)

        # Catch keywords anywhere within the aggregated pool
        is_start = bool(re.search(r"\b(started|start)\b", combined_text, re.IGNORECASE))
        is_end = bool(re.search(r"\b(ended|end)\b", combined_text, re.IGNORECASE))

        if not is_start and not is_end:
            logging.info(f"[DEBUG] Message from '{message.author}' in #{message.channel.name} dropped: No valid active event keywords found.")
            continue

        # Smart Biome Parsing Strategy
        # First priority: Look for standard structured patterns
        biome_match = re.search(r"(?:Biome\s+(?:Started|Ended)(?:\s*:\s*|\s*-\s*))([A-Z_]+)", combined_text, re.IGNORECASE)
        if biome_match:
            biome_name = biome_match.group(1).upper()
        else:
            # Second priority: Match against popular explicit game biome titles 
            known_biomes = ["WINDY", "SNOWY", "NORMAL", "CORRUPTION", "RAINY", "STARFALL", "GLITCHED", "DREAMSPACE", "CYBERSPACE"]
            found_known = [b for b in known_biomes if b.lower() in combined_text.lower()]
            if found_known:
                biome_name = found_known[0]
            else:
                # Fallback: Isolate capitalized words, excluding common layout structures
                words = re.findall(r"\b[A-Z]{4,}\b", combined_text)
                filtered_words = [w for w in words if w not in ["START", "STARTED", "ENDED", "BIOME", "TIME", "INVITE", "SERVER", "PRIVATE", "LINK"]]
                biome_name = filtered_words[0] if filtered_words else "UNKNOWN BIOME"

        event_type = "STARTED" if is_start else "ENDED"
        roblox_link = "None"

        # Link Extraction: Only parsed during start up events
        if is_start:
            link_match = re.search(r"https://www\.roblox\.com/share\?\S+", combined_text)
            if link_match:
                roblox_link = link_match.group(0)
            else:
                logging.warning(f"⚠ Event detected, but no valid Roblox invite share link was located in the structural fields.")

        # Clean, console extraction display format
        print("—" * 60)
        print(f"🔮 EXTRACTION LOG - BIOME {event_type}")
        print("—" * 60)
        print(f"🏰 Server Name  : {message.guild.name if message.guild else 'Private Guild'}")
        print(f"💬 Channel      : #{message.channel.name} (ID: {message.channel.id})")
        print(f"👤 Author       : {message.author}")
        print(f"🧩 Parsed Item  : {biome_name} ({event_type})")
        print(f"🔗 Link Found   : {roblox_link}")
        print("—" * 60)

# Fire up the HTTP keep-alive daemon thread before triggering the Discord loop
threading.Thread(target=keep_alive, daemon=True).start()

TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)
else:
    print("CRITICAL ERROR: Missing 'DISCORD_TOKEN' variable inside your Render Environment Settings!")
