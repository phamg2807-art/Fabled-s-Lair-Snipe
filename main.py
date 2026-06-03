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

# Shut up the annoying "GET / HTTP/1.1" console logs from uptime checkers
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
# FIX LỖI 3: Đổi từ command_code thành command_prefix chuẩn của discord.py
bot = commands.Bot(command_prefix="!", intents=intents)

raw_channels = os.getenv("CHANNEL_IDS", "")
MONITORED_CHANNELS = [int(cid.strip()) for cid in raw_channels.split(",") if cid.strip().isdigit()]

# Danh sách từ khóa nhận diện các kênh săn bot tự động
TARGET_KEYWORDS = ["webhook", "forward", "found", "macro"]

# Danh sách các Biome cụ thể trong Sol's RNG để làm bộ quét dự phòng tối cao
KNOWN_BIOMES = [
    "WINDY", "SNOWY", "RAINY", "GLITCHED", "GLITCH", "CORRUPTION", 
    "HELL", "STARFALL", "METEOR", "PUMPKIN", "NORMAL", "GRAVEYARD", 
    "SANDSTORM", "BLOOD MOON", "CLASSIC"
]

def extract_roblox_link(text):
    match = re.search(r'https://(?:[a-zA-Z0-9\-]+\.)?roblox\.com/[^\s\)\}\]\"\']+', text)
    return match.group(0) if match else None

def clean_entity_name(raw_name):
    """Deep cleans names by removing markdown artifacts, formatting leaks, and stray emojis."""
    if not raw_name:
        return ""
    clean = raw_name.replace("**", "").replace("*", "").replace("__", "").replace("`", "").strip()
    clean = re.sub(r'<[^>]+>', '', clean).strip()
    clean = re.sub(r'^[^A-Za-z0-9\s\(]+', '', clean).strip()
    clean = re.sub(r'\s+', ' ', clean)
    
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
            # FIX LỖI 1: Ép kiểu channel.id thành str() trước khi chạy .ljust() để không bị crash crash bot
            logging.info(f"   {tag} ID: {str(channel.id).ljust(19)} | #{channel.name}")
    logging.info("📋 --- END OF VISIBLE CHANNELS CHECKLIST ---")
    print("="*60 + "\n")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    channel_name = getattr(message.channel, "name", "").lower()
    guild_name = getattr(message.channel.guild, "name", "Direct Message / Unknown")
    
    is_target_channel = any(keyword in channel_name for keyword in TARGET_KEYWORDS)
    is_fallback_id = message.channel.id in MONITORED_CHANNELS

    if not (is_target_channel or is_fallback_id):
        return

    text_to_search = message.content or ""
    
    if message.embeds:
        for embed in message.embeds:
            if embed.title:
                text_to_search += f"\nTitle: {embed.title}"
            if embed.url:
                text_to_search += f"\nEmbed URL: {embed.url}"
            if embed.description:
                text_to_search += f"\nDescription: {embed.description}"
            for field in embed.fields:
                text_to_search += f"\nField Name: {field.name}\nField Value: {field.value}"

    if message.components:
        for row in message.components:
            for component in row.children:
                if hasattr(component, 'url') and component.url:
                    text_to_search += f"\nButton URL: {component.url}"

    if not text_to_search.strip():
        return

    # Quét trạng thái hoạt động chính xác
    is_biome = "Biome Started" in text_to_search or "Biome Ended" in text_to_search or any(b in text_to_search.upper() for b in KNOWN_BIOMES)
    is_merchant = any(k in text_to_search for k in ["Merchant", "Mari", "Jester"])

    if is_biome or is_merchant:
        entity_name = ""
        status = "STARTED"
        
        if "Ended" in text_to_search or "ended" in text_to_search.lower():
            status = "ENDED"
            
        if is_biome:
            event_type = f"BIOME {status}"
        else:
            event_type = "MERCHANT SPAWN"
        
        # ------------------------------------------------------------
        # EXTRACTION LAYER FOR BIOMES
        # ------------------------------------------------------------
        if is_biome:
            # Strategy A: Quét cùng dòng dạng (Started/Ended)
            biome_match = re.search(r'Biome\s*(?:Started|Ended)[\s\*\:\-]*([^\n]+)', text_to_search, re.IGNORECASE)
            if biome_match:
                entity_name = clean_entity_name(biome_match.group(1))
            
            # Strategy B: Quét đa dòng từ dữ liệu thô
            if not entity_name:
                lines = text_to_search.split("\n")
                for i, line in enumerate(lines):
                    if any(k in line.lower() for k in ["biome started", "biome ended"]) and i + 1 < len(lines):
                        next_line = lines[i+1]
                        if "field value:" in next_line.lower():
                            entity_name = clean_entity_name(next_line.split("Field Value:", 1)[1])
                            break
                        else:
                            entity_name = clean_entity_name(next_line)
                            if entity_name: 
                                break

            # Strategy C: Kiểm tra cấu trúc trường dữ liệu "Field Name"
            if not entity_name:
                lines = text_to_search.split("\n")
                for i, line in enumerate(lines):
                    if "field name:" in line.lower() and "biome" in line.lower():
                        if i + 1 < len(lines) and "field value:" in lines[i+1].lower():
                            entity_name = clean_entity_name(lines[i+1].split("Field Value:", 1)[1])
                            break
            
            # FIX LỖI 2 (VIBE SAFETY NET): Nếu vẫn không tìm được hoặc ra chữ Unknown, quét toàn bộ text để tìm tên Biome gốc
            if not entity_name or entity_name.lower() == "unknown biome":
                for biome_keyword in KNOWN_BIOMES:
                    if biome_keyword in text_to_search.upper():
                        entity_name = biome_keyword
                        break
            
            if not entity_name:
                entity_name = "Unknown Biome"
            
        # ------------------------------------------------------------
        # EXTRACTION LAYER FOR MERCHANTS
        # ------------------------------------------------------------
        else:
            if "Mari" in text_to_search:
                entity_name = "Merchant (Mari)"
            elif "Jester" in text_to_search:
                entity_name = "Merchant (Jester)"
            else:
                merchant_match = re.search(r'Merchant(?:s)?(?:[\s\w]+)?[\s\*\:\-]*([^\n]+)', text_to_search, re.IGNORECASE)
                if merchant_match:
                    entity_name = clean_entity_name(merchant_match.group(1))
                
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
        db_display_name = f"{entity_name} ({status})" if is_biome else entity_name

        # ------------------------------------------------------------
        # CLEAN TERMINAL DASHBOARD
        # ------------------------------------------------------------
        print("\n" + "═"*60)
        print(f" 🎯 EXTRACTION LOG - {event_type}")
        print("─"*60)
        print(f" 🏰 Server Name : {guild_name}")
        print(f" 📺 Channel     : #{getattr(message.channel, 'name', 'Unknown')} (ID: {message.channel.id})")
        print(f" 👤 Author      : {message.author}")
        print(f" ✨ Parsed Item : {db_display_name}")
        print(f" 🔗 Link Found  : {roblox_link if roblox_link else 'None'}")
        print("─"*60)
        
        if roblox_link:
            if supabase:
                try:
                    data, count = supabase.table("servers").insert({
                        "server_link": roblox_link, 
                        "biome_name": db_display_name
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
        logging.info(f"📥 [FILTERED] Msg from '{message.author}' in #{getattr(message.channel, 'name', 'Unknown')} dropped (No keyword matches found for Biome/Merchant).")

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
