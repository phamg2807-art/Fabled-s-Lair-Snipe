import discord
from discord.ext import commands
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import logging
import re
import os
import json
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

# 3. Advanced Global Metric Trackers
biome_counts = {}
merchant_counts = {}
webhook_activity = {}  # channel_id -> { "name": str, "last_seen": ISO string, "total_messages": int }
active_live_events = {} # channel_id -> { "type": str, "name": str, "started_at": ISO string, "server": str }

def get_metrics_payload():
    """Generates a deep, accurate state object perfectly optimized for JSON API responses."""
    now = datetime.now(timezone.utc)
    total_webhooks = len(webhook_activity)
    active_webhooks_count = 0
    active_streams_list = []
    
    # Calculate Grand Totals dynamically from active history maps
    grand_total_biomes = sum(biome_counts.values())
    grand_total_merchants = sum(merchant_counts.values())
    
    # Process dynamic sliding window activity
    for cid, data in webhook_activity.items():
        last_seen_dt = datetime.fromisoformat(data["last_seen"])
        delta_mins = (now - last_seen_dt).total_seconds() / 60.0
        if delta_mins <= 10.0:
            active_webhooks_count += 1
            active_streams_list.append({
                "channel_id": cid,
                "name": data["name"],
                "last_seen_ago_mins": round(delta_mins, 2)
            })
            
    return {
        "status": "ONLINE",
        "timestamp": now.isoformat(),
        "telemetry": {
            "total_registered_webhooks": total_webhooks,
            "active_webhooks_last_10m": active_webhooks_count,
            "grand_total_biomes": grand_total_biomes,
            "grand_total_merchants": grand_total_merchants
        },
        "counters": {
            "biomes": biome_counts,
            "merchants": merchant_counts
        },
        "live_events": list(active_live_events.values()),
        "active_webhook_streams": active_streams_list,
        "raw_webhook_registry": webhook_activity
    }

# 4. Hybrid Web Server (Serves HTML Dashboard to Humans & Clean JSON to your Website Frontend)
class RenderHealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        # ROUTE 1: JSON Data API Endpoint for Zite/Lovable Web Components
        if self.path == '/api/metrics':
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*') # Permits your frontend to read data without CORS blocks
            self.end_headers()
            payload = get_metrics_payload()
            self.wfile.write(json.dumps(payload, ensure_ascii=False, indent=2).encode('utf-8'))
            return
            
        # ROUTE 2: Default Visual HTML Monitoring Dashboard
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        
        data = get_metrics_payload()
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>SjpWorkspace - Advanced Metrics Hub</title>
            <style>
                body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #0b0c10; color: #c5c6c7; padding: 30px; margin: 0; }}
                .container {{ max-width: 1100px; margin: 0 auto; }}
                h1 {{ color: #66fcf1; border-bottom: 2px solid #1f2833; padding-bottom: 12px; margin-bottom: 25px; font-size: 28px; }}
                h2 {{ color: #45f3ff; margin-top: 35px; margin-bottom: 15px; font-size: 20px; text-transform: uppercase; letter-spacing: 1px; }}
                .card {{ background: #1f2833; padding: 20px; border-radius: 8px; margin-bottom: 25px; border: 1px solid #2f3e46; }}
                .stat-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 20px; }}
                .stat-card {{ background: #151a21; padding: 20px; border-radius: 6px; border-left: 4px solid #66fcf1; }}
                .stat-val {{ font-size: 32px; font-weight: bold; color: #fff; margin-top: 5px; }}
                .grid-display {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 15px; }}
                .item-box {{ background: #151a21; padding: 15px; border-radius: 6px; text-align: center; border: 1px solid #45f3ff; }}
                .item-title {{ font-weight: bold; color: #c5c6c7; font-size: 13px; text-transform: uppercase; }}
                .item-count {{ font-size: 24px; color: #66fcf1; font-weight: bold; margin-top: 6px; }}
                .live-box {{ background: #1c2541; border: 1px solid #5bc0be; padding: 15px; border-radius: 6px; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center; }}
                .badge {{ background: #ff2a6d; color: white; padding: 4px 8px; border-radius: 4px; font-size: 11px; font-weight: bold; text-transform: uppercase; animation: pulse 2s infinite; }}
                ul {{ list-style-type: none; padding: 0; margin: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 10px; }}
                li {{ background: #151a21; padding: 12px; border-radius: 4px; font-size: 13px; border-left: 3px solid #66fcf1; display: flex; justify-content: space-between; }}
                .empty {{ color: #4f5d75; font-style: italic; }}
                @keyframes pulse {{ 0% {{ opacity: 0.6; }} 50% {{ opacity: 1; }} 100% {{ opacity: 0.6; }} }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>⚡ SjpWorkspace - Deep Telemetry Central</h1>
                <p>System Status: <span style="color:#66fcf1; font-weight:bold;">ONLINE</span> | API Channel Available: <code>/api/metrics</code></p>
                
                <div class="stat-grid">
                    <div class="stat-card" style="border-left-color: #a78bfa;">
                        <div style="color: #95a5a6; font-size: 14px;">✨ Grand Total Biomes</div>
                        <div class="stat-val" style="color: #a78bfa;">{data['telemetry']['grand_total_biomes']}</div>
                    </div>
                    <div class="stat-card" style="border-left-color: #f59e0b;">
                        <div style="color: #95a5a6; font-size: 14px;">🛒 Grand Total Merchants</div>
                        <div class="stat-val" style="color: #f59e0b;">{data['telemetry']['grand_total_merchants']}</div>
                    </div>
                    <div class="stat-card" style="border-left-color: #45f3ff;">
                        <div style="color: #95a5a6; font-size: 14px;">Total Channels</div>
                        <div class="stat-val">{data['telemetry']['total_registered_webhooks']}</div>
                    </div>
                    <div class="stat-card" style="border-left-color: #ff2a6d;">
                        <div style="color: #95a5a6; font-size: 14px;">Active Webhooks (10m)</div>
                        <div class="stat-val">{data['telemetry']['active_webhooks_last_10m']}</div>
                    </div>
                </div>
                
                <h2>🔴 Real-Time Live Map (Active Right Now)</h2>
                <div class="card">
        """
        if not data['live_events']:
            html += '<p class="empty">No active biomes or merchants are currently live inside tracked servers.</p>'
        else:
            for ev in data['live_events']:
                html += f"""
                <div class="live-box">
                    <div>
                        <strong style="color:#fff; font-size:16px;">{ev['name']}</strong> 
                        <span style="color:#95a5a6; margin-left:10px;">({ev['type'].upper()})</span>
                        <br><small style="color:#45f3ff;">Server Instance: {ev['server']} | Tracked in #{ev['channel_name']}</small>
                    </div>
                    <span class="badge">Live Since {ev['started_at'][11:19]} UTC</span>
                </div>
                """
                
        html += """
                </div>
                
                <h2>📊 Historical Biome Discoveries</h2>
                <div class="card">
        """
        if not data['counters']['biomes']:
            html += '<p class="empty">No biomes tracked yet during this runtime engine cycle.</p>'
        else:
            html += '<div class="grid-display">'
            for b_name, count in sorted(data['counters']['biomes'].items()):
                html += f"""
                <div class="item-box">
                    <div class="item-title">{b_name}</div>
                    <div class="item-count">{count}</div>
                </div>
                """
            html += '</div>'
            
        html += """
                </div>

                <h2>🛒 Historical Merchant Arrivals</h2>
                <div class="card">
        """
        if not data['counters']['merchants']:
            html += '<p class="empty">No merchant appearances logged yet in this deployment.</p>'
        else:
            html += '<div class="grid-display">'
            for m_name, count in sorted(data['counters']['merchants'].items()):
                html += f"""
                <div class="item-box" style="border-color: #ff2a6d;">
                    <div class="item-title" style="color:#ff2a6d;">{m_name}</div>
                    <div class="item-count" style="color:#fff;">{count}</div>
                </div>
                """
            html += '</div>'
            
        html += """
                </div>
                
                <h2>📡 Webhook Pipeline Feed Traffic</h2>
                <div class="card">
        """
        if not data['active_webhook_streams']:
            html += '<p class="empty">No active data flow across channels in the last 10 minutes.</p>'
        else:
            html += '<ul>'
            for w in sorted(data['active_webhook_streams'], key=lambda x: x['name']):
                reg_info = data['raw_webhook_registry'][str(w['channel_id'])]
                html += f"""
                <li>
                    <span>#{w['name']}</span>
                    <span style="color:#66fcf1;">{reg_info['total_messages']} frames logged ({w['last_seen_ago_mins']}m ago)</span>
                </li>
                """
            html += '</ul>'
            
        html += """
                </div>
            </div>
        </body>
        </html>
        """
        self.wfile.write(html.encode('utf-8'))
        
    def log_message(self, format, *args):
        pass # Inhibits continuous logging pollution inside your standard console stream

def keep_alive():
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), RenderHealthCheckHandler)
    logging.info(f"WEB SERVER: API and Dashboard engine active on port {port}")
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

    cid_str = str(message.channel.id)
    now_iso = datetime.now(timezone.utc).isoformat()

    # Process and preserve historical entry tracking metrics per channel pipeline
    if cid_str not in webhook_activity:
        webhook_activity[cid_str] = {
            "name": message.channel.name,
            "last_seen": now_iso,
            "total_messages": 1
        }
    else:
        webhook_activity[cid_str]["last_seen"] = now_iso
        webhook_activity[cid_str]["total_messages"] += 1

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

        # Advanced keyword mapping to encompass varying macro frameworks smoothly
        is_start = bool(re.search(r"\b(started|start|spawned|arrived|appeared)\b", combined_text, re.IGNORECASE))
        is_end = bool(re.search(r"\b(ended|end|despawned|left|gone)\b", combined_text, re.IGNORECASE))

        if not is_start and not is_end:
            logging.info(f"[DEBUG] Message from '{message.author}' in #{message.channel.name} dropped: No valid active event keywords found.")
            continue

        roblox_link = "None"
        if is_start:
            link_match = re.search(r"https://www\.roblox\.com/share\?\S+", combined_text)
            if link_match:
                roblox_link = link_match.group(0)

        guild_name = message.guild.name if message.guild else "Private Guild"

        # GATING INTERCEPT ROUTE: Is it a Merchant instance or Biome weather shift?
        if "merchant" in combined_text.lower():
            if "mysterious" in combined_text.lower():
                merchant_name = "MYSTERIOUS MERCHANT"
            elif "traveling" in combined_text.lower():
                merchant_name = "TRAVELING MERCHANT"
            else:
                merchant_name = "MERCHANT"

            event_type = "SPAWNED" if is_start else "DESPAWNED"
            
            if is_start:
                merchant_counts[merchant_name] = merchant_counts.get(merchant_name, 0) + 1
                active_live_events[cid_str] = {
                    "type": "merchant",
                    "name": merchant_name,
                    "started_at": now_iso,
                    "server": guild_name,
                    "channel_name": message.channel.name,
                    "link": roblox_link
                }
            else:
                active_live_events.pop(cid_str, None)

            metrics = get_metrics_payload()

            print("—" * 60)
            print(f"🛒 EXTRACTION LOG - MERCHANT {event_type}")
            print("—" * 60)
            print(f"🏰 Server Name  : {guild_name}")
            print(f"💬 Channel      : #{message.channel.name} (ID: {message.channel.id})")
            print(f"👤 Author       : {message.author}")
            print(f"🧩 Parsed Item  : {merchant_name} ({event_type})")
            print(f"🔗 Link Found   : {roblox_link}")
            print(f"📈 Total {merchant_name}s: {merchant_counts.get(merchant_name, 0)}")
            print(f"📡 Webhooks Active: {metrics['telemetry']['active_webhooks_last_10m']}/{metrics['telemetry']['total_registered_webhooks']}")
            print("—" * 60)

        else:
            # Smart Biome Extraction Engine
            biome_match = re.search(r"(?:Biome\s+(?:Started|Ended)(?:\s*:\s*|\s*-\s*))([A-Z_]+)", combined_text, re.IGNORECASE)
            if biome_match:
                biome_name = biome_match.group(1).upper()
            else:
                # Isolate sub-biomes safely when multiple priority tags overlap (e.g. Singularity inside Starfall)
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

            event_type = "STARTED" if is_start else "ENDED"
            
            if is_start:
                biome_counts[biome_name] = biome_counts.get(biome_name, 0) + 1
                active_live_events[cid_str] = {
                    "type": "biome",
                    "name": biome_name,
                    "started_at": now_iso,
                    "server": guild_name,
                    "channel_name": message.channel.name,
                    "link": roblox_link
                }
            else:
                active_live_events.pop(cid_str, None)

            metrics = get_metrics_payload()

            print("—" * 60)
            print(f"🔮 EXTRACTION LOG - BIOME {event_type}")
            print("—" * 60)
            print(f"🏰 Server Name  : {guild_name}")
            print(f"💬 Channel      : #{message.channel.name} (ID: {message.channel.id})")
            print(f"👤 Author       : {message.author}")
            print(f"🧩 Parsed Item  : {biome_name} ({event_type})")
            print(f"🔗 Link Found   : {roblox_link}")
            print(f"📈 Total {biome_name}s: {biome_counts.get(biome_name, 0)}")
            print(f"📡 Webhooks Active: {metrics['telemetry']['active_webhooks_last_10m']}/{metrics['telemetry']['total_registered_webhooks']}")
            print("—" * 60)

# Fire up the HTTP keep-alive daemon thread before triggering the Discord loop
threading.Thread(target=keep_alive, daemon=True).start()

TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)
else:
    print("CRITICAL ERROR: Missing 'DISCORD_TOKEN' variable inside your Render Environment Settings!")
