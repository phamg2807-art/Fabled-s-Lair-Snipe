import discord
from discord.ext import commands
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import logging
import re
import os
import json
import asyncio
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

# Path to preserve counting data locally (Secondary fallback layer)
DATA_STORE_PATH = "metrics_store.json"

# 3. Advanced Global Metric Trackers
biome_counts = {}
merchant_counts = {}
webhook_activity = {}  # channel_id -> { "name": str, "last_seen": ISO string, "total_messages": int, "accounts": dict }
active_live_events = {} # event_key -> { "type": str, "name": str, "started_at": ISO string, "server": str, ... }

def load_persisted_metrics():
    """Loads previous version counting data safely from the local file system (fallback)."""
    global biome_counts, merchant_counts, webhook_activity
    if os.path.exists(DATA_STORE_PATH):
        try:
            with open(DATA_STORE_PATH, 'r', encoding='utf-8') as f:
                stored_data = json.load(f)
                biome_counts = stored_data.get("biomes", {})
                merchant_counts = stored_data.get("merchants", {})
                webhook_activity = stored_data.get("webhook_activity", {})
                logging.info(f"💾 LOCAL ENGINE: Restored metrics fallback cache from {DATA_STORE_PATH}")
        except Exception as e:
            logging.error(f"⚠️ LOCAL ENGINE: Error reading local cache state: {e}")

def save_persisted_metrics():
    """Saves current state counters to local file system payload."""
    try:
        payload = {
            "biomes": biome_counts,
            "merchants": merchant_counts,
            "webhook_activity": webhook_activity
        }
        with open(DATA_STORE_PATH, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logging.error(f"⚠️ LOCAL ENGINE: Failed writing tracking data to disk: {e}")

async def backup_state_to_discord_cloud():
    """Bulletproof Cloud Engine: Saves the system state payload straight into a private Discord channel."""
    state_channel_id = os.getenv("STATE_CHANNEL_ID")
    channel = None
    
    if state_channel_id:
        channel = bot.get_channel(int(state_channel_id))
    if not channel:
        for guild in bot.guilds:
            channel = discord.utils.get(guild.text_channels, name="sjp-state-db")
            if channel:
                break
                
    if channel:
        try:
            payload = {
                "biomes": biome_counts,
                "merchants": merchant_counts,
                "webhook_activity": webhook_activity,
                "active_live_events": active_live_events
            }
            temp_file = "cloud_backup.json"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            
            await channel.send(
                content=f"🔄 **SjpWorkspace Cloud Backup Instance** | Timestamp: `{datetime.now(timezone.utc).isoformat()}`",
                file=discord.File(temp_file)
            )
            logging.info("💾 CLOUD DATABASE: Successfully synced latest database state up to Discord storage channel.")
            try:
                os.remove(temp_file)
            except:
                pass
        except Exception as e:
            logging.error(f"⚠️ CLOUD DATABASE: Failed transmitting state synchronization: {e}")

async def load_state_from_discord_cloud():
    """Fetches the last JSON backup file posted inside the backup channel to recover historical states."""
    global biome_counts, merchant_counts, webhook_activity, active_live_events
    state_channel_id = os.getenv("STATE_CHANNEL_ID")
    channel = None
    
    if state_channel_id:
        channel = bot.get_channel(int(state_channel_id))
    if not channel:
        for guild in bot.guilds:
            channel = discord.utils.get(guild.text_channels, name="sjp-state-db")
            if channel:
                break
                
    if channel:
        try:
            logging.info("⚡ CLOUD DATABASE: Scanning sync channel histories for historical profiles...")
            async for message in channel.history(limit=25):
                if message.attachments:
                    for attachment in message.attachments:
                        if attachment.filename.endswith(".json"):
                            data_bytes = await attachment.read()
                            stored_data = json.loads(data_bytes.decode('utf-8'))
                            
                            biome_counts = stored_data.get("biomes", {})
                            merchant_counts = stored_data.get("merchants", {})
                            webhook_activity = stored_data.get("webhook_activity", {})
                            active_live_events = stored_data.get("active_live_events", {})
                            
                            logging.info("🎯 CLOUD DATABASE: Successfully restored all cross-version historical data from Discord Cloud Storage!")
                            return True
        except Exception as e:
            logging.error(f"⚠️ CLOUD DATABASE: Critical error while attempting recovery parse: {e}")
    return False

def get_metrics_payload():
    """Generates a deep, accurate state object perfectly optimized for JSON API responses."""
    now = datetime.now(timezone.utc)
    total_webhooks = len(webhook_activity)
    active_webhooks_count = 0
    active_streams_list = []
    
    grand_total_biomes = sum(biome_counts.values())
    grand_total_merchants = sum(merchant_counts.values())
    
    for cid, data in webhook_activity.items():
        last_seen_dt = datetime.fromisoformat(data["last_seen"])
        delta_mins = (now - last_seen_dt).total_seconds() / 60.0
        if delta_mins <= 10.0:
            active_webhooks_count += 1
            active_streams_list.append({
                "channel_id": cid,
                "name": data["name"],
                "last_seen_ago_mins": round(delta_mins, 2),
                "accounts_count": len(data.get("accounts", {}))
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
        if self.path == '/api/metrics':
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*') 
            self.end_headers()
            payload = get_metrics_payload()
            self.wfile.write(json.dumps(payload, ensure_ascii=False, indent=2).encode('utf-8'))
            return
            
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        
        data = get_metrics_payload()
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>SjpWorkspace - Multi-Account Telemetry Hub</title>
            <style>
                body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #0b0c10; color: #c5c6c7; padding: 30px; margin: 0; }}
                .container {{ max-width: 1200px; margin: 0 auto; }}
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
                
                .webhook-block {{ background: #151a21; border: 1px solid #2f3e46; border-radius: 6px; padding: 15px; margin-bottom: 15px; }}
                .webhook-header {{ font-size: 16px; font-weight: bold; color: #66fcf1; border-bottom: 1px dashed #2f3e46; padding-bottom: 6px; margin-bottom: 10px; display: flex; justify-content: space-between; }}
                .account-row {{ background: #1f2833; border-left: 3px solid #ff2a6d; padding: 10px; margin: 8px 0; border-radius: 4px; font-size: 13px; }}
                .session-tag {{ background: #2f3e46; padding: 2px 6px; border-radius: 3px; font-size: 11px; color: #45f3ff; margin-right: 5px; }}
                @keyframes pulse {{ 0% {{ opacity: 0.6; }} 50% {{ opacity: 1; }} 100% {{ opacity: 0.6; }} }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>⚡ SjpWorkspace - Multi-Account Telemetry Hub</h1>
                <p>System Status: <span style="color:#66fcf1; font-weight:bold;">ONLINE</span> | Cloud Sync: <span style="color:#2ecc71; font-weight:bold;">ACTIVE</span></p>
                
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
                
                <h2>🔴 Real-Time Active Sessions</h2>
                <div class="card">
        """
        if not data['live_events']:
            html += '<p class="empty">No active macro instances detected streaming right now.</p>'
        else:
            for ev in data['live_events']:
                html += f"""
                <div class="live-box">
                    <div>
                        <strong style="color:#fff; font-size:16px;">{ev['name']}</strong> 
                        <span style="color:#95a5a6; margin-left:10px;">({ev['type'].upper()})</span>
                        <br><small style="color:#45f3ff;">Channel: #{ev['channel_name']} | Assigned: <strong>{ev.get('account_identity', 'Unknown Account')}</strong></small>
                    </div>
                    <span class="badge">Live Since {ev['started_at'][11:19]} UTC</span>
                </div>
                """
                
        html += """
                </div>
                
                <h2>📡 Channel Macro Profiles & Biome Lengths</h2>
                <div class="card">
        """
        if not data['raw_webhook_registry']:
            html += '<p class="empty">No channel stream history recorded yet.</p>'
        else:
            for cid, reg in sorted(data['raw_webhook_registry'].items(), key=lambda x: x[1]['name']):
                html += f"""
                <div class="webhook-block">
                    <div class="webhook-header">
                        <span>#{reg['name']} <small style="color:#7f8c8d; font-weight:normal;">({reg['total_messages']} frames)</small></span>
                        <span style="color:#45f3ff; font-size:13px;">Accounts Detected: {len(reg.get('accounts', {}))}</span>
                    </div>
                """
                accounts = reg.get("accounts", {})
                if not accounts:
                    html += '<p style="color:#4f5d75; font-style:italic; margin:0; font-size:13px;">No accounts assigned yet via private server links.</p>'
                else:
                    for l_key, acc in accounts.items():
                        html += f"""
                        <div class="account-row">
                            <strong style="color:#fff;">{acc['display_name']}</strong> 
                            <span style="color:#95a5a6; font-size:11px; margin-left:10px;">Link Hash: {l_key[:30]}...</span>
                            <div style="margin-top:6px;">
                                <span style="color:#66fcf1; font-weight:bold;">Recent Finished Sessions & Session Lengths:</span><br>
                        """
                        history = acc.get("completed_sessions", [])
                        if not history:
                            html += '<span style="color:#7f8c8d; font-size:12px;">Waiting for first session termination event...</span>'
                        else:
                            for sess in reversed(history):
                                html += f"<span class='session-tag'>{sess['name']}: {sess['duration']}</span> "
                        html += """
                            </div>
                        </div>
                        """
                html += "</div>"
            
        html += """
                </div>
            </div>
        </body>
        </html>
        """
        self.wfile.write(html.encode('utf-8'))
        
    def log_message(self, format, *args):
        pass 

def keep_alive():
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), RenderHealthCheckHandler)
    logging.info(f"WEB SERVER: Dashboard engine active on port {port}")
    server.serve_forever()

@bot.event
async def on_ready():
    load_persisted_metrics()
    # Pull master state from cloud backup before activation sequence triggers
    await load_state_from_discord_cloud()
    
    logging.info("SYSTEM ONLINE: Logged into Discord Gateway successfully.")
    logging.info("Your service is live and tracking 🚀")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    channel_name = message.channel.name.lower()
    missing_channel_whitelist = {1511359721632694363, 1511365304624877568, 1511335720239759361, 1511362877322432792}

    is_monitored_channel = (
        message.channel.id in missing_channel_whitelist or
        "webhook" in channel_name or
        "forward" in channel_name or
        "found" in channel_name
    )

    if not is_monitored_channel:
        return

    cid_str = str(message.channel.id)
    now_iso = datetime.now(timezone.utc).isoformat()
    is_forwarder = "forward" in channel_name

    # Check for private server link string globally across both Start/End frames
    combined_embed_text = ""
    if message.embeds:
        for embed in message.embeds:
            els = [embed.title or "", embed.description or ""]
            for f in embed.fields:
                els.extend([f.name or "", f.value or ""])
            combined_embed_text += " " + " ".join(els)
            
    link_match = re.search(r"https://www\.roblox\.com/share\?\S+", combined_embed_text)
    roblox_link = link_match.group(0) if link_match else None

    # Track activity metrics exclusively for non-forwarder webhooks
    if not is_forwarder:
        if cid_str not in webhook_activity:
            webhook_activity[cid_str] = {
                "name": message.channel.name,
                "last_seen": now_iso,
                "total_messages": 1,
                "accounts": {}
            }
        else:
            webhook_activity[cid_str]["last_seen"] = now_iso
            webhook_activity[cid_str]["total_messages"] += 1
            if "accounts" not in webhook_activity[cid_str]:
                webhook_activity[cid_str]["accounts"] = {}

        # Distinct multi-account identifier core logic
        if roblox_link:
            acc_registry = webhook_activity[cid_str]["accounts"]
            if roblox_link not in acc_registry:
                assigned_index = len(acc_registry) + 1
                acc_registry[roblox_link] = {
                    "display_name": f"Account {assigned_index}",
                    "biomes": {},
                    "merchants": {},
                    "completed_sessions": []
                }
            account_identity = acc_registry[roblox_link]["display_name"]
        else:
            # Fallback if embed data drops link text unexpectedly
            account_identity = "Account 1" 
    else:
        account_identity = "Forwarder Source"

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
        combined_text_lower = combined_text.lower()

        is_start = bool(re.search(r"\b(started|start|spawned|arrived|appeared|has arrived|is here)\b", combined_text_lower))
        is_end = bool(re.search(r"\b(ended|end|despawned|left|gone|has left)\b", combined_text_lower))

        if not is_start and not is_end:
            continue

        guild_name = message.guild.name if message.guild else "Private Guild"

        is_merchant_event = (
            "merchant" in combined_text_lower or 
            "mari" in combined_text_lower or 
            "jester" in combined_text_lower or 
            "rin" in combined_text_lower
        )

        if is_merchant_event:
            if "mysterious" in combined_text_lower: merchant_name = "MYSTERIOUS MERCHANT"
            elif "traveling" in combined_text_lower: merchant_name = "TRAVELING MERCHANT"
            elif "mari" in combined_text_lower: merchant_name = "MARI (MERCHANT)"
            elif "jester" in combined_text_lower: merchant_name = "JESTER (MERCHANT)"
            elif "rin" in combined_text_lower: merchant_name = "RIN (MERCHANT)"
            else: merchant_name = "MERCHANT"

            event_type = "SPAWNED" if is_start else "DESPAWNED"
            event_key = f"{cid_str}_{account_identity}_{merchant_name}"
            duration_str = "N/A"
            
            if is_start:
                merchant_counts[merchant_name] = merchant_counts.get(merchant_name, 0) + 1
                active_live_events[event_key] = {
                    "type": "merchant",
                    "name": merchant_name,
                    "started_at": now_iso,
                    "server": guild_name,
                    "channel_name": message.channel.name,
                    "account_identity": account_identity,
                    "link": roblox_link or "None"
                }
            else:
                if event_key in active_live_events:
                    start_dt = datetime.fromisoformat(active_live_events[event_key]["started_at"])
                    delta = datetime.now(timezone.utc) - start_dt
                    duration_str = f"{int(delta.total_seconds() // 60)}m {int(delta.total_seconds() % 60)}s"
                    active_live_events.pop(event_key, None)
                    
                    if not is_forwarder and roblox_link:
                        webhook_activity[cid_str]["accounts"][roblox_link]["completed_sessions"].append({
                            "name": merchant_name, "duration": duration_str, "at": now_iso
                        })

            save_persisted_metrics()
            await backup_state_to_discord_cloud()
            metrics = get_metrics_payload()

            print("—" * 60)
            print(f"🛒 MERCHANT {event_type} | Account Target: {account_identity}")
            print("—" * 60)
            print(f"💬 Channel      : #{message.channel.name} {'[FORWARDER]' if is_forwarder else ''}")
            print(f"🧩 Item Name    : {merchant_name} | Runtime Length: {duration_str}")
            print(f"📡 Webhooks Active: {metrics['telemetry']['active_webhooks_last_10m']}/{metrics['telemetry']['total_registered_webhooks']}")
            print("—" * 60)

        else:
            biome_match = re.search(r"(?:Biome\s+(?:Started|Ended)(?:\s*:\s*|\s*-\s*))([A-Z_]+)", combined_text, re.IGNORECASE)
            if biome_match:
                biome_name = biome_match.group(1).upper()
            else:
                known_biomes = ["SINGULARITY", "GLITCHED", "DREAMSPACE", "CYBERSPACE", "STARFALL", "CORRUPTION", "WINDY", "SNOWY", "RAINY", "HELL", "NORMAL"]
                found_known = [b for b in known_biomes if b.lower() in combined_text_lower]
                if found_known:
                    biome_name = "SINGULARITY" if "SINGULARITY" in found_known else found_known[0]
                else:
                    words = re.findall(r"\b[A-Z]{4,}\b", combined_text)
                    filtered_words = [w for w in words if w not in ["START", "STARTED", "ENDED", "BIOME", "TIME", "INVITE", "SERVER", "PRIVATE", "LINK"]]
                    biome_name = filtered_words[0] if filtered_words else "UNKNOWN BIOME"

            event_type = "STARTED" if is_start else "ENDED"
            event_key = f"{cid_str}_{account_identity}_{biome_name}"
            duration_str = "N/A"
            
            if is_start:
                biome_counts[biome_name] = biome_counts.get(biome_name, 0) + 1
                active_live_events[event_key] = {
                    "type": "biome",
                    "name": biome_name,
                    "started_at": now_iso,
                    "server": guild_name,
                    "channel_name": message.channel.name,
                    "account_identity": account_identity,
                    "link": roblox_link or "None"
                }
            else:
                if event_key in active_live_events:
                    start_dt = datetime.fromisoformat(active_live_events[event_key]["started_at"])
                    delta = datetime.now(timezone.utc) - start_dt
                    duration_str = f"{int(delta.total_seconds() // 60)}m {int(delta.total_seconds() % 60)}s"
                    active_live_events.pop(event_key, None)
                    
                    if not is_forwarder and roblox_link:
                        if len(webhook_activity[cid_str]["accounts"][roblox_link]["completed_sessions"]) >= 10:
                            webhook_activity[cid_str]["accounts"][roblox_link]["completed_sessions"].pop(0)
                        webhook_activity[cid_str]["accounts"][roblox_link]["completed_sessions"].append({
                            "name": biome_name, "duration": duration_str, "at": now_iso
                        })

            save_persisted_metrics()
            await backup_state_to_discord_cloud()
            metrics = get_metrics_payload()

            print("—" * 60)
            print(f"🔮 BIOME {event_type} | Account Target: {account_identity}")
            print("—" * 60)
            print(f"💬 Channel      : #{message.channel.name} {'[FORWARDER]' if is_forwarder else ''}")
            print(f"🧩 Item Name    : {biome_name} | Biome Length: {duration_str}")
            print(f"📡 Webhooks Active: {metrics['telemetry']['active_webhooks_last_10m']}/{metrics['telemetry']['total_registered_webhooks']}")
            print("—" * 60)

# Fire up the HTTP keep-alive daemon thread before triggering the Discord loop
threading.Thread(target=keep_alive, daemon=True).start()

TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)
else:
    print("CRITICAL ERROR: Missing 'DISCORD_TOKEN' inside Environment Settings!")
