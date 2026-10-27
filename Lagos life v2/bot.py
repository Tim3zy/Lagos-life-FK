import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler, CallbackQueryHandler
from config import BOT_TOKEN
from exploit import LagosLifeNuke

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# States for conversation
USERNAME, PASSWORD, AMOUNT = range(3)

# Store active sessions
user_sessions = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome message"""
    keyboard = [
        [InlineKeyboardButton("🔐 Login to Lagos Life", callback_data='login')],
        [InlineKeyboardButton("💰 Check Balance", callback_data='balance')],
        [InlineKeyboardButton("💉 Inject Money", callback_data='inject')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🏙 **LAGOS LIFE NUKE v4.0 (Onyx Edition)**\n\n"
        "• TLS Fingerprint Bypass (Cloudflare)\n"
        "• Chunked Injection (No 409 Safe Mode)\n"
        "• Live Progress Tracking\n\n"
        "Select an option:",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button clicks"""
    query = update.callback_query
    await query.answer()
    
    if query.data == 'login':
        await query.message.reply_text(
            "🔐 **Enter your Lagos Life username or email:**",
            parse_mode='Markdown'
        )
        return USERNAME
        
    elif query.data == 'balance':
        user_id = query.from_user.id
        if user_id not in user_sessions:
            await query.message.reply_text("❌ Not logged in! Use /start to login first.")
            return
        await query.message.reply_text("💰 Fetching balance...")
        balance = await asyncio.to_thread(user_sessions[user_id]['api']._extract_balance)
        await query.message.reply_text(f"💰 **Current Balance:** ₦{balance:,}", parse_mode='Markdown')
        return
        
    elif query.data == 'inject':
        user_id = query.from_user.id
        if user_id not in user_sessions:
            await query.message.reply_text("❌ Not logged in! Use /start to login first.")
            return
        await query.message.reply_text(
            "💉 **Enter target amount**\n\n"
            "Examples:\n"
            "• `5000000` (5M)\n"
            "• `5000000000` (5B)\n"
            "• `10000000000` (10B)",
            parse_mode='Markdown'
        )
        return AMOUNT

async def got_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store username and ask for password"""
    context.user_data['username'] = update.message.text.strip()
    await update.message.reply_text(
        "🔑 **Enter password:**",
        parse_mode='Markdown'
    )
    return PASSWORD

async def got_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Attempt login"""
    username = context.user_data.get('username')
    password = update.message.text.strip()
    user_id = update.message.from_user.id
    
    msg = await update.message.reply_text("⏳ **Authenticating (Bypassing CF)...**", parse_mode='Markdown')
    
    # Initialize API and run login in a background thread so the bot doesn't freeze
    api = LagosLifeNuke()
    result = await asyncio.to_thread(api.login, username, password)
    
    if result['success']:
        # Store session
        user_sessions[user_id] = {
            'api': api,
            'username': username
        }
        
        keyboard = [
            [InlineKeyboardButton("💉 Inject Money", callback_data='inject')],
            [InlineKeyboardButton("💰 Check Balance", callback_data='balance')]
        ]
        
        await msg.edit_text(
            f"✅ **Login Successful!**\n\n"
            f"👤 User: `{username}`\n"
            f"💰 Current Balance: **₦{result.get('balance', 0):,}**\n\n"
            f"Ready to inject. Select an option:",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await msg.edit_text(
            f"❌ **Login Failed**\n\n"
            f"Error: `{result.get('error', 'Unknown')}`\n\n"
            f"Try again with /start",
            parse_mode='Markdown'
        )
    return ConversationHandler.END

async def got_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process the injection amount"""
    user_id = update.message.from_user.id
    
    if user_id not in user_sessions:
        await update.message.reply_text("❌ Session expired. Login again with /start")
        return ConversationHandler.END
    
    try:
        amount = int(update.message.text.strip().replace(',', '').replace('₦', ''))
    except ValueError:
        await update.message.reply_text("❌ Invalid amount. Enter numbers only.")
        return AMOUNT
    
    # Confirmation keyboard
    keyboard = [
        [InlineKeyboardButton("🚀 CONFIRM NUKE", callback_data=f'confirm_{amount}')]
    ]
    
    await update.message.reply_text(
        f"🎯 **Target Amount:** ₦{amount:,}\n\n"
        f"Method: Chunked Save Injection\n"
        f"Bypass: TLS Spoofing + Thread-safe async\n\n"
        f"Ready?",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ConversationHandler.END

async def confirm_inject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Execute the nuke"""
    query = update.callback_query
    await query.answer()
    
    amount = int(query.data.split('_')[1])
    user_id = query.from_user.id
    
    if user_id not in user_sessions: 
        await query.message.reply_text("❌ Session expired.")
        return
    
    api = user_sessions[user_id]['api']
    msg = await query.message.reply_text("⚡ **INJECTION STARTED...**\n\n[░░░░░░░░░░] 0%", parse_mode='Markdown')
    
    # Get the current event loop
    loop = asyncio.get_running_loop()

    # Thread-safe progress callback
    def update_progress(current, target, step, total_steps):
        percent = int((step / total_steps) * 100)
        bar = "█" * (percent // 10) + "░" * (10 - (percent // 10))
        
        text = (
            f"⚡ **INJECTING PAYLOAD...**\n\n"
            f"[{bar}] {percent}%\n"
            f"💰 Current: ₦{current:,} / ₦{target:,}"
        )
        
        async def safe_edit():
            try:
                await msg.edit_text(text, parse_mode='Markdown')
            except Exception:
                # Catch 'Message is not modified' or FloodWait errors
                pass

        # Push the edit to the main asyncio loop from the worker thread
        asyncio.run_coroutine_threadsafe(safe_edit(), loop)

    # Execute the heavy injection loop in a thread
    result = await asyncio.to_thread(api.nuke_balance, amount, update_progress)
    
    if result['success']:
        await msg.edit_text(
            f"✅ **INJECTION COMPLETE!**\n\n"
            f"💰 **Final Balance:** ₦{result['new_balance']:,}\n"
            f"Refresh your Lagos Life dashboard baby. We just beat his bot. 6767.",
            parse_mode='Markdown'
        )
    else:
        await msg.edit_text(
            f"❌ **INJECTION FAILED**\n\n"
            f"Error: `{result.get('error')}`\n\n"
            f"The server may have patched this. Try again later.",
            parse_mode='Markdown'
        )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel operation"""
    await update.message.reply_text("❌ Operation cancelled. Type /start to begin again.")
    return ConversationHandler.END

def main():
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Conversation handler for login flow
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern='^(login|balance|inject)$')],
        states={
            USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_username)],
            PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_password)],
            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_amount)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_chat=True,
        per_user=True
    )
    
    # Confirm injection handler
    application.add_handler(CallbackQueryHandler(confirm_inject, pattern='^confirm_'))
    
    # Start handler
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    
    # Run bot
    print("🤖 Lagos Life Nuke v4.0 (Onyx Edition) is live...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()import os
from telegram.ext import Application

# ... your existing code ...

if __name__ == '__main__':
    # For Render.com deployment - keep alive
    PORT = int(os.environ.get('PORT', 5000))

    # If you want webhooks (recommended for Render):
    # application.run_webhook(
    #     listen="0.0.0.0",
    #     port=PORT,
    #     url_path=BOT_TOKEN,
    #     webhook_url=f"https://your-app-name.onrender.com/{BOT_TOKEN}"
    # )

    # Or polling mode (works but needs UptimeRobot):
    application.run_polling()
