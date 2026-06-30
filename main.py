import os
import asyncio
import sqlite3
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["8523526764:AAHRv4AlNsmfJcclqqERrbzryHNOmAppc_Q"]
WEBAPP_URL = os.environ["https://heartbeat-coral.vercel.app/"]

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

# Database
def init_db():
    with sqlite3.connect("couples.db") as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS couples (
                user_id INTEGER PRIMARY KEY,
                partner_id INTEGER,
                username TEXT,
                total_sent INTEGER DEFAULT 0,
                streak INTEGER DEFAULT 0,
                last_sent DATE
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS heartbeats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER,
                receiver_id INTEGER,
                emotion TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
init_db()

def set_pair(a, b, ua, ub):
    with sqlite3.connect("couples.db") as db:
        db.execute("INSERT OR REPLACE INTO couples (user_id, partner_id, username) VALUES (?,?,?)", (a, b, ua))
        db.execute("INSERT OR REPLACE INTO couples (user_id, partner_id, username) VALUES (?,?,?)", (b, a, ub))
    logger.info(f"Пара создана: {a} <-> {b}")

def get_partner(user_id):
    with sqlite3.connect("couples.db") as db:
        cur = db.execute("SELECT partner_id FROM couples WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        if row:
            logger.info(f"Партнёр для {user_id}: {row[0]}")
            return row[0]
        logger.warning(f"Партнёр для {user_id} не найден")
        return None

def update_stats(user_id, emotion):
    with sqlite3.connect("couples.db") as db:
        today = datetime.now().date()
        db.execute("""
            INSERT INTO couples (user_id, partner_id, username, total_sent, streak, last_sent)
            VALUES (?, 0, '', 1, 1, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                total_sent = total_sent + 1,
                streak = CASE 
                    WHEN last_sent = date('now', '-1 day') THEN streak + 1
                    WHEN last_sent = date('now') THEN streak
                    ELSE streak + 1
                END,
                last_sent = ?
        """, (user_id, today, today))
        
        partner = get_partner(user_id)
        if partner:
            db.execute("INSERT INTO heartbeats (sender_id, receiver_id, emotion) VALUES (?,?,?)",
                      (user_id, partner, emotion))
            logger.info(f"Статистика обновлена: {user_id} -> {partner}, эмоция: {emotion}")

# Handlers
pending = {}

@router.message(CommandStart())
async def start(msg: Message):
    args = msg.text.split() if msg.text else []
    
    # Check for pairing
    if len(args) > 1 and args[1].startswith("pair_"):
        try:
            partner_id = int(args[1].split("_")[1])
            if partner_id == msg.from_user.id:
                await msg.answer("❌ Нельзя связаться с самим собой!")
                return
                
            pending[msg.from_user.id] = partner_id
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Да, связать нас", callback_data="confirm_pair")]
            ])
            await msg.answer(
                f"💕 **Вас хотят связать в Heartbeat!**\n\n"
                f"Подтвердите связь с партнёром?",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb
            )
            logger.info(f"Запрос на связь: {msg.from_user.id} хочет связаться с {partner_id}")
            return
        except (ValueError, IndexError) as e:
            logger.error(f"Ошибка разбора deep link: {e}")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="💗 Открыть Heartbeat",
            web_app=WebAppInfo(url=WEBAPP_URL)
        )],
        [InlineKeyboardButton(text="🔗 Связаться с партнёром", callback_data="link")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")]
    ])
    await msg.answer(
        "💓 **Добро пожаловать в Heartbeat!**\n\n"
        "Отправляй сигналы любимому человеку — "
        "его телефон **завибрирует** и получит уведомление! 📳💕\n\n"
        "Нажми кнопку ниже, чтобы начать 💕",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb
    )

@router.callback_query(F.data == "link")
async def link_cmd(cb: CallbackQuery):
    bot_username = (await bot.get_me()).username
    link = f"https://t.me/{bot_username}?start=pair_{cb.from_user.id}"
    await cb.message.answer(
        f"🔗 **Отправь эту ссылку партнёру:**\n\n"
        f"`{link}`\n\n"
        "Когда партнёр перейдёт по ссылке и подтвердит связь — "
        "вы сможете отправлять друг другу сигналы! 💕",
        parse_mode=ParseMode.MARKDOWN
    )

@router.callback_query(F.data == "confirm_pair")
async def confirm_pair(cb: CallbackQuery):
    a = cb.from_user.id
    b = pending.get(a)
    
    if not b:
        await cb.answer("❌ Ссылка устарела. Запросите новую ссылку.", show_alert=True)
        return
    
    try:
        set_pair(a, b, cb.from_user.username, "")
        del pending[a]
        
        await cb.message.answer(
            "💞 **Вы связаны!**\n\n"
            "Теперь вы можете отправлять друг другу сигналы любви! "
            "Откройте Heartbeat и нажмите на сердечко 💓",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Отправляем уведомление партнёру
        try:
            await bot.send_message(
                b,
                "💞 **Ваш партнёр принял связь!**\n\n"
                "Откройте Heartbeat и отправьте первый сигнал любви! 💓\n\n"
                "Нажмите на кнопку ниже, чтобы открыть приложение:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💗 Открыть Heartbeat", web_app=WebAppInfo(url=WEBAPP_URL))]
                ])
            )
            logger.info(f"Уведомление отправлено партнёру {b}")
        except TelegramBadRequest as e:
            logger.error(f"Не удалось отправить сообщение партнёру {b}: {e}")
            await cb.answer("Партнёр не найден или заблокировал бота", show_alert=True)
            
    except Exception as e:
        logger.error(f"Ошибка при подтверждении пары: {e}")
        await cb.answer("Произошла ошибка. Попробуйте ещё раз.", show_alert=True)

@router.callback_query(F.data == "stats")
async def show_stats(cb: CallbackQuery):
    with sqlite3.connect("couples.db") as db:
        cur = db.execute("SELECT total_sent, streak FROM couples WHERE user_id=?", (cb.from_user.id,))
        row = cur.fetchone()
        
        if row:
            total, streak = row
            await cb.message.answer(
                f"📊 **Ваша статистика:**\n\n"
                f"💗 Всего отправлено: {total}\n"
                f"🔥 Дней подряд: {streak}",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await cb.message.answer("Пока нет статистики. Отправьте первый сигнал! 💓")

@router.message(F.web_app_data)
async def webapp_data(msg: Message):
    data = msg.web_app_data.data
    logger.info(f"Получены данные из WebApp от {msg.from_user.id}: {data}")
    
    partner = get_partner(msg.from_user.id)
    
    if not partner:
        await msg.answer(
            "❌ Сначала свяжитесь с партнёром через кнопку 🔗",
            show_alert=True
        )
        return
    
    emotion_texts = {
        'miss_you': ('💗', 'Скучаю по тебе!', 'heartbeat'),
        'emotion_miss': ('💭', 'Скучаю...', 'miss'),
        'emotion_love': ('💖', 'Люблю тебя!', 'love'),
        'emotion_think': ('💫', 'Думаю о тебе...', 'think'),
        'emotion_kiss': ('😘', 'Посылаю поцелуй!', 'kiss')
    }
    
    emoji, text, vibe_type = emotion_texts.get(data, ('💗', 'Отправил сигнал!', 'heartbeat'))
    
    # Update stats
    update_stats(msg.from_user.id, data)
    
    # Формируем URL с параметром вибрации
    beat_url = f"{WEBAPP_URL}?beat=1&emotion={vibe_type}"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{emoji} Открыть и почувствовать",
            web_app=WebAppInfo(url=beat_url)
        )]
    ])
    
    try:
        await bot.send_message(
            partner,
            f"{emoji} **Ваш любимый человек: {text}**\n\n"
            f"Нажмите на кнопку ниже, чтобы **почувствовать вибрацию** и ответить! 💓",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb
        )
        logger.info(f"Уведомление отправлено партнёру {partner}: {text}")
        await msg.answer(f"✅ {text} Сигнал отправлен партнёру!")
    except TelegramBadRequest as e:
        logger.error(f"Не удалось отправить уведомление партнёру {partner}: {e}")
        await msg.answer("❌ Не удалось отправить сигнал. Возможно, партнёр заблокировал бота.", show_alert=True)

if __name__ == "__main__":
    logger.info("Запуск бота...")
    asyncio.run(dp.start_polling(bot))
