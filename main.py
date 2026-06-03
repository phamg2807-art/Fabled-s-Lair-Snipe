import discord
from discord.ext import commands
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import logging
import re
import os
from datetime import datetime, timezone

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

# 3. Global Metric Trackers
biome_counts = {}
webhook_activity = {}  # Format: { channel_id: { "name": str, "last_seen": datetime } }

def get_metrics():
    now = datetime.now(timezone.utc)
    total_webhooks = len(webhook_activity)
    active_webhooks = 0
    active_list = []
    
    for cid, data in webhook_activity.items():
        delta = (now - data["last_seen"]).total_seconds() / 60.0
        if delta <= 10.0:
            active_webhooks += 1
            active_list.append(data["name"])
            
    return {
        "total_webhooks": total_webhooks,
        "active_webhooks": active_webhooks,
        "active_list": active_list,
        "biome_counts": biome_counts
    }

# 4. Lightweight Web Server to satisfy Render's Port Binding & Serve live Stats
class RenderHealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        
        metrics = get_metrics()
        
        # Build a neat dashboard UI directly visible via your Render Web URL
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>SjpWorkspace - Metrics Panel</title>
            <style>
                body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #0d0e12; color: #e1e1e6; padding: 30px; margin: 0; }}
                .container {{ max-width: 900px; margin: 0 auto; }}
                h1 {{ color: #10b981; border-bottom: 2px solid #1f2937; padding-bottom: 12px; margin-bottom: 25px; }}
                h2 {{ color: #60a5fa; margin-top: 35px; margin-bottom: 15px; }}
                .card {{ background: #1e1f29; padding: 20px; border-radius: 8px; margin-bottom: 20px; border: 1px solid #2e303f; }}
                .stat-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 20px; }}
                .stat-card {{ background: #161720; padding: 15px; border-radius: 6px; border-left: 4px solid #10b981; }}
                .stat-val {{ font-size: 28px; font-weight: bold; color: #f59e0b; margin-top: 5px; }}
                .biome-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 12px; }}
                .biome-item {{ background: #262738; padding: 12px; border-radius: 6px; text-align: center; border: 1px solid #3b3d54; }}
                .biome-name {{ font-weight: bold; color: #a78bfa; font-size: 14px; }}
                .biome-num {{ font-size: 20px; color: #fff; font-weight: bold; margin-top: 4px; }}
                ul {{ list-style-type: none; padding: 0; margin: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 8px; }}
                li {{ background: #161720; padding: 10px 14px; border-radius: 4px; font-size: 13px; border-left: 3px solid #10b981; font-family: monospace; }}
                .empty {{ color: #6b7280; font-style: italic; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>⚡ SjpWorkspace - Live Metrics Monitor</h1>
                <p>System Status: <strong>ONLINE</strong> | Watching Discord Gateway Streams</p>
                
                <div class="stat-grid">
                    <div class="stat-card" style="border-left-color: #3b82f6;">
                        <div style="color: #9ca3af; font-size: 14px;">Total Connected Webhooks</div>
                        <div class="stat-val">{metrics['total_webhooks']}</div>
                    </div>
                    <div class="stat-card">
                        <div style="color: #9ca3af; font-size: 14px;">Active Webhooks (Last 10m)</div>
                        <div class="stat-val" style="color: #10b981;">{metrics['active_webhooks']}</div>
                    </div>
                </div>
                
                <h2>📊 Biome Sniper Counters</h2>
                <div class="card">
        """
        if not metrics['biome_counts']:
            html += '<p class="empty">No biomes tracked yet during this active runtime session.</p>'
        else:
            html += '<div class="biome-grid">'
            for b_name, count in sorted(metrics['biome_counts'].items()):
                html += f"""
                <div class="biome-item">
                    <div class="biome-name">{b_name}</div>
                    <div class="biome-num">{count}</div>
                </div>
                """
            html += '</div>'
            
        html += """
                </div>
                
                <h2>🟢 Active Webhooks Streams (Last 10 mins)</h2>
                <div class="card">
        """
        if not metrics['active_list']:
            html += '<p class="empty">No active webhook updates processed in the last 10 minutes.</p>'
        else:
            html += '<ul>'
            for w_name in sorted(metrics['active_list']):
                html += f"<li>#{w_name}</li>"
            html += '</ul>'
            
        html += """
                </div>
            </div>
        </body>
        </html>
        """
        self.wfile.write(html.encode('utf-8'))
        
    def log_message(self, format, *args):
        # Mute background logging to prevent terminal congestion
        pass

def keep_alive():
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), RenderHealthCheckHandler)
    logging.info(f"WEB SERVER: Health check metric listener bound to port {port}")
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

    # [NEW FEATURE] Track every single incoming webhook packet to count unique streams and assess activity window
    webhook_activity[message.channel.id] = {
        "name": message.channel.name,
        "last_seen": datetime.now(timezone.utc)
    }

    if not message.embeds:
        return

    for embed in message.embeds:
        text_elements = []
        if embed.title: text_elements.append(embed.title)
        if embed.description: text_elements.append(embed.description)
        if embed.author and embed.author.name: text_elements.append(embed.author.name)
        
        for field in embed.fields:
            if field.name: text_elements.append(field.name)
            if field.value: text_elements.append(field.value)
            
        combined_text = " ".join(text_elements)

        is_start = bool(re.search(r"\b(started|start)\b", combined_text, re.IGNORECASE))
        is_end = bool(re.search(r"\b(ended|end)\b", combined_text, re.IGNORECASE))

        if not is_start and not is_end:
            logging.info(f"[DEBUG] Message from '{message.author}' in #{message.channel.name} dropped: No valid active event keywords found.")
            continue

        # Smart Biome Parsing Strategy
        biome_match = re.search(r"(?:Biome\s+(?:Started|Ended)(?:\s*:\s*|\s*-\s*))([A-Z_]+)", combined_text, re.IGNORECASE)
        if biome_match:
            biome_name = biome_match.group(1).upper()
        else:
            # [FIXED LOGIC] Added SINGULARITY and re-ordered list to prioritize rare sub-biomes over overlapping parent weathers
            known_biomes = ["SINGULARITY", "GLITCHED", "DREAMSPACE", "CYBERSPACE", "STARFALL", "CORRUPTION", "WINDY", "SNOWY", "RAINY", "HELL", "NORMAL"]
            found_known = [b for b in known_biomes if b.lower() in combined_text.lower()]
            if found_known:
                if "SINGULARITY" in found_known:
                    biome_name = "SINGULARITY"
                else:
                    biome_name = found_known[0]
            else:
                words = re.findall(r"\b[A-Z]{4,}\b", combined_text)
                filtered_words = [w for w in words if w not in ["START", "STARTED", "ENDED", "BIOME", "TIME", "INVITE", "SERVER", "PRIVATE", "LINK"]]
                biome_name = filtered_words[0] if filtered_words else "UNKNOWN BIOME"

        # [NEW FEATURE] Increment counter for the identified biome
        biome_counts[biome_name] = biome_counts.get(biome_name, 0) + 1

        event_type = "STARTED" if is_start else "ENDED"
        roblox_link = "None"

        if is_start:
            link_match = re.search(r"https://www\.roblox\.com/share\?\S+", combined_text)
            if link_match:
                roblox_link = link_match.group(0)
            else:
                logging.warning(f"⚠ Event detected, but no valid Roblox invite share link was located in the structural fields.")

        # Gather metrics for real-time console overview
        metrics = get_metrics()

        print("—" * 60)
        print(f"🔮 EXTRACTION LOG - BIOME {event_type}")
        print("—" * 60)
        print(f"🏰 Server Name  : {message.guild.name if message.guild else 'Private Guild'}")
        print(f"💬 Channel      : #{message.channel.name} (ID: {message.channel.id})")
        print(f"👤 Author       : {message.author}")
        print(f"🧩 Parsed Item  : {biome_name} ({event_type})")
        print(f"🔗 Link Found   : {roblox_link}")
        print(f"📈 Total {biome_name}s: {biome_counts[biome_name]}")
        print(f"📡 Webhooks Active: {metrics['active_webhooks']}/{metrics['total_webhooks']}")
        print("—" * 60)

# Fire up the HTTP keep-alive daemon thread before triggering the Discord loop
threading.Thread(target=keep_alive, daemon=True).start()

TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)
else:
    print("CRITICAL ERROR: Missing 'DISCORD_TOKEN' variable inside your Render Environment Settings!")
