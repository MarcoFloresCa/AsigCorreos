# AsigCorreos - Clasificador de Correos

Sistema automático para clasificar correos de Gmail y enviar resumenes por Telegram.

## Requisitos

- Python 3.7+
- Cuenta de Gmail
- API Key de DeepSeek
- Bot de Telegram

## Instalación

1. **Clonar o descargar el proyecto**

2. **Instalar dependencias:**
```bash
pip install -r requirements.txt
```

3. **Configurar variables de entorno:**
```bash
cp .env.example .env
# Editar .env con tus credenciales
```

## Configuración de APIs

### 1. Gmail API

1. Ir a [Google Cloud Console](https://console.cloud.google.com/)
2. Crear proyecto nuevo: "AsigCorreos"
3. Habilitar Gmail API:
   - APIs y servicios → Biblioteca → Buscar "Gmail API" → Habilitar
4. Crear credenciales:
   - APIs y servicios → Credenciales → Crear credenciales → ID de cliente OAuth
   - Tipo de aplicación: Aplicación de escritorio
   - Descargar como `credentials.json`
5. Poner el archivo en la raíz del proyecto

### 2. DeepSeek API

1. Ir a [DeepSeek](https://platform.deepseek.com/)
2. Crear cuenta
3. API Keys → Crear nueva key
4. Copiar la key en `.env`

### 3. Telegram Bot

1. Buscar @BotFather en Telegram
2. Enviar `/newbot`
3. Seguir instrucciones y obtener el token
4. Buscar @userinfobot para obtener tu chat_id
5. Agregar ambos a `.env`

## Uso

### Primera ejecución

```bash
python src/main.py
```

La primera vez se abrirá el navegador para autorizar Gmail. Esto crea `token.pickle`.

### Ejecución automática al iniciar PC

1. Abrir Programador de tareas (taskschd.msc)
2. Crear tarea básica:
   - Nombre: "AsigCorreos"
   - Desencadenador: Al iniciar sesión
   - Acción: Iniciar un programa
   - Programa: `python`
   - Argumentos: `C:\ruta\al\proyecto\src\main.py`
   - Iniciar en: `C:\ruta\al\proyecto`

## Estructura

```
AsigCorreos/
├── credentials.json    # (tu archivo de Gmail)
├── token.pickle       # (se crea automáticamente)
├── .env               # (tu archivo de configuración)
├── requirements.txt   # dependencias
└── src/
    └── main.py        # script principal
```

## Categorías

- **Requerimiento**: Necesita respuesta
- **Promocion**: Ofertas y marketing
- **Informe**: Reportes y dashboards
- **Personal**: Correos personales
- **Otro**: No clasificado
