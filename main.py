import asyncio
import sqlite3
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import CommandStart
from aiogram.enums import ParseMode

BOT_TOKEN = "8523526764:AAHRv4AlNsmfJcclqqERrbzryHNOmAppc_Q"
WEBAPP_URL = "https://heartbeat-coral.vercel.app/"  # куда залишь Mini App

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

# ---------- БД ----------
def init_db():
    with sqlite3.connect("couples.db") as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS couples (
                user_id INTEGER PRIMARY KEY,
                partner_id INTEGER,
                username TEXT
            )
        """)
init_db()

def set_pair(a, b, ua, ub):
    with sqlite3.connect("couples.db") as db:
        db.execute("INSERT OR REPLACE INTO couples VALUES (?,?,?)", (a, b, ua))
        db.execute("INSERT OR REPLACE INTO couples VALUES (?,?,?)", (b, a, ub))

def get_partner(user_id):
    with sqlite3.connect("couples.db") as db:
        cur = db.execute("SELECT partner_id FROM couples WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        return row[0] if row else None

# ---------- Хендлеры ----------
pending = {}  # user_id -> partner_id (ожидающие подтверждения)

@router.message(CommandStart())
async def start(msg: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="💗 Открыть Heartbeat",
            web_app=WebAppInfo(url=WEBAPP_URL)
        )],
        [InlineKeyboardButton(text="🔗 Связаться с партнёром", callback_data="link")]
    ])
    await msg.answer(
        "Привет! Это Heartbeat 💓\n\n"
        "Нажми кнопку ниже, чтобы отправить сигнал любимому человеку — "
        "его телефон завибрирует, где бы он ни был.",
        reply_markup=kb
    )

@router.callback_query(F.data == "link")
async def link_cmd(cb):
    await cb.message.answer(
        f"Отправь эту ссылку партнёру:\n"
        f"https://t.me/{(await bot.get_me()).username}?start=pair_{cb.from_user.id}"
    )

@router.message(F.text.regexp(r"^/start pair_(\d+)$"))
async def pair_start(msg: Message):
    partner_id = int(msg.text.split("_")[1])
    pending[msg.from_user.id] = partner_id
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, связать нас", callback_data="confirm_pair")]
    ])
    await msg.answer(
        f"Пользователь {partner_id} хочет связаться с тобой в Heartbeat. Согласен?",
        reply_markup=kb
    )

@router.callback_query(F.data == "confirm_pair")
async def confirm_pair(cb):
    a = cb.from_user.id
    b = pending.get(a)
    if not b:
        return await cb.answer("Ссылка устарела", show_alert=True)
    set_pair(a, b, cb.from_user.username, "")
    del pending[a]
    await cb.message.answer("💞 Вы связаны! Теперь нажимайте «Скучаю» в приложении.")
    await bot.send_message(b, "💞 Ваш партнёр принял связь. Откройте Heartbeat!")

# ---------- Приём сигнала из Mini App ----------
@router.message(F.web_app_data)
async def webapp_data(msg: Message):
    if msg.web_app_data.data == "miss_you":
        partner = get_partner(msg.from_user.id)
        if not partner:
            return await msg.answer("Сначала свяжитесь с партнёром через кнопку 🔗")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="💓 Открыть сердце",
                web_app=WebAppInfo(url=WEBAPP_URL + "?beat=1")
            )]
        ])
        await bot.send_message(
            partner,
            f"💗 *Ваш любимый человек скучает по вам!*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb
        )
        await msg.answer("✅ Сигнал отправлен!")

if __name__ == "__main__":
    asyncio.run(dp.start_polling(bot))
