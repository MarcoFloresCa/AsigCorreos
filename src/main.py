import os
import base64
import json
import pickle
from datetime import datetime, timedelta
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from telegram import Bot
import asyncio
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/gmail.modify', 'https://www.googleapis.com/auth/calendar.events.readonly']

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

USER_EMAIL = None
HISTORY_FILE = 'history.json'

CATEGORIES = {
    'Requerimiento': ['requerimiento', 'solicitud', 'por favor', 'urgente', 'necesito', 'requiere', 'importante', 'por responder', 'pendiente', 'favor confirmar', 'favor responder'],
    'Promocion': ['oferta', 'descuento', 'promocion', 'sale', 'gratis', 'cashback', 'beneficio', 'promo'],
    'Informe': ['informe', 'reporte', 'reporte diario', 'resumen', 'dashboard', 'daily report'],
}

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

def get_emails(service, days_back=30):
    date_str = (datetime.now() - timedelta(days=days_back)).strftime('%Y/%m/%d')
    query = f'after:{date_str} -from:me'
    print(f"   Query: {query}")
    results = service.users().messages().list(userId='me', q=query, maxResults=100).execute()
    messages = results.get('messages', [])
    
    emails = []
    threads_seen = set()
    
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
        
        email_entry = {
            'id': msg['id'],
            'thread_id': thread_id,
            'subject': subject,
            'sender': sender,
            'snippet': snippet,
            'body': body,
            'date': msg_data.get('internalDate'),
        }
        
        emails.append(email_entry)
    
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

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                return json.load(f)
        except:
            return []
    return []

def save_history(history):
    with open(HISTORY_FILE, 'w') as f:
        json.dump(history, f, indent=2)

def add_to_history(email, resolved_date):
    history = load_history()
    history.append({
        'subject': email['subject'],
        'sender': email['sender'],
        'resolved_date': resolved_date,
        'original_date': email.get('date', '')
    })
    save_history(history)

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
    body = email.get('body', '').lower()
    
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

def truncate(text, length=35):
    text = text.replace('\n', ' ').replace('\r', '')
    if len(text) > length:
        return text[:length] + '...'
    return text

def extract_sender_name(sender):
    if '<' in sender:
        return sender.split('<')[0].strip().strip('"')
    return sender.split('@')[0]

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

def send_telegram_notification(bot, chat_id, report, meetings):
    lines = []
    lines.append("=" * 50)
    lines.append(f"RESUMEN DE CORREOS")
    lines.append(datetime.now().strftime('%d/%m/%Y %H:%M'))
    lines.append("=" * 50)
    lines.append(f"Total: {report['total']} correos")
    lines.append("")
    
    for category in ['Requerimiento', 'Informe Importante', 'Informe (No importante)', 'Promocion', 'Otro']:
        emails = report['by_category'].get(category, [])
        if emails:
            lines.append(f"[{category}]: {len(emails)}")
    
    if meetings:
        lines.append("")
        lines.append("-" * 50)
        lines.append(f"REUNIONES HOY: {len(meetings)}")
        lines.append("-" * 50)
        for event in meetings[:5]:
            start = event.get('start', {}).get('dateTime', event.get('start', {}).get('date', 'Sin hora'))
            if 'T' in start:
                start = start.split('T')[1][:5]
            summary = event.get('summary', 'Sin titulo')
            lines.append(f"- {start} {truncate(summary, 30)}")
    
    lines.append("")
    lines.append("-" * 50)
    lines.append(f"PENDIENTES: {len(report['pending'])}")
    lines.append("-" * 50)
    
    if report['pending']:
        for i, email in enumerate(report['pending'][:8], 1):
            sender = extract_sender_name(email['sender'])
            subject = truncate(email['subject'], 30)
            lines.append(f"{i}. {sender}")
            lines.append(f"   {subject}")
            lines.append(f"   [Link]({get_gmail_link(email['id'])})")
    else:
        lines.append("No hay pendientes")
    
    if len(report['pending']) > 8:
        lines.append(f"... y {len(report['pending']) - 8} mas")
    
    lines.append("")
    lines.append("=" * 50)
    
    message = '\n'.join(lines)
    
    try:
        asyncio.run(bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown'))
    except Exception as e:
        print(f"Error enviando Telegram: {e}")
        plain_message = '\n'.join(lines).replace('[Link](url)', 'Link: url')
        try:
            asyncio.run(bot.send_message(chat_id=chat_id, text=plain_message))
        except Exception as e2:
            print(f"Error enviando Telegram (sin markdown): {e2}")

def main():
    print("Iniciando clasificador de correos...")
    
    print("Conectando a Gmail...")
    service, calendar_service = get_gmail_service()
    
    print("Descargando correos...")
    emails = get_emails(service)
    emails = group_by_thread(emails)
    print(f"   Encontrados: {len(emails)} correos (sin duplicados)")
    
    report = {
        'total': len(emails),
        'by_category': {},
        'pending': []
    }
    
    print("Clasificando correos...")
    count = 0
    for email in emails:
        category = classify_email(email)
        
        if category not in report['by_category']:
            report['by_category'][category] = []
        report['by_category'][category].append(email)
        
        if is_pending(service, email):
            report['pending'].append(email)
        
        count += 1
        if count % 10 == 0:
            print(f"   Procesados: {count}/{len(emails)}")
    
    print(f"   Clasificacion completada!")
    for cat, emails_list in report['by_category'].items():
        print(f"   - {cat}: {len(emails_list)}")
    print(f"   - Pendientes: {len(report['pending'])}")
    
    meetings = []
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        print("Obteniendo reuniones...")
        meetings = get_meetings(calendar_service)
        print(f"   Reuniones hoy: {len(meetings)}")
        
        print("Enviando notificacion a Telegram...")
        bot = Bot(token=TELEGRAM_TOKEN)
        send_telegram_notification(bot, TELEGRAM_CHAT_ID, report, meetings)
        print("   Notificacion enviada!")
    else:
        print("! Telegram no configurado")
    
    print("Proceso completado!")

if __name__ == '__main__':
    main()
