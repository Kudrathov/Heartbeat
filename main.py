import os
import asyncio
import sqlite3
import logging
import time
from aiogram import Bot, Dispatcher, Router
from aiogram.types import Message, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import CommandStart
from aiogram.enums import ParseMode
from aiohttp import web

# ===== НАСТРОЙКИ =====
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEBAPP_URL = os.environ.get("WEBAPP_URL")

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не установлен!")
if not WEBAPP_URL:
    raise ValueError("❌ WEBAPP_URL не установлен!")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

# ===== БАЗА ДАННЫХ =====
def get_db():
    conn = sqlite3.connect("couples.db")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS couples (
            user_id INTEGER PRIMARY KEY, partner_id INTEGER NOT NULL
        )""")
        # Новая таблица для сигналов
        db.execute("""CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user INTEGER,
            to_user INTEGER,
            emotion TEXT,
            timestamp REAL,
            delivered INTEGER DEFAULT 0
        )""")
    logger.info("✅ База данных и таблица сигналов готовы")

init_db()

def get_partner(user_id):
    with get_db() as db:
        row = db.execute("SELECT partner_id FROM couples WHERE user_id=?", (user_id,)).fetchone()
        return row['partner_id'] if row else None

# ===== ПУШ-УВЕДОМЛЕНИЕ В ЧАТ =====
async def send_fallback_push(partner_id, emotion):
    emotions = {
        'miss_you': ('💗', 'Скучаю по тебе!'),
        'emotion_miss': ('💭', 'Скучаю...'),
        'emotion_love': ('💖', 'Люблю тебя!'),
        'emotion_think': ('💫', 'Думаю о тебе...'),
        'emotion_kiss': ('😘', 'Поцелуй!')
    }
    emoji, text = emotions.get(emotion, ('💗', 'Сигнал!'))
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💗 Открыть Heartbeat", web_app=WebAppInfo(url=WEBAPP_URL))]
    ])
    try:
        await bot.send_message(
            partner_id,
            f"{emoji} **{text}**\n\nЗайди в приложение, чтобы почувствовать 💓",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb
        )
        logger.info(f"🔔 Отправлен пуш в чат для {partner_id}")
    except Exception as e:
        logger.error(f"Ошибка отправки пуша: {e}")

# ===== HTTP API ДЛЯ МГНОВЕННОГОО ОБМЕНА =====
async def handle_click(request):
    headers = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type"}
    if request.method == "OPTIONS": return web.Response(status=200, headers=headers)
    
    try:
        data = await request.json()
        user_id = int(data.get("user_id"))
        emotion = data.get("emotion", "heartbeat")
        
        partner_id = get_partner(user_id)
        if not partner_id:
            return web.json_response({"status": "error", "message": "Пара не найдена"}, headers=headers)
            
        # Записываем сигнал в базу данных
        with get_db() as db:
            db.execute(
                "INSERT INTO signals (from_user, to_user, emotion, timestamp) VALUES (?, ?, ?, ?)",
                (user_id, partner_id, emotion, time.time())
            )
            
        # Запускаем фоновую задачу: если партнер не заберёт сигнал из приложения за 3 секунды -> шлём пуш в чат
        async def push_delayed():
            await asyncio.sleep(3.0)
            with get_db() as db_check:
                # Проверяем, был ли доставлен этот сигнал
                row = db_check.execute(
                    "SELECT delivered FROM signals WHERE from_user=? AND to_user=? AND emotion=? AND delivered=0", 
                    (user_id, partner_id, emotion)
                ).fetchone()
                if row:
                    # Сигнал всё еще не доставлен в приложение — отправляем в чат Telegram
                    await send_fallback_push(partner_id, emotion)
                    db_check.execute("UPDATE signals SET delivered = 2 WHERE from_user=? AND to_user=? AND delivered=0", (user_id, partner_id))
                    
        asyncio.create_task(push_delayed())
        
        return web.json_response({"status": "ok"}, headers=headers)
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, headers=headers)

# API проверки входящих сигналов (фронтенд будет опрашивать его каждые 1-2 секунды)
async def check_signals(request):
    headers = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type"}
    if request.method == "OPTIONS": return web.Response(status=200, headers=headers)
    
    try:
        data = await request.json()
        user_id = int(data.get("user_id"))
        
        with get_db() as db:
            # Ищем новые недоставленные сигналы для этого пользователя
            rows = db.execute(
                "SELECT * FROM signals WHERE to_user=? AND delivered=0 ORDER BY timestamp ASC", 
                (user_id,)
            ).fetchall()
            
            signals_list = []
            if rows:
                for row in rows:
                    signals_list.append({"emotion": row["emotion"]})
                # Отмечаем как доставленные в приложение
                db.execute("UPDATE signals SET delivered = 1 WHERE to_user=? AND delivered=0", (user_id,))
                
            return web.json_response({"status": "ok", "signals": signals_list}, headers=headers)
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, headers=headers)


@router.message(CommandStart())
async def cmd_start(msg: Message):
    user_id = msg.from_user.id
    with get_db() as db:
        db.execute("INSERT OR IGNORE INTO users VALUES (?,?,?)", (user_id, msg.from_user.username, msg.from_user.first_name))
    
    args = msg.text.split() if msg.text else []
    if len(args) > 1 and args[1].startswith("pair_"):
        try:
            partner_id = int(args[1].split("_")[1])
            if partner_id != user_id:
                with get_db() as db:
                    db.execute("INSERT OR REPLACE INTO couples VALUES (?,?)", (user_id, partner_id))
                    db.execute("INSERT OR REPLACE INTO couples VALUES (?,?)", (partner_id, user_id))
                await msg.answer("💞 **Вы успешно связались!** Открывайте Heartbeat!")
                return
        except: pass

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💗 Открыть Heartbeat", web_app=WebAppInfo(url=WEBAPP_URL))]])
    await msg.answer("💓 **Привет!** Открой приложение, чтобы отправлять сигналы.", reply_markup=kb)

async def main():
    app = web.Application()
    app.router.add_post('/api/click', handle_click)
    app.router.add_options('/api/click', handle_click)
    app.router.add_post('/api/check', check_signals)
    app.router.add_options('/api/check', check_signals)
    
    port = int(os.environ.get("PORT", 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    
    asyncio.create_task(site.start())
    logger.info(f"🔥 Real-time API запущен на порту {port}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
