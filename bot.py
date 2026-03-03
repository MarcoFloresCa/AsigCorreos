import os
import json
from datetime import datetime
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
import asyncio

TOKEN = os.getenv('TELEGRAM_TOKEN')
USER_SHEET_ID = os.getenv('USER_SHEET_ID', '1K83W6MgOCMrYsN-dzJjek_lHZxhwT02_um27tmUCbWs')

async def start(update, context):
    await update.message.reply_text("🤖 Bot de AsigCorreos activo!\n\nUsa /pendientes para ver pendientes\n/ayuda para ver comandos")

async def pendientes(update, context):
    await update.message.reply_text("📋 Para ver pendientes, ejecuta el script principal: python src/main.py")

async def ayuda(update, context):
    help_text = """
📚 Comandos disponibles:

/start - Iniciar bot
/pendientes - Ver pendientes (ejecutar script)
/ayuda - Mostrar ayuda
    """
    await update.message.reply_text(help_text)

async def handle_callback(update, context):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    subject = "Pendiente"
    
    if data.startswith("resolve_"):
        email_id = data.replace("resolve_", "")
        subject = f"Pendiente {email_id}"
        
        try:
            import gspread
            gc = gspread.service_account(filename='service_account.json')
            sh = gc.open_by_key(USER_SHEET_ID)
            ws = sh.sheet1
            
            cells = ws.findall(subject)
            if cells:
                ws.update_cell(cells[0].row, 4, 'Resuelto')
            
            await query.edit_message_text(f"✅ Marcado como resuelto:\n{subject}")
        except Exception as e:
            await query.edit_message_text(f"✅ Resuelto: {subject}")
    
    elif data.startswith("note_"):
        email_id = data.replace("note_", "")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"📝 Escribe la nota para:\n{subject}"
        )

async def handle_message(update, context):
    text = update.message.text
    
    if "listo" in text.lower() or "resuelto" in text.lower():
        await update.message.reply_text("✅ Para marcar como resuelto, usa el botón en el mensaje del pendientes")
    else:
        await update.message.reply_text("💡 Usa /pendientes para ver los correos pendientes")

def main():
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("pendientes", pendientes))
    app.add_handler(CommandHandler("ayuda", ayuda))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("🤖 Bot iniciado en modo webhook...")
    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.getenv("PORT", 8080)),
        url_path=TOKEN,
        webhook_url=os.getenv("WEBHOOK_URL", "")
    )

if __name__ == '__main__':
    main()
