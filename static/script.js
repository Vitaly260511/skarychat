// script.js — SkaryChat

let token = localStorage.getItem('skarychat_token');
let currentUser = null;
let currentChat = null;
let ws = null;

// ============ API ============
const API = '';

async function api(path, method = 'GET', body = null) {
    const headers = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = `Bearer ${token}`;
    
    const options = { method, headers };
    if (body) options.body = JSON.stringify(body);
    
    const response = await fetch(API + path, options);
    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Ошибка');
    }
    return response.json();
}

// ============ АВТОРИЗАЦИЯ ============
function switchTab(tab) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.form').forEach(f => f.classList.remove('active'));
    
    event.target.classList.add('active');
    document.getElementById(tab + '-form').classList.add('active');
}

async function register() {
    const username = document.getElementById('register-username').value;
    const password = document.getElementById('register-password').value;
    const errorEl = document.getElementById('register-error');
    
    try {
        const data = await api('/api/register', 'POST', { username, password });
        token = data.token;
        currentUser = { id: data.user_id, username: data.username };
        localStorage.setItem('skarychat_token', token);
        localStorage.setItem('skarychat_user', JSON.stringify(currentUser));
        showChatScreen();
    } catch (e) {
        errorEl.textContent = e.message;
    }
}

async function login() {
    const username = document.getElementById('login-username').value;
    const password = document.getElementById('login-password').value;
    const errorEl = document.getElementById('login-error');
    
    try {
        const data = await api('/api/login', 'POST', { username, password });
        token = data.token;
        currentUser = { id: data.user_id, username: data.username };
        localStorage.setItem('skarychat_token', token);
        localStorage.setItem('skarychat_user', JSON.stringify(currentUser));
        showChatScreen();
    } catch (e) {
        errorEl.textContent = e.message;
    }
}

function logout() {
    localStorage.removeItem('skarychat_token');
    localStorage.removeItem('skarychat_user');
    token = null;
    currentUser = null;
    if (ws) ws.close();
    location.reload();
}

// ============ ЭКРАНЫ ============
function showChatScreen() {
    document.getElementById('auth-screen').classList.remove('active');
    document.getElementById('chat-screen').classList.add('active');
    document.getElementById('current-user').textContent = currentUser.username;
    loadChats();
    connectWebSocket();
}

// ============ WEBSOCKET ============
function connectWebSocket() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${location.host}/ws`);
    
    ws.onopen = () => {
        ws.send(JSON.stringify({ type: 'auth', token }));
    };
    
    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.type === 'message') {
            if (currentChat && msg.data.chat_id === currentChat.id) {
                addMessage(msg.data);
            }
        }
    };
    
    ws.onclose = () => {
        setTimeout(connectWebSocket, 3000);
    };
}

// ============ ЧАТЫ ============
async function loadChats() {
    try {
        const chats = await api('/api/chats');
        const list = document.getElementById('chats-list');
        list.innerHTML = '';
        
        chats.forEach(chat => {
            const item = document.createElement('div');
            item.className = 'chat-item';
            item.onclick = () => openChat(chat);
            item.innerHTML = `
                <div class="chat-avatar">${chat.name[0].toUpperCase()}</div>
                <div>${chat.name}</div>
            `;
            list.appendChild(item);
        });
    } catch (e) {
        console.error(e);
    }
}

async function openChat(chat) {
    currentChat = chat;
    document.getElementById('chat-name').textContent = chat.name;
    
    document.querySelectorAll('.chat-item').forEach(i => i.classList.remove('active'));
    event.target.closest('.chat-item').classList.add('active');
    
    const messages = await api(`/api/messages/${chat.id}`);
    const container = document.getElementById('messages');
    container.innerHTML = '';
    messages.forEach(addMessage);
}

function addMessage(msg) {
    const container = document.getElementById('messages');
    const div = document.createElement('div');
    div.className = 'message' + (msg.user_id === currentUser.id ? ' own' : '');
    div.innerHTML = `
        <div class="message-author">${msg.username}</div>
        <div class="message-text">${escapeHtml(msg.text)}</div>
        <div class="message-time">${new Date(msg.created_at).toLocaleTimeString()}</div>
    `;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ============ СООБЩЕНИЯ ============
async function sendMessage() {
    const input = document.getElementById('message-text');
    const text = input.value.trim();
    if (!text || !currentChat) return;
    
    try {
        await api('/api/messages', 'POST', { chat_id: currentChat.id, text });
        input.value = '';
    } catch (e) {
        console.error(e);
    }
}

// ============ НОВЫЙ ЧАТ ============
async function showNewChat() {
    const modal = document.getElementById('new-chat-modal');
    modal.classList.add('active');
    
    const users = await api('/api/users');
    const list = document.getElementById('users-list');
    list.innerHTML = '';
    
    users.forEach(user => {
        const item = document.createElement('div');
        item.className = 'user-item';
        item.innerHTML = `
            <input type="checkbox" value="${user.id}">
            <span>${user.username}</span>
        `;
        item.onclick = (e) => {
            if (e.target.tagName !== 'INPUT') {
                const checkbox = item.querySelector('input');
                checkbox.checked = !checkbox.checked;
            }
        };
        list.appendChild(item);
    });
}

function closeNewChat() {
    document.getElementById('new-chat-modal').classList.remove('active');
}

async function createChat() {
    const name = document.getElementById('new-chat-name').value.trim();
    const members = Array.from(document.querySelectorAll('#users-list input:checked'))
        .map(i => parseInt(i.value));
    
    if (!name || members.length === 0) {
        alert('Введи название и выбери участников');
        return;
    }
    
    try {
        await api('/api/chats', 'POST', { name, members });
        closeNewChat();
        loadChats();
    } catch (e) {
        alert(e.message);
    }
}

// ============ ИНИЦИАЛИЗАЦИЯ ============
window.onload = () => {
    const savedUser = localStorage.getItem('skarychat_user');
    if (token && savedUser) {
        currentUser = JSON.parse(savedUser);
        showChatScreen();
    }
};