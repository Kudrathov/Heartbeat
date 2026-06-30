import os
import asyncio
import sqlite3
import logging
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.enums import ParseMode

# ===== НАСТРОЙКИ =====
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# ИСПРАВЛЕНО: Теперь запрашиваются имена переменных, а не их значения
BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEBAPP_URL = os.environ.get("WEBAPP_URL")

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не установлен в Railway Variables!")
if not WEBAPP_URL:
    raise ValueError("❌ WEBAPP_URL не установлен в Railway Variables!")

logger.info(f"🚀 Запуск бота... URL: {WEBAPP_URL}")

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
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS couples (
            user_id INTEGER PRIMARY KEY,
            partner_id INTEGER NOT NULL
        )""")
    logger.info("✅ База данных готова")

init_db()

def save_user(user_id, username, first_name):
    with get_db() as db:
        db.execute("INSERT OR IGNORE INTO users VALUES (?,?,?)", (user_id, username, first_name))

def set_pair(a, b):
    with get_db() as db:
        db.execute("INSERT OR REPLACE INTO couples VALUES (?,?)", (a, b))
        db.execute("INSERT OR REPLACE INTO couples VALUES (?,?)", (b, a))
    logger.info(f"💞 Пара создана: {a} <-> {b}")

def get_partner(user_id):
    with get_db() as db:
        row = db.execute("SELECT partner_id FROM couples WHERE user_id=?", (user_id,)).fetchone()
        return row['partner_id'] if row else None

def get_user(user_id):
    with get_db() as db:
        return db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()

# ===== ОЖИДАЮЩИЕ ПАРЫ =====
pending = {}  # user_id -> partner_id

# ===== /start =====
@router.message(CommandStart())
async def cmd_start(msg: Message):
    user_id = msg.from_user.id
    save_user(user_id, msg.from_user.username, msg.from_user.first_name)
    logger.info(f"📩 /start от {user_id} ({msg.from_user.first_name})")
    
    # Deep link: ?start=pair_123456
    args = msg.text.split() if msg.text else []
    if len(args) > 1 and args[1].startswith("pair_"):
        try:
            partner_id = int(args[1].split("_")[1])
            if partner_id == user_id:
                await msg.answer("❌ Нельзя связаться с самим собой!")
                return
            
            partner = get_user(partner_id)
            if not partner:
                await msg.answer(
                    "❌ Этот пользователь ещё не запускал бота.\n"
                    "Попроси его сначала нажать /start!"
                )
                return
            
            pending[user_id] = partner_id
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Да, связать нас!", callback_data="confirm")]
            ])
            await msg.answer(
                f"💕 **{partner['first_name'] or 'Партнёр'}** приглашает тебя в Heartbeat!\n\n"
                f"Подтвердить связь?",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb
            )
            return
        except (ValueError, IndexError):
            pass
    
    # Обычный старт
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💗 Открыть Heartbeat", web_app=WebAppInfo(url=WEBAPP_URL))],
        [InlineKeyboardButton(text="🔗 Моя ссылка для партнёра", callback_data="mylink")],
        [InlineKeyboardButton(text="📊 Мой статус", callback_data="status")],
    ])
    await msg.answer(
        f"💓 **Привет, {msg.from_user.first_name or 'друг'}!**\n\n"
        f"Это **Heartbeat** — приложение для пар на расстоянии.\n\n"
        f"1️⃣ Нажми **🔗 Моя ссылка для партнёра**\n"
        f"2️⃣ Отправь ссылку любимому человеку\n"
        f"3️⃣ Когда он подтвердит — можно отправлять сигналы!\n\n"
        f"⚠️ **Важно:** оба должны нажать /start в боте!",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb
    )

# ===== ССЫЛКА ДЛЯ ПАРТНЁРА =====
@router.callback_query(F.data == "mylink")
async def my_link(cb: CallbackQuery):
    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start=pair_{cb.from_user.id}"
    await cb.message.answer(
        f"🔗 **Твоя ссылка для партнёра:**\n\n`{link}`\n\n"
        f"Скопируй и отправь ему в Telegram!",
        parse_mode=ParseMode.MARKDOWN
    )

# ===== ПОДТВЕРЖДЕНИЕ ПАРЫ =====
@router.callback_query(F.data == "confirm")
async def confirm(cb: CallbackQuery):
    user_id = cb.from_user.id
    partner_id = pending.get(user_id)
    
    if not partner_id:
        await cb.answer("❌ Ссылка устарела", show_alert=True)
        return
    
    set_pair(user_id, partner_id)
    del pending[user_id]
    
    await cb.message.edit_text(
        "💞 **Вы связаны!**\n\nТеперь отправляйте друг другу сигналы!",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💗 Открыть Heartbeat", web_app=WebAppInfo(url=WEBAPP_URL))]
        ])
    )
    
    # Уведомление партнёру
    try:
        partner = get_user(partner_id)
        await bot.send_message(
            partner_id,
            f"🎉 **{cb.from_user.first_name or 'Партнёр'}** принял связь!\n\n"
            f"Откройте Heartbeat и нажмите на сердечко 💓",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💗 Открыть Heartbeat", web_app=WebAppInfo(url=WEBAPP_URL))]
            ])
        )
        logger.info(f"✅ Уведомление отправлено {partner_id}")
    except Exception as e:
        logger.error(f"❌ Ошибка отправки {partner_id}: {e}")

# ===== СТАТУС =====
@router.callback_query(F.data == "status")
async def status(cb: CallbackQuery):
    partner_id = get_partner(cb.from_user.id)
    if partner_id:
        partner = get_user(partner_id)
        name = partner['first_name'] if partner else f"ID {partner_id}"
        text = f"✅ **Вы связаны!**\n💕 Партнёр: {name}"
    else:
        text = "❌ **Вы не связаны.**\nНажми 🔗 Моя ссылка для партнёра"
    await cb.message.answer(text, parse_mode=ParseMode.MARKDOWN)

# ===== ДАННЫЕ ИЗ MINI APP =====
@router.message(F.web_app_data)
async def webapp_data(msg: Message):
    user_id = msg.from_user.id
    data = msg.web_app_data.data
    logger.info(f"📲 WebApp от {user_id}: {data}")
    
    partner_id = get_partner(user_id)
    if not partner_id:
        await msg.answer("❌ Сначала свяжитесь с партнёром!")
        return
    
    emotions = {
        'miss_you': ('💗', 'Скучаю по тебе!', 'heartbeat'),
        'emotion_miss': ('💭', 'Скучаю...', 'miss'),
        'emotion_love': ('💖', 'Люблю тебя!', 'love'),
        'emotion_think': ('💫', 'Думаю о тебе...', 'think'),
        'emotion_kiss': ('😘', 'Поцелуй!', 'kiss')
    }
    emoji, text, vibe = emotions.get(data, ('💗', 'Сигнал!', 'heartbeat'))
    
    beat_url = f"{WEBAPP_URL}?beat=1&emotion={vibe}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{emoji} Почувствовать", web_app=WebAppInfo(url=beat_url))]
    ])
    
    try:
        await bot.send_message(
            partner_id,
            f"{emoji} **{text}**\n\nНажми кнопку, чтобы почувствовать 💓",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb
        )
        logger.info(f"✅ Отправлено {partner_id}: {text}")
        await msg.answer("✅ Отправлено!")
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        await msg.answer("❌ Не удалось отправить. Партнёр не нажал /start?")

# ===== DEBUG =====
@router.message(Command("debug"))
async def debug(msg: Message):
    with get_db() as db:
        users = db.execute("SELECT * FROM users").fetchall()
        couples = db.execute("SELECT * FROM couples").fetchall()
    
    text = f"🔧 **DEBUG**\n\n👥 Пользователи ({len(users)}):\n"
    for u in users:
        text += f"  • {u['user_id']} — {u['first_name']} (@{u['username']})\n"
    text += f"\n💞 Пары ({len(couples)//2}):\n"
    for c in couples:
        text += f"  • {c['user_id']} <-> {c['partner_id']}\n"
    await msg.answer(text, parse_mode=ParseMode.MARKDOWN)

# ===== ЗАПУСК =====
if __name__ == "__main__":
    asyncio.run(dp.start_polling(bot))
