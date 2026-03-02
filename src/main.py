import os
import json
import pickle
from datetime import datetime, timedelta
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from openai import OpenAI
from telegram import Bot
from dotenv import load_dotenv

load_dotenv()

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/gmail.modify']

DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

CATEGORIES = {
    'Requerimiento': ['requerimiento', 'solicitud', 'por favor', 'urgente', 'necesito', 'requiere', 'importante', 'por responder', 'pendiente'],
    'Promocion': ['oferta', 'descuento', 'promoción', 'sale', 'gratis', 'cashback', 'beneficio', 'promo'],
    'Informe': ['informe', 'reporte', 'daily', 'semanal', 'mensual', 'reporte', 'resumen', 'dashboard'],
    'Personal': ['personal', 'privado', 'amigo', 'familia'],
}

def get_gmail_service():
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
    
    return build('gmail', 'v1', credentials=creds)

def get_emails(service, days_back=7):
    query = f'after:{datetime.now() - timedelta(days=days_back)}'
    results = service.users().messages().list(userId='me', q=query, maxResults=100).execute()
    messages = results.get('messages', [])
    
    emails = []
    for msg in messages:
        msg_data = service.users().messages().get(userId='me', id=msg['id']).execute()
        headers = msg_data.get('payload', {}).get('headers', [])
        
        subject = next((h['value'] for h in headers if h['name'] == 'Subject'), '(Sin asunto)')
        sender = next((h['value'] for h in headers if h['name'] == 'From'), 'Desconocido')
        snippet = msg_data.get('snippet', '')
        
        emails.append({
            'id': msg['id'],
            'subject': subject,
            'sender': sender,
            'snippet': snippet,
            'date': msg_data.get('internalDate'),
        })
    
    return emails

def classify_email(client, subject, snippet):
    text = f"Asunto: {subject}\n\nContenido: {snippet}"
    
    prompt = f"""Clasifica este correo en una de estas categorías:
- Requerimiento: Necesita respuesta o acción de tu parte
- Promocion: Ofertas, descuentos, marketing
- Informe: Reportes, dashboards, actualizaciones
- Personal: Correos personales
- Otro: No pertenece a las anteriores

Responde SOLO con el nombre de la categoría.

{text}"""

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=50
        )
        category = response.choices[0].message.content.strip()
        
        for cat in CATEGORIES:
            if cat.lower() in category.lower():
                return cat
        return "Otro"
    except Exception as e:
        print(f"Error classify: {e}")
        return classify_by_keywords(subject, snippet)

def classify_by_keywords(subject, snippet):
    text = (subject + " " + snippet).lower()
    
    for category, keywords in CATEGORIES.items():
        for keyword in keywords:
            if keyword.lower() in text:
                return category
    return "Otro"

def is_pending(client, subject, snippet):
    text = f"Asunto: {subject}\n\nContenido: {snippet}"
    
    prompt = f"""Analiza este correo y determina si requiere una respuesta o acción de tu parte.
Responde SOLO con "SI" o "NO".

{text}"""

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=10
        )
        result = response.choices[0].message.content.strip().upper()
        return "SI" in result
    except:
        keywords = ['por favor', 'responder', 'urgente', 'necesito', 'favor', 'pendiente', 'requiere']
        text_lower = (subject + " " + snippet).lower()
        return any(kw in text_lower for kw in keywords)

def send_telegram_notification(bot, chat_id, report):
    message = f"📧 *Resumen de Correos - {datetime.now().strftime('%d/%m/%Y %H:%M')}*\n\n"
    
    message += f"📊 *Total: {report['total']}*\n\n"
    
    for category, emails in report['by_category'].items():
        if emails:
            message += f"*{category}:* {len(emails)}\n"
    
    message += f"\n⚠️ *Pendientes: {len(report['pending'])}*\n"
    
    if report['pending']:
        message += "\n📌 *Requerimientos pendientes:*\n"
        for email in report['pending'][:5]:
            subject = email['subject'][:50] + "..." if len(email['subject']) > 50 else email['subject']
            message += f"• {subject}\n"
    
    if len(report['pending']) > 5:
        message += f"... y {len(report['pending']) - 5} más"
    
    bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')

def main():
    print("🚀 Iniciando clasificador de correos...")
    
    print("📧 Conectando a Gmail...")
    service = get_gmail_service()
    
    print("🤖 Conectando a DeepSeek...")
    client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com"
    )
    
    print("📥 Descargando correos de los últimos 7 días...")
    emails = get_emails(service, days_back=7)
    print(f"   Encontrados: {len(emails)} correos")
    
    report = {
        'total': len(emails),
        'by_category': {},
        'pending': []
    }
    
    print("🔍 Clasificando correos...")
    for email in emails:
        category = classify_email(client, email['subject'], email['snippet'])
        
        if category not in report['by_category']:
            report['by_category'][category] = []
        report['by_category'][category].append(email)
        
        if is_pending(client, email['subject'], email['snippet']):
            report['pending'].append(email)
    
    print(f"   Clasificación completada!")
    for cat, emails_list in report['by_category'].items():
        print(f"   - {cat}: {len(emails_list)}")
    print(f"   - Pendientes: {len(report['pending'])}")
    
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        print("📱 Enviando notificación a Telegram...")
        bot = Bot(token=TELEGRAM_TOKEN)
        send_telegram_notification(bot, TELEGRAM_CHAT_ID, report)
        print("   ¡Notificación enviada!")
    else:
        print("⚠️ Telegram no configurado, omitiendo notificación")
    
    print("✅ Proceso completado!")

if __name__ == '__main__':
    main()
