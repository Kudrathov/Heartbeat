import os
import asyncio
import sqlite3
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.enums import ParseMode

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

# ВАЖНО: Имена переменных должны быть ТОЧНО такими, как в Railway!
BOT_TOKEN = os.environ.get("8523526764:AAHRv4AlNsmfJcclqqERrbzryHNOmAppc_Q")
WEBAPP_URL = os.environ.get("https://heartbeat-coral.vercel.app/")

if not BOT_TOKEN or not WEBAPP_URL:
    raise ValueError(" Ошибка: Не установлены переменные BOT_TOKEN или WEBAPP_URL в Railway Variables!")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

# ... дальше идет остальной код бота (init_db и т.д.) ...

# ========== БАЗА ДАННЫХ ==========
def get_db():
    conn = sqlite3.connect("couples.db")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                started_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS couples (
                user_id INTEGER PRIMARY KEY,
                partner_id INTEGER NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS heartbeats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER,
                receiver_id INTEGER,
                emotion TEXT,
                sent_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
    logger.info("✅ База данных инициализирована")

init_db()

def save_user(user_id, username, first_name):
    with get_db() as db:
        db.execute(
            "INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?,?,?)",
            (user_id, username, first_name)
        )
        db.commit()
    logger.info(f"👤 Пользователь сохранён: {user_id} (@{username})")

def set_pair(user_id, partner_id):
    with get_db() as db:
        db.execute("INSERT OR REPLACE INTO couples (user_id, partner_id) VALUES (?,?)", (user_id, partner_id))
        db.execute("INSERT OR REPLACE INTO couples (user_id, partner_id) VALUES (?,?)", (partner_id, user_id))
        db.commit()
    logger.info(f"💞 Пара создана: {user_id} <-> {partner_id}")

def get_partner(user_id):
    with get_db() as db:
        row = db.execute("SELECT partner_id FROM couples WHERE user_id=?", (user_id,)).fetchone()
        if row:
            logger.info(f"🔍 Партнёр для {user_id}: {row['partner_id']}")
            return row['partner_id']
        logger.warning(f"❌ Партнёр для {user_id} НЕ НАЙДЕН")
        return None

def get_user_info(user_id):
    with get_db() as db:
        return db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()

def log_heartbeat(sender, receiver, emotion):
    with get_db() as db:
        db.execute("INSERT INTO heartbeats (sender_id, receiver_id, emotion) VALUES (?,?,?)",
                  (sender, receiver, emotion))
        db.commit()

# ========== ОБРАБОТЧИКИ ==========

pending_pairs = {}  # user_id -> partner_id (ожидают подтверждения)

@router.message(CommandStart())
async def cmd_start(msg: Message):
    user_id = msg.from_user.id
    username = msg.from_user.username or ""
    first_name = msg.from_user.first_name or ""
    
    save_user(user_id, username, first_name)
    logger.info(f" /start от {user_id} (@{username})")
    
    # Проверяем deep link (ссылка на связь)
    args = msg.text.split() if msg.text else []
    if len(args) > 1 and args[1].startswith("pair_"):
        try:
            partner_id = int(args[1].split("_")[1])
            logger.info(f" {user_id} получил ссылку на связь с {partner_id}")
            
            # Проверяем что партнёр существует в БД
            partner_info = get_user_info(partner_id)
            if not partner_info:
                await msg.answer(
                    "❌ Этот пользователь ещё не запускал бота. "
                    "Попроси его сначала нажать /start в боте!",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text=" Скопировать свою ссылку", callback_data="get_link")]
                    ])
                )
                return
            
            pending_pairs[user_id] = partner_id
            
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Да, связать нас!", callback_data="confirm_pair")]
            ])
            await msg.answer(
                f"💕 **Вас приглашают в Heartbeat!**\n\n"
                f"Пользователь **{partner_info['first_name'] or partner_info['username']}** "
                f"хочет связаться с тобой.\n\n"
                f"Подтверди связь?",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb
            )
            return
        except (ValueError, IndexError) as e:
            logger.error(f"Ошибка deep link: {e}")
    
    # Обычный старт
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💗 Открыть Heartbeat", web_app=WebAppInfo(url=WEBAPP_URL))],
        [InlineKeyboardButton(text="🔗 Связаться с партнёром", callback_data="get_link")],
        [InlineKeyboardButton(text=" Мой статус", callback_data="status")],
        [InlineKeyboardButton(text="📖 Как это работает?", callback_data="help")]
    ])
    
    await msg.answer(
        f"💓 **Привет, {first_name or 'друг'}!**\n\n"
        f"Это **Heartbeat** — приложение для пар на расстоянии.\n\n"
        f"1️ Нажми **🔗 Связаться с партнёром**\n"
        f"2️⃣ Отправь ссылку любимому человеку\n"
        f"3️⃣ Когда он подтвердит — вы сможете отправлять друг другу сигналы!\n\n"
        f"⚠️ **Важно:** партнёр тоже должен нажать /start в этом боте!",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb
    )

@router.callback_query(F.data == "get_link")
async def get_link(cb: CallbackQuery):
    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start=pair_{cb.from_user.id}"
    
    partner = get_partner(cb.from_user.id)
    status_text = "✅ Вы связаны!" if partner else "❌ Пока не связаны"
    
    await cb.message.answer(
        f"📊 **Твой статус:** {status_text}\n\n"
        f" **Твоя ссылка для партнёра:**\n\n"
        f"`{link}`\n\n"
        f" Скопируй и отправь любимому человеку!\n\n"
        f"️ Он должен сначала нажать /start в боте, потом перейти по ссылке.",
        parse_mode=ParseMode.MARKDOWN
    )

@router.callback_query(F.data == "confirm_pair")
async def confirm_pair(cb: CallbackQuery):
    user_id = cb.from_user.id
    partner_id = pending_pairs.get(user_id)
    
    logger.info(f" {user_id} нажал confirm_pair, pending={partner_id}")
    
    if not partner_id:
        await cb.answer("❌ Ссылка устарела. Попроси новую.", show_alert=True)
        return
    
    # Создаём пару
    set_pair(user_id, partner_id)
    del pending_pairs[user_id]
    
    await cb.message.edit_text(
        "💞 **Вы связаны!**\n\n"
        "Теперь вы можете отправлять друг другу сигналы любви! 💓\n\n"
        "Нажми кнопку ниже, чтобы открыть приложение:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💗 Открыть Heartbeat", web_app=WebAppInfo(url=WEBAPP_URL))]
        ])
    )
    
    # УВЕДОМЛЕНИЕ ПАРТНЁРУ
    try:
        partner_info = get_user_info(partner_id)
        await bot.send_message(
            partner_id,
            f"🎉 **Отличные новости!**\n\n"
            f"**{cb.from_user.first_name or 'Твой партнёр'}** подтвердил связь с тобой!\n\n"
            f"Теперь вы можете отправлять друг другу сигналы. "
            f"Открой Heartbeat и нажми на сердечко! 💓",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💗 Открыть Heartbeat", web_app=WebAppInfo(url=WEBAPP_URL))]
            ])
        )
        logger.info(f"✅ Уведомление отправлено партнёру {partner_id}")
    except Exception as e:
        logger.error(f"❌ Не удалось отправить уведомление партнёру {partner_id}: {e}")
        await bot.send_message(
            user_id,
            f"⚠️ Пара создана, но не удалось уведомить партнёра. "
            f"Возможно, он не нажал /start в боте. Попроси его сделать это!",
        )

@router.callback_query(F.data == "status")
async def show_status(cb: CallbackQuery):
    user_id = cb.from_user.id
    partner = get_partner(user_id)
    user_info = get_user_info(user_id)
    
    if partner:
        partner_info = get_user_info(partner)
        partner_name = partner_info['first_name'] if partner_info else f"ID {partner}"
        text = (
            f"✅ **Вы связаны!**\n\n"
            f"👤 Ты: {user_info['first_name'] or user_info['username'] or 'Аноним'}\n"
            f"💕 Партнёр: {partner_name}\n\n"
            f"Теперь нажимайте на сердечко в приложении! 💓"
        )
    else:
        text = (
            f"❌ **Вы пока не связаны.**\n\n"
            f"Нажми **🔗 Связаться с партнёром** и отправь ему ссылку.\n\n"
            f"⚠️ Партнёр должен сначала нажать /start в боте!"
        )
    
    await cb.message.answer(text, parse_mode=ParseMode.MARKDOWN)

@router.callback_query(F.data == "help")
async def show_help(cb: CallbackQuery):
    await cb.message.answer(
        "📖 **Как работает Heartbeat:**\n\n"
        "1️⃣ Оба нажимают /start в боте\n"
        "2️⃣ Один генерирует ссылку и отправляет другому\n"
        "3️ Второй переходит по ссылке и подтверждает\n"
        "4️⃣ Готово! Теперь можно отправлять сигналы\n\n"
        "💓 Когда ты нажимаешь на сердечко:\n"
        "• Партнёр получает уведомление в Telegram\n"
        "• Он нажимает на кнопку в сообщении\n"
        "• Открывается приложение и телефон **вибрирует**\n\n"
        "⚠️ Уведомления приходят только если партнёр нажал /start!",
        parse_mode=ParseMode.MARKDOWN
    )

@router.message(F.web_app_data)
async def webapp_data(msg: Message):
    user_id = msg.from_user.id
    data = msg.web_app_data.data
    
    logger.info(f"📲 WebApp данные от {user_id}: {data}")
    
    partner = get_partner(user_id)
    if not partner:
        await msg.answer(
            "❌ Сначала свяжитесь с партнёром!\n\n"
            "Нажми кнопку 🔗 Связаться с партнёром в боте.",
            show_alert=True
        )
        return
    
    # Определяем эмоцию
    emotions = {
        'miss_you': ('💗', 'Скучаю по тебе!', 'heartbeat'),
        'emotion_miss': ('💭', 'Скучаю...', 'miss'),
        'emotion_love': ('💖', 'Люблю тебя!', 'love'),
        'emotion_think': ('💫', 'Думаю о тебе...', 'think'),
        'emotion_kiss': ('😘', 'Посылаю поцелуй!', 'kiss')
    }
    
    emoji, text, vibe = emotions.get(data, ('💗', 'Отправил сигнал!', 'heartbeat'))
    
    # Логируем
    log_heartbeat(user_id, partner, data)
    logger.info(f"💓 {user_id} -> {partner}: {text}")
    
    # Отправляем УВЕДОМЛЕНИЕ партнёру
    beat_url = f"{WEBAPP_URL}?beat=1&emotion={vibe}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{emoji} Почувствовать",
            web_app=WebAppInfo(url=beat_url)
        )]
    ])
    
    try:
        await bot.send_message(
            partner,
            f"{emoji} **Твой любимый человек: {text}**\n\n"
            f"Нажми на кнопку, чтобы почувствовать вибрацию! 💓",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb
        )
        logger.info(f"✅ Уведомление доставлено партнёру {partner}")
        await msg.answer(f"✅ Сигнал отправлен!")
    except Exception as e:
        logger.error(f"❌ Ошибка отправки партнёру {partner}: {e}")
        await msg.answer(
            "❌ Не удалось отправить сигнал. "
            "Возможно, партнёр заблокировал бота или не нажал /start.",
            show_alert=True
        )

@router.message(Command("debug"))
async def debug_cmd(msg: Message):
    """Команда для отладки — показывает всё что в БД"""
    user_id = msg.from_user.id
    with get_db() as db:
        users = db.execute("SELECT * FROM users").fetchall()
        couples = db.execute("SELECT * FROM couples").fetchall()
        heartbeats = db.execute("SELECT * FROM heartbeats ORDER BY id DESC LIMIT 5").fetchall()
    
    text = f"🔧 **DEBUG**\n\n"
    text += f"👥 **Пользователи ({len(users)}):**\n"
    for u in users:
        text += f"  • {u['user_id']} @{u['username']} ({u['first_name']})\n"
    
    text += f"\n💞 **Пары ({len(couples)}):**\n"
    for c in couples:
        text += f"  • {c['user_id']} <-> {c['partner_id']}\n"
    
    text += f"\n💓 **Последние сигналы:**\n"
    for h in heartbeats:
        text += f"  • {h['sender_id']} -> {h['receiver_id']}: {h['emotion']}\n"
    
    await msg.answer(text, parse_mode=ParseMode.MARKDOWN)

if __name__ == "__main__":
    logger.info(f"🚀 Запуск бота... URL: {WEBAPP_URL}")
    asyncio.run(dp.start_polling(bot))
