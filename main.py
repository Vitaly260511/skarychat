# -*- coding: utf-8 -*-
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Dict, List, Optional
import sqlite3, hashlib, secrets, json, os, shutil, uuid
from datetime import datetime

# СНАЧАЛА создаём папки
os.makedirs("uploads/avatars", exist_ok=True)
os.makedirs("uploads/images", exist_ok=True)
os.makedirs("uploads/audio", exist_ok=True)

app = FastAPI(title="SkaryChat")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
templates = Jinja2Templates(directory="templates")
security = HTTPBearer()
DB_PATH = "skarychat.db"
SECRET_KEY = secrets.token_hex(32)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        token TEXT,
        avatar TEXT DEFAULT '',
        theme TEXT DEFAULT 'dark',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS chats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        is_group INTEGER DEFAULT 0,
        is_channel INTEGER DEFAULT 0,
        owner_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS chat_members (
        chat_id INTEGER,
        user_id INTEGER,
        role TEXT DEFAULT 'member',
        joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (chat_id, user_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        user_id INTEGER,
        text TEXT,
        image TEXT,
        audio TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    conn.close()

init_db()

class RegisterModel(BaseModel):
    username: str
    password: str

class LoginModel(BaseModel):
    username: str
    password: str

class MessageModel(BaseModel):
    chat_id: int
    text: str
    image: Optional[str] = None
    audio: Optional[str] = None

class ChatModel(BaseModel):
    name: str
    members: List[int] = []
    is_channel: bool = False

class ThemeModel(BaseModel):
    theme: str

class JoinModel(BaseModel):
    chat_id: int

def hash_password(password: str) -> str:
    return hashlib.sha256((password + SECRET_KEY).encode()).hexdigest()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, username, avatar, theme FROM users WHERE token = ?", (token,))
    user = c.fetchone()
    conn.close()
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return {"id": user[0], "username": user[1], "avatar": user[2], "theme": user[3]}

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, List[WebSocket]] = {}
    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)
    def disconnect(self, user_id: int, websocket: WebSocket):
        if user_id in self.active_connections:
            if websocket in self.active_connections[user_id]:
                self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
    async def send_to_user(self, user_id: int, message: dict):
        if user_id in self.active_connections:
            for connection in self.active_connections[user_id]:
                try:
                    await connection.send_json(message)
                except:
                    pass
    async def broadcast_to_chat(self, chat_id: int, message: dict):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT user_id FROM chat_members WHERE chat_id = ?", (chat_id,))
        members = c.fetchall()
        conn.close()
        for member in members:
            await self.send_to_user(member[0], message)

manager = ConnectionManager()

@app.get("/", response_class=HTMLResponse)
async def index():
    with open("templates/index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.post("/api/register")
async def register(data: RegisterModel):
    if len(data.username) < 4:
        raise HTTPException(status_code=400, detail="Username must be at least 4 characters")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE username = ?", (data.username,))
    if c.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="Username already taken")
    token = secrets.token_hex(32)
    password_hash = hash_password(data.password)
    c.execute("INSERT INTO users (username, password_hash, token) VALUES (?, ?, ?)", (data.username, password_hash, token))
    user_id = c.lastrowid
    conn.commit()
    conn.close()
    return {"token": token, "user_id": user_id, "username": data.username}

@app.post("/api/login")
async def login(data: LoginModel):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    password_hash = hash_password(data.password)
    c.execute("SELECT id, username, avatar, theme FROM users WHERE username = ? AND password_hash = ?", (data.username, password_hash))
    user = c.fetchone()
    if not user:
        conn.close()
        raise HTTPException(status_code=401, detail="Invalid credentials")
    new_token = secrets.token_hex(32)
    c.execute("UPDATE users SET token = ? WHERE id = ?", (new_token, user[0]))
    conn.commit()
    conn.close()
    return {"token": new_token, "user_id": user[0], "username": user[1], "avatar": user[2], "theme": user[3]}

@app.get("/api/me")
async def get_me(user: dict = Depends(get_current_user)):
    return user

@app.post("/api/theme")
async def set_theme(data: ThemeModel, user: dict = Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET theme = ? WHERE id = ?", (data.theme, user["id"]))
    conn.commit()
    conn.close()
    return {"theme": data.theme}

@app.post("/api/avatar")
async def upload_avatar(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only images allowed")
    ext = file.filename.split(".")[-1]
    filename = f"{uuid.uuid4()}.{ext}"
    path = f"uploads/avatars/{filename}"
    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    avatar_url = f"/uploads/avatars/{filename}"
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET avatar = ? WHERE id = ?", (avatar_url, user["id"]))
    conn.commit()
    conn.close()
    return {"avatar": avatar_url}

@app.post("/api/upload/image")
async def upload_image(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only images allowed")
    ext = file.filename.split(".")[-1]
    filename = f"{uuid.uuid4()}.{ext}"
    path = f"uploads/images/{filename}"
    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"url": f"/uploads/images/{filename}"}

@app.post("/api/upload/audio")
async def upload_audio(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    if not file.content_type.startswith("audio/"):
        raise HTTPException(status_code=400, detail="Only audio allowed")
    ext = file.filename.split(".")[-1]
    filename = f"{uuid.uuid4()}.{ext}"
    path = f"uploads/audio/{filename}"
    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"url": f"/uploads/audio/{filename}"}

@app.get("/api/users")
async def get_users(user: dict = Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, username, avatar FROM users WHERE id != ?", (user["id"],))
    users = [{"id": u[0], "username": u[1], "avatar": u[2]} for u in c.fetchall()]
    conn.close()
    return users

@app.get("/api/chats")
async def get_chats(user: dict = Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''SELECT c.id, c.name, c.is_group, c.is_channel, c.owner_id 
                 FROM chats c JOIN chat_members cm ON c.id = cm.chat_id 
                 WHERE cm.user_id = ?''', (user["id"],))
    chats = [{"id": ch[0], "name": ch[1], "is_group": bool(ch[2]), "is_channel": bool(ch[3]), "owner_id": ch[4]} for ch in c.fetchall()]
    conn.close()
    return chats

@app.get("/api/public-chats")
async def get_public_chats(user: dict = Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''SELECT c.id, c.name, c.is_group, c.is_channel, c.owner_id 
                 FROM chats c 
                 WHERE c.is_channel = 1 AND c.id NOT IN (SELECT chat_id FROM chat_members WHERE user_id = ?)''', (user["id"],))
    chats = [{"id": ch[0], "name": ch[1], "is_group": bool(ch[2]), "is_channel": bool(ch[3]), "owner_id": ch[4]} for ch in c.fetchall()]
    conn.close()
    return chats

@app.post("/api/chats")
async def create_chat(data: ChatModel, user: dict = Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    is_group = 1 if data.is_channel or len(data.members) > 1 else 0
    c.execute("INSERT INTO chats (name, is_group, is_channel, owner_id) VALUES (?, ?, ?, ?)",
              (data.name, is_group, 1 if data.is_channel else 0, user["id"]))
    chat_id = c.lastrowid
    c.execute("INSERT INTO chat_members (chat_id, user_id, role) VALUES (?, ?, ?)", (chat_id, user["id"], "owner"))
    for member_id in data.members:
        c.execute("INSERT INTO chat_members (chat_id, user_id) VALUES (?, ?)", (chat_id, member_id))
    conn.commit()
    conn.close()
    return {"chat_id": chat_id, "name": data.name, "is_channel": data.is_channel}

@app.post("/api/chats/join")
async def join_chat(data: JoinModel, user: dict = Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT 1 FROM chat_members WHERE chat_id = ? AND user_id = ?", (data.chat_id, user["id"]))
    if c.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="Already member")
    c.execute("INSERT INTO chat_members (chat_id, user_id) VALUES (?, ?)", (data.chat_id, user["id"]))
    conn.commit()
    conn.close()
    return {"status": "joined"}

@app.get("/api/messages/{chat_id}")
async def get_messages(chat_id: int, search: str = "", user: dict = Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT 1 FROM chat_members WHERE chat_id = ? AND user_id = ?", (chat_id, user["id"]))
    if not c.fetchone():
        conn.close()
        raise HTTPException(status_code=403, detail="Access denied")
    if search:
        c.execute('''SELECT m.id, m.user_id, u.username, u.avatar, m.text, m.image, m.audio, m.created_at 
                     FROM messages m JOIN users u ON m.user_id = u.id 
                     WHERE m.chat_id = ? AND m.text LIKE ? 
                     ORDER BY m.created_at ASC LIMIT 100''', (chat_id, f"%{search}%"))
    else:
        c.execute('''SELECT m.id, m.user_id, u.username, u.avatar, m.text, m.image, m.audio, m.created_at 
                     FROM messages m JOIN users u ON m.user_id = u.id 
                     WHERE m.chat_id = ? ORDER BY m.created_at ASC LIMIT 100''', (chat_id,))
    messages = [{
        "id": m[0], "user_id": m[1], "username": m[2], "avatar": m[3],
        "text": m[4], "image": m[5], "audio": m[6], "created_at": m[7]
    } for m in c.fetchall()]
    conn.close()
    return messages

@app.post("/api/messages")
async def send_message(data: MessageModel, user: dict = Depends(get_current_user)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT 1 FROM chat_members WHERE chat_id = ? AND user_id = ?", (data.chat_id, user["id"]))
    if not c.fetchone():
        conn.close()
        raise HTTPException(status_code=403, detail="Access denied")
    c.execute("INSERT INTO messages (chat_id, user_id, text, image, audio) VALUES (?, ?, ?, ?, ?)",
              (data.chat_id, user["id"], data.text, data.image, data.audio))
    message_id = c.lastrowid
    conn.commit()
    c.execute('''SELECT m.id, m.user_id, u.username, u.avatar, m.text, m.image, m.audio, m.created_at 
                 FROM messages m JOIN users u ON m.user_id = u.id WHERE m.id = ?''', (message_id,))
    msg = c.fetchone()
    conn.close()
    message = {
        "id": msg[0], "user_id": msg[1], "username": msg[2], "avatar": msg[3],
        "text": msg[4], "image": msg[5], "audio": msg[6], "created_at": msg[7],
        "chat_id": data.chat_id
    }
    await manager.broadcast_to_chat(data.chat_id, {"type": "message", "data": message})
    return message

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    user_id = None
    try:
        data = await websocket.receive_text()
        msg = json.loads(data)
        if msg.get("type") == "auth":
            token = msg.get("token")
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT id FROM users WHERE token = ?", (token,))
            user = c.fetchone()
            conn.close()
            if user:
                user_id = user[0]
                await manager.connect(user_id, websocket)
                await websocket.send_json({"type": "auth_ok"})
            else:
                await websocket.send_json({"type": "auth_error"})
                await websocket.close()
                return
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            if msg.get("type") == "message":
                chat_id = msg.get("chat_id")
                text = msg.get("text")
                image = msg.get("image")
                audio = msg.get("audio")
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute("SELECT 1 FROM chat_members WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
                if c.fetchone():
                    c.execute("INSERT INTO messages (chat_id, user_id, text, image, audio) VALUES (?, ?, ?, ?, ?)",
                              (chat_id, user_id, text, image, audio))
                    message_id = c.lastrowid
                    conn.commit()
                    c.execute('''SELECT m.id, m.user_id, u.username, u.avatar, m.text, m.image, m.audio, m.created_at 
                                 FROM messages m JOIN users u ON m.user_id = u.id WHERE m.id = ?''', (message_id,))
                    m = c.fetchone()
                    message = {
                        "id": m[0], "user_id": m[1], "username": m[2], "avatar": m[3],
                        "text": m[4], "image": m[5], "audio": m[6], "created_at": m[7],
                        "chat_id": chat_id
                    }
                    await manager.broadcast_to_chat(chat_id, {"type": "message", "data": message})
                conn.close()
    except WebSocketDisconnect:
        if user_id:
            manager.disconnect(user_id, websocket)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
