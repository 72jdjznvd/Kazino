import asyncio
import logging
import os
import random
import secrets
import string
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import asyncpg
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from fastapi import FastAPI
import uvicorn

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "ACE_SUPORT").strip().lstrip("@")
START_BALANCE = 1000
MIN_BET = 10
MAX_BET = 5000

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ace-prive")

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML)) if BOT_TOKEN else None
dp = Dispatcher()
app = FastAPI(title="ACE PRIVÉ Demo Bot", docs_url=None, redoc_url=None)
pool: asyncpg.Pool | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,
    username TEXT,
    full_name TEXT NOT NULL DEFAULT '',
    balance BIGINT NOT NULL DEFAULT 1000,
    joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_daily TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS requests (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('demo_deposit','demo_withdraw')),
    amount BIGINT NOT NULL CHECK (amount > 0),
    note TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    handled_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS promo_uses (
    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    used_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY(user_id, code)
);
CREATE TABLE IF NOT EXISTS game_log (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    game TEXT NOT NULL,
    bet BIGINT NOT NULL,
    multiplier NUMERIC(8,2) NOT NULL,
    payout BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

async def db() -> asyncpg.Pool:
    if pool is None:
        raise RuntimeError("Database pool not initialized")
    return pool

async def ensure_user(tg_user) -> None:
    p = await db()
    name = (tg_user.full_name or "")[:200]
    username = (tg_user.username or "")[:100]
    await p.execute(
        """INSERT INTO users(user_id, username, full_name, balance) VALUES($1,$2,$3,$4)
        ON CONFLICT(user_id) DO UPDATE SET username=EXCLUDED.username, full_name=EXCLUDED.full_name""",
        tg_user.id, username, name, START_BALANCE
    )

async def user_row(user_id: int):
    p = await db()
    return await p.fetchrow("SELECT * FROM users WHERE user_id=$1", user_id)

async def change_balance(user_id: int, delta: int) -> int:
    p = await db()
    async with p.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("SELECT balance FROM users WHERE user_id=$1 FOR UPDATE", user_id)
            if not row:
                raise ValueError("İstifadəçi tapılmadı")
            new_balance = int(row["balance"]) + delta
            if new_balance < 0:
                raise ValueError("Balans kifayət etmir")
            await conn.execute("UPDATE users SET balance=$2 WHERE user_id=$1", user_id, new_balance)
            return new_balance

def kb(rows):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d) for t,d in row] for row in rows])

def main_menu():
    return kb([
        [("🎮 Aviator DEMO", "game:aviator"), ("🎁 Bonus çarxı", "wheel")],
        [("💳 Virtual balans", "balance"), ("🧩 Demo kod", "promo")],
        [("➕ Demo mədaxil", "request:demo_deposit"), ("➖ Demo çıxarış", "request:demo_withdraw")],
        [("📊 Profilim", "profile"), ("🆘 Dəstək", "support")],
    ])

def admin_menu():
    return kb([
        [("📥 Gözləyən sorğular", "admin:requests"), ("👥 İstifadəçilər", "admin:users")],
        [("🏠 Əsas menyu", "home")]
    ])

@dp.message(CommandStart())
async def start(message: Message):
    await ensure_user(message.from_user)
    await message.answer(
        "<b>♠️ ACE PRIVÉ</b>\n<code>PREMIUM DEMO CLUB</code>\n\n"
        "Xoş gəlmisən! Buradakı oyunlar yalnız <b>virtual balansla</b> işləyir. "
        "Real pul, real depozit/çıxarış və real qumar xidməti yoxdur.\n\n"
        "🎁 Başlanğıc balansın: <b>1 000 demo kredit</b>",
        reply_markup=main_menu()
    )

@dp.message(Command("menu"))
async def menu_cmd(message: Message):
    await ensure_user(message.from_user)
    await message.answer("<b>ACE PRIVÉ</b> — əsas menyu", reply_markup=main_menu())

@dp.message(Command("admin"))
async def admin_cmd(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return await message.answer("⛔ Bu bölmə yalnız administrator üçündür.")
    await message.answer("<b>ADMIN PANEL</b>", reply_markup=admin_menu())

@dp.callback_query(F.data == "home")
async def home(call: CallbackQuery):
    await call.message.edit_text("<b>ACE PRIVÉ</b> — əsas menyu", reply_markup=main_menu())
    await call.answer()

@dp.callback_query(F.data == "balance")
async def balance(call: CallbackQuery):
    row = await user_row(call.from_user.id)
    await call.message.answer(f"💳 Virtual balansın: <b>{int(row['balance']):,} demo kredit</b>\n\nBu kreditlərin real pul dəyəri yoxdur.", reply_markup=main_menu())
    await call.answer()

@dp.callback_query(F.data == "profile")
async def profile(call: CallbackQuery):
    row = await user_row(call.from_user.id)
    p = await db()
    games = await p.fetchrow("SELECT COUNT(*) AS n, COALESCE(SUM(payout-bet),0) AS net FROM game_log WHERE user_id=$1", call.from_user.id)
    await call.message.answer(
        f"<b>👤 PROFİL</b>\nAd: {row['full_name'] or '—'}\nUsername: @{row['username'] or 'yoxdur'}\n"
        f"ID: <code>{call.from_user.id}</code>\nBalans: <b>{int(row['balance']):,} demo kredit</b>\n"
        f"Oyun sayı: {games['n']}\nDemo nəticə: {int(games['net']):+,} kredit",
        reply_markup=main_menu()
    )
    await call.answer()

@dp.callback_query(F.data == "support")
async def support(call: CallbackQuery):
    await call.message.answer(f"🆘 Dəstək: @{SUPPORT_USERNAME}\n\nHeç kimə bot tokenini və ya bank məlumatlarını göndərmə.")
    await call.answer()

@dp.callback_query(F.data == "game:aviator")
async def aviator_menu(call: CallbackQuery):
    await call.message.answer(
        "<b>🚀 AVIATOR DEMO</b>\nMərc yalnız virtual kreditlədir. Nəticə təsadüfi simulyasiyadır; real Aviator xidməti deyil.\n\nMərc seç:",
        reply_markup=kb([[("10", "bet:10"),("50", "bet:50"),("100", "bet:100")],[("250", "bet:250"),("500", "bet:500")],[("⬅️ Menyu", "home")]])
    )
    await call.answer()

@dp.callback_query(F.data.startswith("bet:"))
async def play_aviator(call: CallbackQuery):
    bet = int(call.data.split(":",1)[1])
    if bet < MIN_BET or bet > MAX_BET:
        return await call.answer("Mərc limiti uyğun deyil.", show_alert=True)
    try:
        balance_after_bet = await change_balance(call.from_user.id, -bet)
    except ValueError:
        return await call.answer("Virtual balansın kifayət etmir.", show_alert=True)
    # Educational/demo-only simulation. A random crash point is generated and shown transparently.
    crash = round(random.uniform(1.0, 5.0), 2)
    if random.random() < 0.28:
        crash = round(random.uniform(1.0, 1.4), 2)
    if crash >= 2.0:
        multiplier = round(random.uniform(1.05, min(crash, 2.5)), 2)
        payout = int(bet * multiplier)
        await change_balance(call.from_user.id, payout)
        outcome = f"🟢 Demo nəticə: <b>{multiplier:.2f}x</b>\nQayıdan kredit: <b>{payout:,}</b>"
    else:
        multiplier = crash
        payout = 0
        outcome = f"🔴 Demo uçuş {crash:.2f}x-də bitdi. Bu raundda virtual mərc geri qayıtmadı."
    p = await db()
    await p.execute("INSERT INTO game_log(user_id,game,bet,multiplier,payout) VALUES($1,'aviator_demo',$2,$3,$4)", call.from_user.id, bet, Decimal(str(multiplier)), payout)
    row = await user_row(call.from_user.id)
    await call.message.answer(f"<b>🚀 AVIATOR DEMO</b>\nMərc: {bet} kredit\n{outcome}\n\nYeni balans: <b>{int(row['balance']):,} kredit</b>", reply_markup=main_menu())
    await call.answer("Demo raund tamamlandı")

@dp.callback_query(F.data == "wheel")
async def wheel(call: CallbackQuery):
    p = await db()
    today = datetime.now(timezone.utc).date()
    async with p.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("SELECT last_daily,balance FROM users WHERE user_id=$1 FOR UPDATE", call.from_user.id)
            if row["last_daily"] and row["last_daily"].date() == today:
                return await call.answer("Bonus çarxını gündə bir dəfə fırlatmaq olar.", show_alert=True)
            prize = random.choice([25, 50, 75, 100, 150, 200, 300])
            await conn.execute("UPDATE users SET balance=balance+$2,last_daily=NOW() WHERE user_id=$1", call.from_user.id, prize)
    await call.message.answer(f"🎁 Çarx fırlandı! Virtual bonusun: <b>+{prize} demo kredit</b>\nBu bonus gündə bir dəfə verilir.", reply_markup=main_menu())
    await call.answer()

@dp.callback_query(F.data == "promo")
async def promo(call: CallbackQuery):
    # Codes are deliberately branded as local demo codes and have no third-party value.
    code = "ACE-DEMO-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    await call.message.answer(f"🧩 Sənin demo kodun:\n<code>{code}</code>\n\nBu kod yalnız ACE PRIVÉ demo ekranı üçündür; CHC Play və ya başqa platformada işləmir və real dəyəri yoxdur.")
    await call.answer()

@dp.callback_query(F.data.startswith("request:"))
async def request_menu(call: CallbackQuery):
    kind = call.data.split(":",1)[1]
    if kind not in ("demo_deposit", "demo_withdraw"):
        return await call.answer()
    await call.message.answer(
        ("➕ <b>Demo mədaxil sorğusu</b>" if kind == "demo_deposit" else "➖ <b>Demo çıxarış sorğusu</b>") +
        "\nMəbləği mesaj kimi göndər: 100, 250 və ya 500.\n\nBu, yalnız demo sorğusudur — kart, bank və ya kripto ödənişi edilmir.",
        reply_markup=kb([[("Ləğv et", "home")]])
    )
    await call.answer()
    # Per-user next action is stored in memory; persistent financial operations are intentionally disabled.
    pending_amount_action[call.from_user.id] = kind

pending_amount_action: dict[int, str] = {}

@dp.message(F.text.regexp(r"^\d{1,7}$"))
async def amount_message(message: Message):
    kind = pending_amount_action.pop(message.from_user.id, None)
    if not kind:
        return
    amount = int(message.text)
    if amount < 10 or amount > 100000:
        pending_amount_action[message.from_user.id] = kind
        return await message.answer("Məbləğ 10–100000 aralığında olmalıdır. Yenidən göndər.")
    p = await db()
    rec = await p.fetchrow("INSERT INTO requests(user_id,kind,amount,note) VALUES($1,$2,$3,$4) RETURNING id", message.from_user.id, kind, amount, "DEMO ONLY")
    await message.answer(f"✅ Demo sorğu yaradıldı: <b>#{rec['id']}</b>\nMəbləğ: {amount:,} demo kredit\nReal pul hərəkəti yoxdur.", reply_markup=main_menu())
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, f"<b>Yeni demo sorğu #{rec['id']}</b>\nNöv: {kind}\nİstifadəçi: <code>{message.from_user.id}</code>\nMəbləğ: {amount} demo kredit", reply_markup=kb([[("Təsdiqlə", f"admin:approve:{rec['id']}"),("Rədd et", f"admin:reject:{rec['id']}")]]))
        except Exception:
            log.exception("Admin notification failed")

@dp.callback_query(F.data == "admin:requests")
async def admin_requests(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return await call.answer("İcazə yoxdur", show_alert=True)
    p = await db()
    rows = await p.fetch("SELECT id,user_id,kind,amount,created_at FROM requests WHERE status='pending' ORDER BY id DESC LIMIT 10")
    if not rows:
        await call.message.answer("Gözləyən demo sorğu yoxdur.")
    for r in rows:
        await call.message.answer(f"Sorğu #{r['id']} | {r['kind']} | {r['amount']} demo kredit | user <code>{r['user_id']}</code>", reply_markup=kb([[("Təsdiqlə", f"admin:approve:{r['id']}"),("Rədd et", f"admin:reject:{r['id']}")]]))
    await call.answer()

@dp.callback_query(F.data == "admin:users")
async def admin_users(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return await call.answer("İcazə yoxdur", show_alert=True)
    p = await db()
    rows = await p.fetch("SELECT user_id,username,full_name,balance FROM users ORDER BY joined_at DESC LIMIT 20")
    if not rows:
        return await call.answer("İstifadəçi yoxdur", show_alert=True)
    text = "<b>Son 20 istifadəçi</b>\n\n" + "\n".join(f"<code>{r['user_id']}</code> @{r['username'] or '—'} · {r['balance']} kredit" for r in rows)
    await call.message.answer(text)
    await call.answer()

@dp.callback_query(F.data.regexp(r"^admin:(approve|reject):\d+$"))
async def admin_handle_request(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        return await call.answer("İcazə yoxdur", show_alert=True)
    _, action, request_id_text = call.data.split(":")
    request_id = int(request_id_text)
    status = "approved" if action == "approve" else "rejected"
    p = await db()
    async with p.acquire() as conn:
        async with conn.transaction():
            r = await conn.fetchrow("SELECT * FROM requests WHERE id=$1 FOR UPDATE", request_id)
            if not r:
                return await call.answer("Sorğu tapılmadı", show_alert=True)
            if r["status"] != "pending":
                return await call.answer("Sorğu artıq işlənib", show_alert=True)
            # Approvals only update demo-request status; they never move real money.
            await conn.execute("UPDATE requests SET status=$2,handled_at=NOW() WHERE id=$1", request_id, status)
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(f"Sorğu #{request_id}: {status}. Yalnız demo statusu dəyişdirildi; heç bir pul köçürülmədi.")
    try:
        await bot.send_message(r["user_id"], f"Demo sorğun #{request_id} statusu: <b>{status}</b>. Real ödəniş həyata keçirilməyib.")
    except Exception:
        pass
    await call.answer("Hazırdır")

@app.get("/")
async def health():
    return {"service": "ACE PRIVÉ Demo Bot", "status": "ok", "mode": "virtual-credit-only"}

@app.get("/health")
async def health_check():
    return {"status": "ok"}

async def run_web():
    config = uvicorn.Config(app, host="0.0.0.0", port=int(os.getenv("PORT", "10000")), log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

async def main():
    global pool
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN mühiti dəyişəni təyin edilməyib")
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL təyin edilməyib. Render PostgreSQL bağlantısını əlavə et.")
    db_url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=5, command_timeout=30, ssl="require" if "render.com" in db_url else None)
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA)
    log.info("ACE PRIVÉ demo bot started")
    await asyncio.gather(dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types()), run_web())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
