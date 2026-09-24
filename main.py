from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta
import sqlite3
import hashlib
import secrets
import os
import shutil
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

app = FastAPI(title="NEXUSCHAT", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = "nexuschat.db"
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

security = HTTPBearer()

# ============ БАЗА ДАННЫХ ============

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        bio TEXT DEFAULT '',
        avatar TEXT DEFAULT '',
        theme TEXT DEFAULT 'dark',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS chats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        username TEXT UNIQUE,
        is_channel INTEGER DEFAULT 0,
        owner_id INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS chat_members (
        chat_id INTEGER,
        user_id INTEGER,
        PRIMARY KEY (chat_id, user_id)
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        text TEXT,
        voice TEXT,
        image TEXT,
        reply_to INTEGER,
        edited INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS reactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        message_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        emoji TEXT NOT NULL
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS email_codes (
        email TEXT PRIMARY KEY,
        code TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    conn.commit()
    conn.close()

init_db()

# ============ ХЕЛПЕРЫ ============

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def get_user_by_token(token: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM sessions WHERE token = ?", (token,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return row[0]

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    user_id = get_user_by_token(credentials.credentials)
    if not user_id:
        raise HTTPException(status_code=401, detail="Не авторизован")
    return user_id

# ============ МОДЕЛИ ============

class RegisterModel(BaseModel):
    username: str
    email: str
    password: str

class LoginModel(BaseModel):
    email: str
    password: str

class VerifyEmailModel(BaseModel):
    email: str
    code: str

class ProfileModel(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    bio: Optional[str] = None

class ChatModel(BaseModel):
    name: str
    username: Optional[str] = None
    is_channel: bool = False
    members: List[int] = []

class MessageModel(BaseModel):
    chat_id: int
    text: Optional[str] = None
    reply_to: Optional[int] = None

class ReactionModel(BaseModel):
    emoji: str

class ThemeModel(BaseModel):
    theme: str

# ============ АВТОРИЗАЦИЯ ============

@app.get("/")
def index():
    return {"status": "ok", "service": "NEXUSCHAT"}

@app.post("/api/send-code")
def send_code(data: dict):
    """Отправка кода на почту"""
    email = data.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Введи почту")
    
    code = str(secrets.randbelow(1000000)).zfill(6)
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO email_codes (email, code) VALUES (?, ?)", (email, code))
    conn.commit()
    conn.close()
    
    # Отправка через SendGrid
    try:
        message = Mail(
            from_email='ginifrost780@gmail.com',
            to_emails=email,
            subject='NEXUSCHAT - Код подтверждения',
            html_content=f'''
            <div style="font-family: Arial, sans-serif; background: #17212B; padding: 40px; border-radius: 20px; max-width: 500px; margin: 0 auto;">
                <h1 style="color: #2AABEE; text-align: center; font-size: 32px;">NEXUSCHAT</h1>
                <p style="color: #FFF; text-align: center; font-size: 18px;">Ваш код подтверждения:</p>
                <h2 style="color: #2AABEE; text-align: center; font-size: 48px; letter-spacing: 10px; margin: 30px 0;">{code}</h2>
                <p style="color: #708499; text-align: center; font-size: 14px;">Если вы не запрашивали код — проигнорируйте это письмо.</p>
            </div>
            '''
        )
        
        api_key = os.environ.get('SENDGRID_API_KEY', '')
        if not api_key:
            print("ОШИБКА: SENDGRID_API_KEY не найден в переменных окружения!")
            raise HTTPException(status_code=500, detail="SENDGRID_API_KEY не настроен")
        
        sg = SendGridAPIClient(api_key)
        response = sg.send(message)
        
        print(f"Письмо отправлено на {email}, статус: {response.status_code}")
        return {"status": "ok", "message": "Код отправлен на почту"}
    except Exception as e:
        print(f"Ошибка отправки: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка отправки: {str(e)}")

@app.post("/api/verify-email")
def verify_email(data: VerifyEmailModel):
    """Подтверждение почты"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT code FROM email_codes WHERE email = ?", (data.email,))
    row = c.fetchone()
    conn.close()
    
    if not row or row[0] != data.code:
        raise HTTPException(status_code=400, detail="Неверный код")
    
    return {"status": "ok", "message": "Почта подтверждена"}

@app.post("/api/register")
def register(data: RegisterModel):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    try:
        c.execute(
            "INSERT INTO users (username, email, password) VALUES (?, ?, ?)",
            (data.username, data.email, hash_password(data.password))
        )
        conn.commit()
        user_id = c.lastrowid
        
        token = secrets.token_hex(32)
        c.execute("INSERT INTO sessions (token, user_id) VALUES (?, ?)", (token, user_id))
        conn.commit()
        
        return {"status": "ok", "access_token": token, "user_id": user_id}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Пользователь уже существует")
    finally:
        conn.close()

@app.post("/api/login")
def login(data: LoginModel):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT id, username FROM users WHERE email = ? AND password = ?",
        (data.email, hash_password(data.password))
    )
    row = c.fetchone()
    
    if not row:
        conn.close()
        raise HTTPException(status_code=401, detail="Неверная почта или пароль")
    
    user_id, username = row
    
    token = secrets.token_hex(32)
    c.execute("INSERT INTO sessions (token, user_id) VALUES (?, ?)", (token, user_id))
    conn.commit()
    conn.close()
    
    return {"status": "ok", "access_token": token, "user_id": user_id, "username": username}

@app.post("/api/logout")
def logout(user_id: int = Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    return {"status": "ok"}

@app.get("/api/me")
def get_me(user_id: int = Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, username, email, bio, avatar, theme FROM users WHERE id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    return {
        "id": row[0],
        "username": row[1],
        "email": row[2],
        "bio": row[3],
        "avatar": row[4],
        "theme": row[5]
    }

@app.post("/api/profile")
def update_profile(data: ProfileModel, user_id: int = Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    if data.username:
        c.execute("UPDATE users SET username = ? WHERE id = ?", (data.username, user_id))
    if data.email:
        c.execute("UPDATE users SET email = ? WHERE id = ?", (data.email, user_id))
    if data.bio is not None:
        c.execute("UPDATE users SET bio = ? WHERE id = ?", (data.bio, user_id))
    
    conn.commit()
    conn.close()
    return {"status": "ok"}

@app.post("/api/theme")
def set_theme(data: ThemeModel, user_id: int = Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET theme = ? WHERE id = ?", (data.theme, user_id))
    conn.commit()
    conn.close()
    return {"status": "ok"}

# ============ ПОИСК ============

@app.get("/api/users/search")
def search_users(q: str, user_id: int = Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, username, bio, avatar FROM users WHERE username LIKE ? AND id != ?", (f"%{q}%", user_id))
    rows = c.fetchall()
    conn.close()
    
    return [{"id": r[0], "username": r[1], "bio": r[2], "avatar": r[3]} for r in rows]

@app.get("/api/chats/search")
def search_chats(q: str, user_id: int = Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT id, name, username, is_channel FROM chats WHERE name LIKE ? OR username LIKE ?",
        (f"%{q}%", f"%{q}%")
    )
    rows = c.fetchall()
    conn.close()
    
    return [{"id": r[0], "name": r[1], "username": r[2], "is_channel": r[3]} for r in rows]

# ============ ЧАТЫ ============

@app.get("/api/chats")
def get_chats(user_id: int = Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT c.id, c.name, c.username, c.is_channel,
               (SELECT text FROM messages WHERE chat_id = c.id ORDER BY id DESC LIMIT 1) as last_message,
               (SELECT created_at FROM messages WHERE chat_id = c.id ORDER BY id DESC LIMIT 1) as last_message_time
        FROM chats c
        JOIN chat_members cm ON c.id = cm.chat_id
        WHERE cm.user_id = ?
        ORDER BY last_message_time DESC
    ''', (user_id,))
    rows = c.fetchall()
    conn.close()
    
    return [{
        "id": r[0],
        "name": r[1],
        "username": r[2],
        "is_channel": r[3],
        "last_message": r[4],
        "last_message_time": r[5]
    } for r in rows]

@app.post("/api/chats")
def create_chat(data: ChatModel, user_id: int = Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute(
        "INSERT INTO chats (name, username, is_channel, owner_id) VALUES (?, ?, ?, ?)",
        (data.name, data.username, 1 if data.is_channel else 0, user_id)
    )
    chat_id = c.lastrowid
    
    c.execute("INSERT INTO chat_members (chat_id, user_id) VALUES (?, ?)", (chat_id, user_id))
    
    for member_id in data.members:
        c.execute("INSERT OR IGNORE INTO chat_members (chat_id, user_id) VALUES (?, ?)", (chat_id, member_id))
    
    conn.commit()
    conn.close()
    
    return {"status": "ok", "chat_id": chat_id}

@app.get("/api/chats/{chat_id}")
def get_chat_info(chat_id: int, user_id: int = Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, name, username, is_channel, owner_id FROM chats WHERE id = ?", (chat_id,))
    row = c.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="Чат не найден")
    
    return {
        "id": row[0],
        "name": row[1],
        "username": row[2],
        "is_channel": row[3],
        "owner_id": row[4]
    }

# ============ СООБЩЕНИЯ ============

@app.get("/api/messages/{chat_id}")
def get_messages(chat_id: int, user_id: int = Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT m.id, m.user_id, u.username, m.text, m.voice, m.image,
               m.reply_to, m.edited, m.created_at
        FROM messages m
        JOIN users u ON m.user_id = u.id
        WHERE m.chat_id = ?
        ORDER BY m.id ASC
    ''', (chat_id,))
    rows = c.fetchall()
    
    result = []
    for r in rows:
        msg_id = r[0]
        
        c.execute("SELECT emoji, COUNT(*) FROM reactions WHERE message_id = ? GROUP BY emoji", (msg_id,))
        reactions = c.fetchall()
        
        result.append({
            "id": r[0],
            "user_id": r[1],
            "username": r[2],
            "text": r[3],
            "voice": r[4],
            "image": r[5],
            "reply_to": r[6],
            "edited": r[7],
            "created_at": r[8],
            "is_own": r[1] == user_id,
            "reactions": [{"emoji": rr[0], "count": rr[1]} for rr in reactions]
        })
    
    conn.close()
    return result

@app.post("/api/messages")
def send_message(data: MessageModel, user_id: int = Depends(get_current_user)):
    if not data.text:
        raise HTTPException(status_code=400, detail="Пустое сообщение")
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute(
        "INSERT INTO messages (chat_id, user_id, text, reply_to) VALUES (?, ?, ?, ?)",
        (data.chat_id, user_id, data.text, data.reply_to)
    )
    message_id = c.lastrowid
    
    conn.commit()
    conn.close()
    
    return {"status": "ok", "message_id": message_id}

@app.post("/api/messages/{message_id}/edit")
def edit_message(message_id: int, data: dict, user_id: int = Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("SELECT user_id FROM messages WHERE id = ?", (message_id,))
    row = c.fetchone()
    
    if not row or row[0] != user_id:
        conn.close()
        raise HTTPException(status_code=403, detail="Не твоё сообщение")
    
    c.execute("UPDATE messages SET text = ?, edited = 1 WHERE id = ?", (data.get("text"), message_id))
    conn.commit()
    conn.close()
    
    return {"status": "ok"}

@app.post("/api/messages/{message_id}/delete")
def delete_message(message_id: int, user_id: int = Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("SELECT user_id FROM messages WHERE id = ?", (message_id,))
    row = c.fetchone()
    
    if not row or row[0] != user_id:
        conn.close()
        raise HTTPException(status_code=403, detail="Не твоё сообщение")
    
    c.execute("DELETE FROM messages WHERE id = ?", (message_id,))
    c.execute("DELETE FROM reactions WHERE message_id = ?", (message_id,))
    conn.commit()
    conn.close()
    
    return {"status": "ok"}

@app.post("/api/messages/{message_id}/reaction")
def add_reaction(message_id: int, data: ReactionModel, user_id: int = Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("SELECT id FROM reactions WHERE message_id = ? AND user_id = ? AND emoji = ?",
              (message_id, user_id, data.emoji))
    if c.fetchone():
        c.execute("DELETE FROM reactions WHERE message_id = ? AND user_id = ? AND emoji = ?",
                  (message_id, user_id, data.emoji))
    else:
        c.execute("INSERT INTO reactions (message_id, user_id, emoji) VALUES (?, ?, ?)",
                  (message_id, user_id, data.emoji))
    
    conn.commit()
    conn.close()
    
    return {"status": "ok"}

# ============ ГОЛОСОВЫЕ ============

@app.post("/api/messages/{chat_id}/voice")
async def send_voice(chat_id: int, file: UploadFile = File(...), user_id: int = Depends(get_current_user)):
    filename = f"voice_{user_id}_{secrets.token_hex(8)}.webm"
    filepath = os.path.join(UPLOAD_DIR, filename)
    
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO messages (chat_id, user_id, voice) VALUES (?, ?, ?)",
        (chat_id, user_id, filename)
    )
    message_id = c.lastrowid
    conn.commit()
    conn.close()
    
    return {"status": "ok", "message_id": message_id, "voice": filename}

# ============ ЗАГРУЗКА ФАЙЛОВ ============

@app.post("/api/upload/image")
async def upload_image(file: UploadFile = File(...), user_id: int = Depends(get_current_user)):
    filename = f"image_{user_id}_{secrets.token_hex(8)}_{file.filename}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    return {"status": "ok", "filename": filename}

@app.post("/api/avatar")
async def upload_avatar(file: UploadFile = File(...), user_id: int = Depends(get_current_user)):
    filename = f"avatar_{user_id}_{secrets.token_hex(8)}_{file.filename}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET avatar = ? WHERE id = ?", (filename, user_id))
    conn.commit()
    conn.close()
    
    return {"status": "ok", "filename": filename}