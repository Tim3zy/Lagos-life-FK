import asyncio
import threading
import time
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, CallbackQueryHandler, ConversationHandler,
)
from config   import BOT_TOKEN
from exploit  import LagosLifeExploit

# Conversation states
ASK_USER, ASK_PASS, ASK_AMOUNT = range(3)

# Per-chat sessions  {chat_id: {"exploit": ..., "target": int}}
sessions: dict[int, dict] = {}


# ── /start ────────────────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("🔐 Login to Lagos Life", callback_data="login")]]
    await update.message.reply_text(
        "🏙 *Lagos Life Inject Tool*\n\n"
        "Verified. Confirmed working.\n"
        "Tap Login to begin.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb),
    )


# ── login flow ────────────────────────────────────────────────────────────────

async def cb_login(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "Enter your *Lagos Life username*:", parse_mode="Markdown"
    )
    return ASK_USER


async def got_username(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["ll_user"] = update.message.text.strip()
    await update.message.reply_text("Now enter your *password*:", parse_mode="Markdown")
    return ASK_PASS


async def got_password(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid  = update.effective_chat.id
    user = ctx.user_data.get("ll_user", "")
    pw   = update.message.text.strip()

    msg  = await update.message.reply_text("⏳ Logging in...")

    exploit = LagosLifeExploit()
    result  = await asyncio.to_thread(exploit.login, user, pw)

    if not result["success"]:
        await msg.edit_text(
            f"❌ Login failed: `{result.get('error', 'unknown')}`",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    # Get balance
    state   = await asyncio.to_thread(exploit.get_state)
    balance = state["game"].get("money", 0) if state["success"] else 0

    sessions[cid] = {"exploit": exploit, "target": 0}

    kb = [[
        InlineKeyboardButton("💉 Set Amount & Inject", callback_data="setamount"),
        InlineKeyboardButton("💰 Check Balance",       callback_data="balance"),
    ]]
    await msg.edit_text(
        f"✅ *Logged in!*\n\n"
        f"Current balance: `₦{balance:,}`\n\n"
        f"Choose action 👇",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb),
    )
    return ConversationHandler.END


# ── balance check ─────────────────────────────────────────────────────────────

async def cb_balance(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    cid = update.effective_chat.id

    if cid not in sessions:
        await update.callback_query.message.reply_text("Not logged in. Use /start.")
        return

    exploit = sessions[cid]["exploit"]
    state   = await asyncio.to_thread(exploit.get_state)
    balance = state["game"].get("money", "unknown") if state["success"] else "error"

    kb = [[InlineKeyboardButton("💉 Inject", callback_data="setamount")]]
    await update.callback_query.message.reply_text(
        f"💰 Balance: `₦{balance:,}`" if isinstance(balance, int) else f"💰 Balance: `{balance}`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb),
    )


# ── set amount flow ───────────────────────────────────────────────────────────

async def cb_setamount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    cid = update.effective_chat.id

    if cid not in sessions:
        await update.callback_query.message.reply_text("Not logged in. Use /start.")
        return ConversationHandler.END

    await update.callback_query.message.reply_text(
        "Enter target balance (e.g. `5000000000` for 5B):",
        parse_mode="Markdown",
    )
    return ASK_AMOUNT


async def got_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    try:
        amount = int(
            update.message.text.strip()
            .replace(",", "")
            .replace("₦", "")
            .replace(" ", "")
        )
    except ValueError:
        await update.message.reply_text("❌ Invalid number. Try again — /start")
        return ConversationHandler.END

    sessions[cid]["target"] = amount

    kb = [[
        InlineKeyboardButton("🚀 START INJECT", callback_data="inject"),
        InlineKeyboardButton("❌ Cancel",        callback_data="cancel"),
    ]]
    await update.message.reply_text(
        f"🎯 *Target set:* `₦{amount:,}`\n\n"
        f"Strategy:\n"
        f"• Starts at 50M per cycle\n"
        f"• Doubles every 3 confirmed writes\n"
        f"• 409? Auto re-sync + halve chunk\n"
        f"• Server timestamp chained (no wasted GETs)\n\n"
        f"Hit *START INJECT* 🚀",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb),
    )
    return ConversationHandler.END


# ── inject ────────────────────────────────────────────────────────────────────

async def cb_inject(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    cid = update.effective_chat.id

    if cid not in sessions:
        await update.callback_query.message.reply_text("Not logged in.")
        return

    exploit = sessions[cid]["exploit"]
    target  = sessions[cid]["target"]

    msg = await update.callback_query.message.reply_text(
        f"💉 *Injection starting...*\nTarget: `₦{target:,}`",
        parse_mode="Markdown",
    )

    # Shared progress state (written from thread, read by loop)
    prog = {
        "cycle"    : 0,
        "success"  : 0,
        "injected" : 0,
        "balance"  : 0,
        "status"   : "STARTING",
        "last_edit": 0.0,
        "dirty"    : False,
    }
    prog_lock = threading.Lock()
    loop      = asyncio.get_event_loop()

    def on_progress(cycle, success_count, injected, balance, status):
        with prog_lock:
            prog.update({
                "cycle"   : cycle,
                "success" : success_count,
                "injected": injected,
                "balance" : balance,
                "status"  : status,
                "dirty"   : True,
            })

    # Background task — throttled Telegram edits
    update_task_done = asyncio.Event()

    async def update_ticker():
        while True:
            await asyncio.sleep(2.5)
            with prog_lock:
                if not prog["dirty"]:
                    continue
                c  = prog["cycle"]
                sc = prog["success"]
                inj = prog["injected"]
                bal = prog["balance"]
                st  = prog["status"]
                prog["dirty"] = False

            bar_pct = min(int(inj / target * 100), 100) if target else 0
            filled  = bar_pct // 10
            bar     = "█" * filled + "░" * (10 - filled)

            text = (
                f"💉 *Injecting...*\n\n"
                f"`Cycle   :` `{c}`\n"
                f"`Success :` `{sc}`\n"
                f"`Injected:` `₦{inj:,}`\n"
                f"`Balance :` `₦{bal:,}`\n"
                f"`Target  :` `₦{target:,}`\n"
                f"`Status  :` `{st}`\n\n"
                f"`{bar}` {bar_pct}%"
            )
            kb = [[InlineKeyboardButton("🛑 STOP", callback_data="stop_inject")]]
            try:
                await msg.edit_text(
                    text,
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(kb),
                )
            except Exception:
                pass

            if update_task_done.is_set():
                break

    ticker = asyncio.ensure_future(update_ticker())

    def run_inject():
        result = exploit.inject(target, progress_cb=on_progress)

        done    = result.get("done", False)
        stopped = result.get("stopped", False)
        fin_bal = result.get("final_balance", 0)
        inj     = result.get("injected", 0)
        cycles  = result.get("cycles", 0)

        icon = "✅" if done else ("⏹" if stopped else "⚠️")
        word = "Complete!" if done else ("Stopped." if stopped else "Ended early.")

        kb = [[
            InlineKeyboardButton("🔄 Inject Again", callback_data="setamount"),
            InlineKeyboardButton("💰 Balance",       callback_data="balance"),
        ]]

        asyncio.run_coroutine_threadsafe(update_task_done.set(), loop)
        asyncio.run_coroutine_threadsafe(
            msg.edit_text(
                f"{icon} *{word}*\n\n"
                f"Final balance: `₦{fin_bal:,}`\n"
                f"Injected:      `₦{inj:,}`\n"
                f"Cycles:        `{cycles}`",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb),
            ),
            loop,
        )

    threading.Thread(target=run_inject, daemon=True).start()


# ── stop ──────────────────────────────────────────────────────────────────────

async def cb_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer("Stopping...")
    cid = update.effective_chat.id
    if cid in sessions:
        sessions[cid]["exploit"].stop()
    await update.callback_query.message.reply_text(
        "🛑 Stop signal sent. Finishing current cycle..."
    )


async def cb_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("Cancelled.")
    return ConversationHandler.END


# ── /debug command ───────────────────────────────────────────────────────────

async def cmd_debug(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    if cid not in sessions:
        await update.message.reply_text("Not logged in. /start first.")
        return

    exploit = sessions[cid]["exploit"]
    msg     = await update.message.reply_text("🔍 Running debug test PUT...")

    # Step 1: get state
    state = await asyncio.to_thread(exploit.get_state)
    if not state["success"]:
        await msg.edit_text(f"❌ GET /api/save failed: `{state}`", parse_mode="Markdown")
        return

    game       = state["game"]
    updated_at = state["updatedAt"]
    balance    = game.get("money", 0)

    # Step 2: fire one raw PUT with +100 and capture full response
    import copy as _copy
    import json  as _json

    test_game = _copy.deepcopy(game)
    test_game["money"] = balance + 100
    stats = test_game.get("stats", {})
    for k in ("earnedToday", "earnedTotal"):
        if k in stats:
            stats[k] = (stats.get(k) or 0) + 100
    test_game["stats"] = stats

    payload = {"game": test_game, "base": updated_at, "build": "prod"}

    def raw_put():
        try:
            r = exploit.session.put(
                f"{exploit.session.base_url if hasattr(exploit.session,'base_url') else 'https://lagoslife.app'}/api/save",
                json=payload,
                timeout=15,
            )
            return {
                "status"  : r.status_code,
                "headers" : dict(r.headers),
                "body"    : r.text[:800],
            }
        except Exception as e:
            return {"error": str(e)}

    # need BASE_URL in scope
    from config import BASE_URL as _BASE
    def raw_put2():
        try:
            r = exploit.session.put(f"{_BASE}/api/save", json=payload, timeout=15)
            return {
                "status"  : r.status_code,
                "headers" : dict(r.headers),
                "body"    : r.text[:800],
            }
        except Exception as e:
            return {"error": str(e)}

    result = await asyncio.to_thread(raw_put2)

    status  = result.get("status", "ERR")
    body    = result.get("body",   result.get("error", "no body"))
    cf_ray  = result.get("headers", {}).get("cf-ray", "none")
    cf_cache= result.get("headers", {}).get("cf-cache-status", "none")
    server  = result.get("headers", {}).get("server", "none")

    report = (
        f"🔍 *Debug PUT Result*\n\n"
        f"GET balance: `₦{balance:,}`\n"
        f"updatedAt:   `{updated_at}`\n\n"
        f"PUT status:  `{status}`\n"
        f"CF-Ray:      `{cf_ray}`\n"
        f"CF-Cache:    `{cf_cache}`\n"
        f"Server:      `{server}`\n\n"
        f"Body:\n`{body[:600]}`"
    )
    await msg.edit_text(report, parse_mode="Markdown")


# ── health check server (for UptimeRobot + Render) ───────────────────────────

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass  # silence access logs


def start_health_server():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"Health check running on port {port}")
    server.serve_forever()


# ── wiring ────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    login_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_login, pattern="^login$")],
        states={
            ASK_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_username)],
            ASK_PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_password)],
        },
        fallbacks=[],
        per_chat=True,
    )

    amount_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_setamount, pattern="^setamount$")],
        states={
            ASK_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_amount)],
        },
        fallbacks=[],
        per_chat=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("debug", cmd_debug))
    app.add_handler(login_conv)
    app.add_handler(amount_conv)
    app.add_handler(CallbackQueryHandler(cb_balance,   pattern="^balance$"))
    app.add_handler(CallbackQueryHandler(cb_inject,    pattern="^inject$"))
    app.add_handler(CallbackQueryHandler(cb_stop,      pattern="^stop_inject$"))
    app.add_handler(CallbackQueryHandler(cb_cancel,    pattern="^cancel$"))

    # Start health check server in background (for Render + UptimeRobot)
    threading.Thread(target=start_health_server, daemon=True).start()

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
