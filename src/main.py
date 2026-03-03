import os
import base64
import json
import pickle
from datetime import datetime, timedelta
from google.auth.transport.requests import Request
from google.oauth2.service_account import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes
import asyncio
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/calendar.events.readonly',
    'https://www.googleapis.com/auth/spreadsheets'
]

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

USER_EMAIL = None
SHEET_ID = 'sheet_id.json'

USER_SHEET_ID = '1K83W6MgOCMrYsN-dzJjek_lHZxhwT02_um27tmUCbWs'
PENDING_DATA_FILE = 'pending_data.json'

CATEGORIES = {
    'Requerimiento': ['requerimiento', 'solicitud', 'por favor', 'urgente', 'necesito', 'requiere', 'importante'],
    'Promocion': ['oferta', 'descuento', 'promocion', 'sale', 'gratis', 'cashback'],
    'Informe': ['informe', 'reporte', 'reporte diario', 'resumen', 'dashboard'],
}

pending_messages = {}

def decode_body(data):
    if not data:
        return ''
    try:
        return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
    except:
        return ''

def get_gmail_service():
    global USER_EMAIL
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    
    gmail_service = build('gmail', 'v1', credentials=creds)
    calendar_service = build('calendar', 'v3', credentials=creds)
    
    try:
        profile = gmail_service.users().getProfile(userId='me').execute()
        USER_EMAIL = profile.get('emailAddress', '').lower()
        print(f"   Usuario: {USER_EMAIL}")
    except:
        pass
    
    return gmail_service, calendar_service

def get_sheets_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    
    credentials = service_account.Credentials.from_service_account_file(
        'service_account.json',
        scopes=['https://www.googleapis.com/auth/spreadsheets']
    )
    return build('sheets', 'v4', credentials=credentials)

def get_or_create_sheet():
    import gspread
    
    gc = gspread.service_account(filename='service_account.json')
    
    sheet_id = None
    if os.path.exists(SHEET_ID):
        with open(SHEET_ID, 'r') as f:
            sheet_id = f.read().strip()
    
    if sheet_id:
        try:
            sh = gc.open_by_key(sheet_id)
            return sh
        except:
            sheet_id = None
    
    sh = gc.create('AsigCorreos - Pendientes')
    sheet_id = sh.id
    
    with open(SHEET_ID, 'w') as f:
        f.write(sheet_id)
    
    ws = sh.sheet1
    ws.title = 'Pendientes'
    ws.append_row(['Remitente', 'Asunto', 'Fecha', 'Estado', 'Notas', 'Link', 'Thread ID'])
    
    print(f"   Hoja creada: https://docs.google.com/spreadsheets/d/{sheet_id}")
    
    return sh

def sync_with_sheet(pending_emails):
    import gspread
    
    gc = gspread.service_account(filename='service_account.json')
    
    sheet_id = USER_SHEET_ID
    
    sh = gc.open_by_key(sheet_id)
    ws = sh.sheet1
    
    # Verificar si existen títulos, si no, agregarlos
    try:
        headers = ws.row_values(1)
        if not headers or headers[0] == '':
            ws.append_row(['Remitente', 'Asunto', 'Fecha', 'Estado', 'Notas', 'Link', 'Thread ID'], 1)
    except:
        ws.append_row(['Remitente', 'Asunto', 'Fecha', 'Estado', 'Notas', 'Link', 'Thread ID'], 1)
    
    try:
        existing_data = ws.get_all_records()
    except:
        existing_data = []
    
    existing_subjects = {row.get('Asunto', ''): row for row in existing_data if row.get('Asunto')}
    
    current_subjects = {email['subject']: email for email in pending_emails}
    
    for i, row in enumerate(existing_data, start=2):
        subject = row.get('Asunto', '')
        if subject and subject not in current_subjects:
            ws.update_cell(i, 4, 'Resuelto')
    
    for email in pending_emails:
        subject = email['subject']
        if subject not in existing_subjects:
            date_str = datetime.now().strftime('%Y-%m-%d')
            link = f"https://mail.google.com/mail/u/0/#inbox/{email['id']}"
            ws.append_row([
                extract_sender_name(email['sender']),
                subject,
                date_str,
                'Pendiente',
                '',
                link,
                email.get('thread_id', '')
            ])
    
    return sheet_id

def get_meetings(service):
    try:
        now = datetime.utcnow().isoformat() + 'Z'
        end_of_day = (datetime.utcnow().replace(hour=23, minute=59, second=59)).isoformat() + 'Z'
        
        events = service.events().list(
            calendarId='primary',
            timeMin=now,
            timeMax=end_of_day,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        return events.get('items', [])
    except Exception as e:
        print(f"Error getting meetings: {e}")
        return []

def get_emails(service, days_back=30):
    date_str = (datetime.now() - timedelta(days=days_back)).strftime('%Y/%m/%d')
    query = f'after:{date_str} -from:me'
    print(f"   Query: {query}")
    results = service.users().messages().list(userId='me', q=query, maxResults=100).execute()
    messages = results.get('messages', [])
    
    emails = []
    
    for msg in messages:
        msg_data = service.users().messages().get(userId='me', id=msg['id'], format='full').execute()
        headers = msg_data.get('payload', {}).get('headers', [])
        
        subject = next((h['value'] for h in headers if h['name'] == 'Subject'), '(Sin asunto)')
        sender = next((h['value'] for h in headers if h['name'] == 'From'), 'Desconocido')
        snippet = msg_data.get('snippet', '')
        thread_id = msg_data.get('threadId', '')
        
        body = ''
        parts = msg_data.get('payload', {}).get('parts', [])
        for part in parts:
            if part.get('mimeType') == 'text/plain':
                body = decode_body(part.get('data', ''))
                break
            elif 'parts' in part:
                for subpart in part['parts']:
                    if subpart.get('mimeType') == 'text/plain':
                        body = decode_body(subpart.get('data', ''))
                        break
        
        emails.append({
            'id': msg['id'],
            'thread_id': thread_id,
            'subject': subject,
            'sender': sender,
            'snippet': snippet,
            'body': body,
            'date': msg_data.get('internalDate'),
        })
    
    return emails

def group_by_thread(emails):
    threads = {}
    for email in emails:
        thread_id = email.get('thread_id', '')
        if thread_id not in threads:
            threads[thread_id] = []
        threads[thread_id].append(email)
    
    result = []
    for thread_id, thread_emails in threads.items():
        thread_emails.sort(key=lambda x: int(x.get('date', 0)), reverse=True)
        result.append(thread_emails[0])
    
    return result

def user_answered_thread(service, thread_id):
    if not thread_id or not USER_EMAIL:
        return False
    
    try:
        thread = service.users().threads().get(userId='me', id=thread_id).execute()
        messages = thread.get('messages', [])
        
        for msg in messages:
            headers = msg.get('payload', {}).get('headers', [])
            for header in headers:
                if header['name'].lower() == 'from':
                    from_addr = header['value'].lower()
                    if USER_EMAIL in from_addr:
                        return True
        return False
    except:
        return False

def classify_email(email):
    subject = email['subject'].lower()
    snippet = email['snippet'].lower()
    body = email.get('body', '').lower()
    
    sender = email['sender'].lower()
    
    if 'contego' in sender or 'no-reply@contego' in sender:
        criticos = body.count('critico') + body.count('crítico') + body.count('critica') + body.count('crítica')
        if criticos >= 3:
            return 'Informe Importante'
        else:
            return 'Informe (No importante)'
    
    for category, keywords in CATEGORIES.items():
        for keyword in keywords:
            if keyword.lower() in subject or keyword.lower() in snippet:
                return category
    
    return 'Otro'

def is_pending(service, email):
    subject = email['subject'].lower()
    snippet = email['snippet'].lower()
    sender = email['sender'].lower()
    
    if 'contego' in sender:
        return False
    
    exclude_keywords = ['vacaciones', 'feriados', 'licencia', 'ausencia', 'permiso', 'rh@', 'rrhh@', 'recursos.humanos', 'renovacion', 'renovación', 'notebook', 'aprobado', 'de acuerdo', 'favor proceder', 'correcto', 'ok proceder', 'muchas gracias', 'gracias por']
    if any(kw in subject for kw in exclude_keywords):
        return False
    if any(kw in snippet for kw in exclude_keywords):
        return False
    
    if user_answered_thread(service, email.get('thread_id', '')):
        return False
    
    keywords = ['por favor responder', 'favor responder', 'por favor confirmar', 'awaiting your response', 'please respond', 'pending response', 'necesito respuesta']
    return any(kw in subject or kw in snippet for kw in keywords)

def get_gmail_link(msg_id):
    return f"https://mail.google.com/mail/u/0/#inbox/{msg_id}"

def truncate(text, length=30):
    text = text.replace('\n', ' ').replace('\r', '')
    if len(text) > length:
        return text[:length] + '...'
    return text

def extract_sender_name(sender):
    if '<' in sender:
        return sender.split('<')[0].strip().strip('"')
    return sender.split('@')[0]

async def send_telegram_with_buttons(bot, chat_id, report, meetings, sheet_id):
    pending_emails = report.get('pending', [])
    by_category = report.get('by_category', {})
    
    # Mensaje principal con el formato deseado
    lines = []
    lines.append("📊 RESUMEN DE CORREOS")
    lines.append(f"🕒 {datetime.now().strftime('%d/%m/%Y - %H:%M')}")
    lines.append("")
    lines.append(f"📬 Total correos: {report.get('total', 0)}")
    lines.append(f"📬 Pendientes: {len(pending_emails)}")
    lines.append("")
    lines.append("📂 Categorías:")
    for cat in ['Requerimiento', 'Informe Importante', 'Informe (No importante)', 'Promocion', 'Otro']:
        count = len(by_category.get(cat, []))
        if count > 0:
            lines.append(f"  • {cat}: {count}")
    lines.append("")
    
    if meetings:
        lines.append("📅 Reuniones hoy:")
        for event in meetings[:5]:
            start = event.get('start', {}).get('dateTime', event.get('start', {}).get('date', ''))
            if 'T' in start:
                start = start.split('T')[1][:5]
            summary = event.get('summary', 'Sin título')
            lines.append(f"  • {start} {truncate(summary, 30)}")
        lines.append("")
    
    if pending_emails:
        lines.append("📋 Pendientes:")
        for i, email in enumerate(pending_emails[:8], 1):
            sender = extract_sender_name(email['sender'])
            subject = truncate(email['subject'], 30)
            lines.append(f"{i}. {sender}")
            lines.append(f"   {subject}")
        if len(pending_emails) > 8:
            lines.append(f"... y {len(pending_emails) - 8} más")
    
    lines.append("")
    lines.append("📎 Ver detalle en Excel:")
    lines.append(f"🔗 [Link Excel](https://docs.google.com/spreadsheets/d/{sheet_id})")
    lines.append("")
    lines.append("💡 Responde a este mensaje para agregar nota")
    
    message = '\n'.join(lines)
    
    await bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')
    
    for i, email in enumerate(pending_emails[:10], 1):
        sender = extract_sender_name(email['sender'])
        subject = truncate(email['subject'], 35)
        link = get_gmail_link(email['id'])
        
        msg_text = f"{i}. *{sender}*\n{subject}\n[Ver correo]({link})"
        
        keyboard = [
            [
                InlineKeyboardButton("Agregar Nota", callback_data=f"note_{email['id']}"),
                InlineKeyboardButton("Resolver", callback_data=f"resolve_{email['id']}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        sent_msg = await bot.send_message(
            chat_id=chat_id,
            text=msg_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        
        pending_messages[email['id']] = {
            'subject': email['subject'],
            'message_id': sent_msg.message_id
        }
    
    if len(pending_emails) > 10:
        await bot.send_message(chat_id=chat_id, text=f"... y {len(pending_emails) - 10} mas")

async def handle_callback(update, context):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    parts = data.split('_')
    action = parts[0]
    email_id = '_'.join(parts[1:])
    
    print(f"DEBUG: Callback recibido - action: {action}, email_id: {email_id}")
    
    subject = f"Pendiente {email_id}"
    if email_id in pending_messages:
        subject = pending_messages[email_id].get('subject', subject)
    
    try:
        import gspread
        gc = gspread.service_account(filename='service_account.json')
        
        sh = gc.open_by_key(USER_SHEET_ID)
        ws = sh.sheet1
        
        if action == "resolve":
            cells = ws.findall(subject)
            if cells:
                ws.update_cell(cells[0].row, 4, 'Resuelto')
            await query.edit_message_text(f"✅ Marcado como resuelto:\n{subject}")
        elif action == "note":
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"📝 Escribe la nota para:\n{subject}\n\n(Envia la nota)"
            )
    except Exception as e:
        print(f"Error en callback: {e}")
        await query.edit_message_text(f"✅ Hecho: {subject}")

async def run_bot_for_callbacks(bot, pending_emails):
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    await application.initialize()
    await application.start()
    
    await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text="🤖 Bot de botones activo por 60 segundos...")
    
    import time
    await asyncio.sleep(60)
    
    await application.stop()

async def main():
    print("Iniciando clasificador de correos...")
    
    print("Conectando a Gmail...")
    service, calendar_service = get_gmail_service()
    
    print("Descargando correos...")
    emails = get_emails(service)
    emails = group_by_thread(emails)
    print(f"   Encontrados: {len(emails)} correos")
    
    pending_emails = []
    by_category = {}
    
    print("Clasificando correos...")
    count = 0
    for email in emails:
        category = classify_email(email)
        
        if category not in by_category:
            by_category[category] = []
        by_category[category].append(email)
        
        if is_pending(service, email):
            pending_emails.append(email)
        
        count += 1
        if count % 10 == 0:
            print(f"   Procesados: {count}/{len(emails)}")
    
    report = {
        'total': len(emails),
        'by_category': by_category,
        'pending': pending_emails
    }
    
    print(f"   Pendientes: {len(pending_emails)}")
    
    print("Conectando a Google Sheets...")
    try:
        print("   Sincronizando...")
        sheet_id = sync_with_sheet(pending_emails)
        print(f"   Sheet OK: {sheet_id}")
    except Exception as e:
        print(f"   Error con Sheets: {e}")
        sheet_id = None
    
    meetings = []
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        print("Obteniendo reuniones...")
        meetings = get_meetings(calendar_service)
        print(f"   Reuniones hoy: {len(meetings)}")
        
        print("Enviando notificacion a Telegram...")
        
        bot = Bot(token=TELEGRAM_TOKEN)
        
        await send_telegram_with_buttons(
            bot,
            TELEGRAM_CHAT_ID,
            report,
            meetings,
            sheet_id
        )
        
        print("   Notificacion enviada!")
    else:
        print("! Telegram no configurado")
    
    print("Proceso completado!")

if __name__ == '__main__':
    asyncio.run(main())
