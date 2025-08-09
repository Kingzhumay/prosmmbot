# bot.py
# Copy-paste ready. YOUR TOKEN & OWNER_ID are already filled in below.
import os
import sqlite3
import logging
import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ----------------- CONFIG (already filled by you) -----------------
BOT_TOKEN = "7886209014:AAFYGnTf0T41y72z5h-DTJcNQQj-mYW4mdo"   # your token (you provided)
VIP_API_KEY = "2b0d769f994484804721e0488ea7fbf8"             # your panel API key (you provided earlier)
OWNER_ID = 883754833                                         # your numeric telegram id (you provided)
QR_URL = ""                                                  # optional: paste direct link to QR image (postimg/imgbb)
UPI_ID = "arshjunaid@slc"
SERVICE_VIEWS = "10837"
SERVICE_REACTIONS = "11244"
SERVICE_MEMBERS = "10776"
REQUIRED_CHANNELS = ["@trickyhubv2", "@primate004"]
DB_PATH = "bot.db"
# -----------------------------------------------------------------

# DB init
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cur = conn.cursor()
cur.execute("""CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    balance REAL DEFAULT 0
)""")
cur.execute("""CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    service TEXT,
    link TEXT,
    qty INTEGER,
    cost REAL,
    order_id TEXT,
    status TEXT DEFAULT 'pending',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)""")
conn.commit()

# Helpers
def ensure_user(uid, username=None):
    cur.execute("SELECT user_id FROM users WHERE user_id=?", (uid,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (user_id, username) VALUES (?,?)", (uid, username))
        conn.commit()

def get_balance(uid):
    cur.execute("SELECT balance FROM users WHERE user_id=?", (uid,))
    r = cur.fetchone()
    return float(r[0]) if r else 0.0

def update_balance(uid, amount):
    cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, uid))
    conn.commit()

def place_smm(service_id, link, qty):
    url = "https://vipprosmm.com/api/v2"
    data = {"key": VIP_API_KEY, "action": "add", "service": str(service_id), "link": link, "quantity": str(qty)}
    try:
        r = requests.post(url, data=data, timeout=25)
        return r.json()
    except Exception as e:
        logger.exception("SMM API error")
        return {"error": str(e)}

# Handlers
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id, user.username)
    text = "🔐 Welcome! Please join these channels to unlock the bot:\n\n"
    for ch in REQUIRED_CHANNELS:
        text += f"➡️ {ch}\n"
    kb = [
        [InlineKeyboardButton("✅ I’ve Joined", callback_data="verify_join")],
        [InlineKeyboardButton("🔁 Refresh", callback_data="verify_join")]
    ]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb))

async def verify_join_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id

    for ch in REQUIRED_CHANNELS:
        try:
            member = await context.bot.get_chat_member(chat_id=ch, user_id=uid)
            if member.status not in ("member", "administrator", "creator"):
                await query.edit_message_text("❌ You must join all required channels to continue.")
                return
        except Exception:
            await query.edit_message_text("❌ Could not verify join status. Ensure channels are public or add bot as admin.")
            return

    menu = [
        [InlineKeyboardButton("💰 Add Funds", callback_data="add_funds")],
        [InlineKeyboardButton("📈 Post Views", callback_data="buy_views"),
         InlineKeyboardButton("❤️ Reactions", callback_data="buy_reactions")],
        [InlineKeyboardButton("👥 Members", callback_data="buy_members")],
        [InlineKeyboardButton("💳 My Balance", callback_data="my_balance"),
         InlineKeyboardButton("📦 My Orders", callback_data="my_orders")]
    ]
    await query.edit_message_text("🎉 Access Granted! Choose:", reply_markup=InlineKeyboardMarkup(menu))

# Add funds
async def add_funds_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = f"💸 Send payment to UPI: `{UPI_ID}`\nAfter payment, reply here with Transaction ID (UTR) + screenshot. Admin will verify and credit your wallet."
    if QR_URL:
        await query.message.reply_photo(photo=QR_URL, caption=text, parse_mode="Markdown")
    else:
        await query.message.reply_text(text, parse_mode="Markdown")

async def payments_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user = update.effective_user
    if len(text) >= 6:
        await update.message.reply_text("✅ Payment claim received. Admin will verify and credit your wallet after confirmation.")
        try:
            await context.bot.send_message(chat_id=OWNER_ID,
                text=f"🔔 Payment claim\nUser: @{user.username} ({user.id})\nClaim: {text}\nVerify & use /addbalance <user_id> <amount>")
        except Exception:
            logger.exception("Failed to notify owner")
    else:
        await update.message.reply_text("Send a valid UTR/Transaction ID or a public post link.")

# Buy flows
async def buy_views_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("Send your public Telegram post link (e.g. https://t.me/channel/123):")
    context.user_data["flow"] = "views_wait_link"

async def buy_reactions_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("Send your public Telegram post link for reactions:")
    context.user_data["flow"] = "reactions_wait_link"

async def buy_members_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("Send target channel/group link where members will be added:")
    context.user_data["flow"] = "members_wait_link"

# Text handler (link/qty/payment)
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    ensure_user(uid, user.username)
    flow = context.user_data.get("flow", "")
    text = update.message.text.strip()

    if flow in ("views_wait_link", "reactions_wait_link", "members_wait_link"):
        context.user_data["pending_link"] = text
        kb = [
            [InlineKeyboardButton("✅ 100% Done", callback_data="link_confirmed")],
            [InlineKeyboardButton("🔁 I want to change or correct my link", callback_data="change_link")]
        ]
        await update.message.reply_text(f"Link received:\n`{text}`\nIs this 100% correct?", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return

    if flow in ("views_wait_qty", "reactions_wait_qty", "members_wait_qty"):
        if not text.isdigit():
            await update.message.reply_text("Please enter numeric quantity (like 1000).")
            return
        qty = int(text)
        link = context.user_data.get("pending_link")
        if not link:
            await update.message.reply_text("No link found. Start order again.")
            return

        # cost calculation
        if flow == "views_wait_qty":
            unit_cost = 0.000657
            svc = SERVICE_VIEWS
            svc_name = "Post Views"
        elif flow == "reactions_wait_qty":
            unit_cost = 0.01577
            svc = SERVICE_REACTIONS
            svc_name = "Reactions"
        else:
            unit_cost = 0.01296
            svc = SERVICE_MEMBERS
            svc_name = "Members"

        cost = qty * unit_cost
        bal = get_balance(uid)
        if bal < cost:
            await update.message.reply_text(f"❌ Insufficient balance. Required ₹{cost:.2f}, Your balance: ₹{bal:.2f}")
            return

        resp = place_smm(svc, link, qty)
        if resp and resp.get("order"):
            order_id = str(resp["order"])
            cur.execute("INSERT INTO orders (user_id, service, link, qty, cost, order_id, status) VALUES (?,?,?,?,?,?,?)",
                        (uid, svc_name, link, qty, cost, order_id, "processing"))
            cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (cost, uid))
            conn.commit()
            await update.message.reply_text(f"✅ Order placed!\nService: {svc_name}\nQty: {qty}\nOrder ID: {order_id}\nDeducted: ₹{cost:.2f}")
            try:
                await context.bot.send_message(chat_id=OWNER_ID, text=f"🆕 Order placed by @{user.username} ({uid})\n{svc_name} | {qty} | id:{order_id}")
            except Exception:
                pass
        else:
            await update.message.reply_text("❌ Failed to place order with panel. Try later.")
        context.user_data.pop("flow", None)
        context.user_data.pop("pending_link", None)
        return

    # fallback -> treat as payment claim
    await payments_handler(update, context)

# link callbacks
async def link_confirmed_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    flow = context.user_data.get("flow", "")
    if "views" in flow:
        context.user_data["flow"] = "views_wait_qty"
    elif "reactions" in flow:
        context.user_data["flow"] = "reactions_wait_qty"
    elif "members" in flow:
        context.user_data["flow"] = "members_wait_qty"
    else:
        context.user_data["flow"] = "views_wait_qty"
    await update.callback_query.message.reply_text("Now enter the quantity (number):")

async def change_link_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    prev = context.user_data.get("flow","")
    if "views" in prev:
        context.user_data["flow"] = "views_wait_link"
    elif "reactions" in prev:
        context.user_data["flow"] = "reactions_wait_link"
    elif "members" in prev:
        context.user_data["flow"] = "members_wait_link"
    else:
        context.user_data["flow"] = "views_wait_link"
    await update.callback_query.message.reply_text("Send the corrected link now:")

# balance & orders
async def my_balance_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    uid = update.callback_query.from_user.id
    bal = get_balance(uid)
    await update.callback_query.message.reply_text(f"💳 Your balance: ₹{bal:.2f}")

async def my_orders_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    uid = update.callback_query.from_user.id
    cur.execute("SELECT service, qty, cost, status, order_id, created_at FROM orders WHERE user_id=? ORDER BY created_at DESC LIMIT 20", (uid,))
    rows = cur.fetchall()
    if not rows:
        await update.callback_query.message.reply_text("You have no orders yet.")
        return
    text = ""
    for s, q, cost, st, oid, created in rows:
        text += f"{s} | {q} | ₹{cost:.2f} | {st} | id:{oid}\n\n"
    await update.callback_query.message.reply_text(text)

# admin
async def cmd_addbalance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("Unauthorized.")
        return
    try:
        parts = context.args
        if len(parts) != 2:
            await update.message.reply_text("Usage: /addbalance <user_id> <amount>")
            return
        uid = int(parts[0]); amt = float(parts[1])
        update_balance(uid, amt)
        await update.message.reply_text(f"Added ₹{amt:.2f} to {uid}")
        await context.bot.send_message(chat_id=uid, text=f"✅ Admin added ₹{amt:.2f} to your balance.")
    except Exception as e:
        await update.message.reply_text("Error: " + str(e))

async def cmd_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("Unauthorized.")
        return
    cur.execute("SELECT user_id, username, balance FROM users ORDER BY balance DESC LIMIT 200")
    rows = cur.fetchall()
    msg = "Users:\n" + "\n".join(f"{u} | @{un} | ₹{b:.2f}" for u,un,b in rows)
    await update.message.reply_text(msg)

async def cmd_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("Unauthorized.")
        return
    cur.execute("SELECT id, user_id, service, qty, cost, status, order_id FROM orders ORDER BY created_at DESC LIMIT 200")
    rows = cur.fetchall()
    msg = "Orders:\n"
    for r in rows:
        msg += "|".join(str(x) for x in r) + "\n"
    await update.message.reply_text(msg)

# App startup
def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN missing.")
        return
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CallbackQueryHandler(verify_join_cb, pattern="^verify_join$"))
    app.add_handler(CallbackQueryHandler(add_funds_cb, pattern="^add_funds$"))
    app.add_handler(CallbackQueryHandler(buy_views_cb, pattern="^buy_views$"))
    app.add_handler(CallbackQueryHandler(buy_reactions_cb, pattern="^buy_reactions$"))
    app.add_handler(CallbackQueryHandler(buy_members_cb, pattern="^buy_members$"))
    app.add_handler(CallbackQueryHandler(link_confirmed_cb, pattern="^link_confirmed$"))
    app.add_handler(CallbackQueryHandler(change_link_cb, pattern="^change_link$"))
    app.add_handler(CallbackQueryHandler(my_balance_cb, pattern="^my_balance$"))
    app.add_handler(CallbackQueryHandler(my_orders_cb, pattern="^my_orders$"))

    app.add_handler(CommandHandler("addbalance", cmd_addbalance))
    app.add_handler(CommandHandler("users", cmd_users))
    app.add_handler(CommandHandler("orders", cmd_orders))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.Regex(r"^[A-Za-z0-9\-_]{6,}$") & ~filters.COMMAND, payments_handler))

    logger.info("Bot starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
