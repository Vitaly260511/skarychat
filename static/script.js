// script.js — SkaryChat
let token = localStorage.getItem('skarychat_token');
let currentUser = null;
let currentChat = null;
let ws = null;
let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;

const API = '';

async function api(path, method = 'GET', body = null) {
    const headers = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const options = { method, headers };
    if (body) options.body = JSON.stringify(body);
    const response = await fetch(API + path, options);
    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Error');
    }
    return response.json();
}

async function uploadFile(path, file) {
    const formData = new FormData();
    formData.append('file', file);
    const response = await fetch(API + path, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` },
        body: formData
    });
    if (!response.ok) throw new Error('Upload failed');
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
    if (username.length < 4) {
        document.getElementById('register-error').textContent = 'Юзернейм от 4 символов';
        return;
    }
    try {
        const data = await api('/api/register', 'POST', { username, password });
        token = data.token;
        currentUser = { id: data.user_id, username: data.username, avatar: '', theme: 'dark' };
        localStorage.setItem('skarychat_token', token);
        localStorage.setItem('skarychat_user', JSON.stringify(currentUser));
        showChatScreen();
    } catch (e) {
        document.getElementById('register-error').textContent = e.message;
    }
}

async function login() {
    const username = document.getElementById('login-username').value;
    const password = document.getElementById('login-password').value;
    try {
        const data = await api('/api/login', 'POST', { username, password });
        token = data.token;
        currentUser = { id: data.user_id, username: data.username, avatar: data.avatar, theme: data.theme };
        localStorage.setItem('skarychat_token', token);
        localStorage.setItem('skarychat_user', JSON.stringify(currentUser));
        if (data.theme === 'light') {
            document.body.classList.add('light');
            document.getElementById('theme-btn').textContent = '☀️';
        }
        showChatScreen();
    } catch (e) {
        document.getElementById('login-error').textContent = e.message;
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

function showChatScreen() {
    document.getElementById('auth-screen').classList.remove('active');
    document.getElementById('chat-screen').classList.add('active');
    document.getElementById('current-user').textContent = currentUser.username;
    if (currentUser.avatar) {
        document.getElementById('my-avatar').src = currentUser.avatar;
    }
    loadChats();
    connectWebSocket();
    requestNotificationPermission();
}

// ============ УВЕДОМЛЕНИЯ ============
function requestNotificationPermission() {
    if ('Notification' in window && Notification.permission === 'default') {
        Notification.requestPermission();
    }
}

function showNotification(title, body) {
    if ('Notification' in window && Notification.permission === 'granted') {
        new Notification(title, { body: body, icon: '/static/icon.png' });
    }
}

// ============ ТЕМА ============
async function toggleTheme() {
    const isLight = document.body.classList.toggle('light');
    const theme = isLight ? 'light' : 'dark';
    document.getElementById('theme-btn').textContent = isLight ? '☀️' : '🌙';
    if (currentUser) currentUser.theme = theme;
    try {
        await api('/api/theme', 'POST', { theme });
    } catch (e) {
        console.error(e);
    }
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
            const data = msg.data;
            if (currentChat && data.chat_id === currentChat.id) {
                addMessage(data);
            }
            if (data.user_id !== currentUser.id) {
                showNotification(data.username, data.text || 'Вложение');
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
            const prefix = chat.is_channel ? '📢 ' : (chat.is_group ? '👥 ' : '');
            item.innerHTML = `
                <div class="chat-avatar">${chat.name[0].toUpperCase()}</div>
                <div>${prefix}${chat.name}</div>
            `;
            list.appendChild(item);
        });
    } catch (e) {
        console.error(e);
    }
}

async function openChat(chat) {
    currentChat = chat;
    const prefix = chat.is_channel ? '📢 ' : (chat.is_group ? '👥 ' : '');
    document.getElementById('chat-name').textContent = prefix + chat.name;
    document.querySelectorAll('.chat-item').forEach(i => i.classList.remove('active'));
    if (event && event.target) {
        const item = event.target.closest('.chat-item');
        if (item) item.classList.add('active');
    }
    await refreshMessages();
    if (window.chatInterval) clearInterval(window.chatInterval);
    window.chatInterval = setInterval(refreshMessages, 3000);
}

async function refreshMessages() {
    if (!currentChat) return;
    try {
        const search = document.getElementById('search-input').value;
        const url = `/api/messages/${currentChat.id}` + (search ? `?search=${encodeURIComponent(search)}` : '');
        const messages = await api(url);
        const container = document.getElementById('messages');
        const wasAtBottom = container.scrollTop + container.clientHeight >= container.scrollHeight - 50;
        container.innerHTML = '';
        messages.forEach(addMessage);
        if (wasAtBottom) container.scrollTop = container.scrollHeight;
    } catch (e) {
        console.error(e);
    }
}

function addMessage(msg) {
    const container = document.getElementById('messages');
    const div = document.createElement('div');
    div.className = 'message' + (msg.user_id === currentUser.id ? ' own' : '');
    let content = `<div class="message-author">${msg.username}</div>`;
    if (msg.text) content += `<div class="message-text">${escapeHtml(msg.text)}</div>`;
    if (msg.image) content += `<img class="message-image" src="${msg.image}" onclick="window.open('${msg.image}')">`;
    if (msg.audio) content += `<audio class="message-audio" controls src="${msg.audio}"></audio>`;
    content += `<div class="message-time">${new Date(msg.created_at).toLocaleTimeString()}</div>`;
    div.innerHTML = content;
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
        await refreshMessages();
    } catch (e) {
        console.error(e);
    }
}

async function uploadImage(input) {
    const file = input.files[0];
    if (!file || !currentChat) return;
    try {
        const data = await uploadFile('/api/upload/image', file);
        await api('/api/messages', 'POST', { chat_id: currentChat.id, text: '', image: data.url });
        await refreshMessages();
    } catch (e) {
        alert('Ошибка загрузки');
    }
    input.value = '';
}

// ============ ГОЛОСОВЫЕ ============
async function toggleRecord() {
    const btn = document.getElementById('record-btn');
    if (isRecording) {
        mediaRecorder.stop();
        isRecording = false;
        btn.classList.remove('recording');
        return;
    }
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaRecorder = new MediaRecorder(stream);
        audioChunks = [];
        mediaRecorder.ondataavailable = (e) => audioChunks.push(e.data);
        mediaRecorder.onstop = async () => {
            const blob = new Blob(audioChunks, { type: 'audio/webm' });
            const file = new File([blob], 'voice.webm', { type: 'audio/webm' });
            try {
                const data = await uploadFile('/api/upload/audio', file);
                await api('/api/messages', 'POST', { chat_id: currentChat.id, text: '', audio: data.url });
                await refreshMessages();
            } catch (e) {
                alert('Ошибка загрузки аудио');
            }
            stream.getTracks().forEach(t => t.stop());
        };
        mediaRecorder.start();
        isRecording = true;
        btn.classList.add('recording');
    } catch (e) {
        alert('Нет доступа к микрофону');
    }
}

// ============ ПОИСК ============
let searchTimeout = null;
function searchMessages() {
    if (searchTimeout) clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
        refreshMessages();
    }, 300);
}

// ============ НОВЫЙ ЧАТ ============
async function showNewChat() {
    const modal = document.getElementById('new-chat-modal');
    modal.classList.add('active');
    const users = await api('/api/users');
    const list = document.getElementById('users-list');
    list.innerHTML = '';
    if (users.length === 0) {
        list.innerHTML = '<p class="hint">Других пользователей нет</p>';
    }
    users.forEach(user => {
        const item = document.createElement('div');
        item.className = 'user-item';
        item.innerHTML = `
            <input type="checkbox" value="${user.id}">
            ${user.avatar ? `<img class="avatar" src="${user.avatar}">` : ''}
            <span>${user.username}</span>
        `;
        item.onclick = (e) => {
            if (e.target.tagName !== 'INPUT') {
                const checkbox = item.querySelector('input');
                checkbox.checked = !checkbox.checked;
                item.classList.toggle('selected', checkbox.checked);
            }
        };
        list.appendChild(item);
    });
}

function closeNewChat() {
    document.getElementById('new-chat-modal').classList.remove('active');
    document.getElementById('new-chat-name').value = '';
    document.getElementById('new-chat-channel').checked = false;
}

async function createChat() {
    const name = document.getElementById('new-chat-name').value.trim();
    const isChannel = document.getElementById('new-chat-channel').checked;
    const members = Array.from(document.querySelectorAll('#users-list input:checked'))
        .map(i => parseInt(i.value));
    if (!name) {
        alert('Введи название');
        return;
    }
    try {
        await api('/api/chats', 'POST', { name, members, is_channel: isChannel });
        closeNewChat();
        loadChats();
    } catch (e) {
        alert(e.message);
    }
}

// ============ ПУБЛИЧНЫЕ КАНАЛЫ ============
async function showPublicChats() {
    const modal = document.getElementById('public-chats-modal');
    modal.classList.add('active');
    try {
        const chats = await api('/api/public-chats');
        const list = document.getElementById('public-chats-list');
        list.innerHTML = '';
        if (chats.length === 0) {
            list.innerHTML = '<p class="hint">Нет доступных каналов</p>';
            return;
        }
        chats.forEach(chat => {
            const item = document.createElement('div');
            item.className = 'user-item';
            item.innerHTML = `<span>📢 ${chat.name}</span>`;
            const btn = document.createElement('button');
            btn.textContent = 'Войти';
            btn.style.cssText = 'margin-left:auto;padding:5px 15px;background:#00A2FF;border:none;border-radius:8px;color:white;cursor:pointer;';
            btn.onclick = async () => {
                await api('/api/chats/join', 'POST', { chat_id: chat.id });
                closePublicChats();
                loadChats();
            };
            item.appendChild(btn);
            list.appendChild(item);
        });
    } catch (e) {
        console.error(e);
    }
}

function closePublicChats() {
    document.getElementById('public-chats-modal').classList.remove('active');
}

// ============ ПРОФИЛЬ ============
function showProfile() {
    document.getElementById('profile-modal').classList.add('active');
    document.getElementById('profile-username').textContent = '@' + currentUser.username;
    if (currentUser.avatar) {
        document.getElementById('profile-avatar').src = currentUser.avatar;
    }
}

function closeProfile() {
    document.getElementById('profile-modal').classList.remove('active');
}

async function uploadAvatar(input) {
    const file = input.files[0];
    if (!file) return;
    try {
        const data = await uploadFile('/api/avatar', file);
        currentUser.avatar = data.avatar;
        localStorage.setItem('skarychat_user', JSON.stringify(currentUser));
        document.getElementById('my-avatar').src = data.avatar;
        document.getElementById('profile-avatar').src = data.avatar;
    } catch (e) {
        alert('Ошибка загрузки аватара');
    }
    input.value = '';
}

// ============ ИНИЦИАЛИЗАЦИЯ ============
window.onload = () => {
    const savedUser = localStorage.getItem('skarychat_user');
    if (token && savedUser) {
        currentUser = JSON.parse(savedUser);
        if (currentUser.theme === 'light') {
            document.body.classList.add('light');
            document.getElementById('theme-btn').textContent = '☀️';
        }
        showChatScreen();
    }
};
