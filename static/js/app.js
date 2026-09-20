// ============================================
// app.js — الأساسيات: State + Chat + UI + Helpers
// ============================================

// ---------- الثوابت ----------
export const EXTERNAL_PLATFORMS = [
    'youtube', 'tiktok', 'facebook', 'instagram',
    'twitter', 'vimeo', 'dailymotion', 'twitch'
];

export const FALLBACK_VIDEO_URL =
    'https://sample-videos.com/video321/mp4/240/big_buck_bunny_240p_1mb.mp4';

export const MAX_VIDEO_SIZE = 100 * 1024 * 1024;

// ---------- الحالة العامة ----------
export const state = {
    chatHistory: [],
    videoLinks: [],
    generatedVideo: null,
    currentProjectId: null,
    sessionId: null,
    processingSessionId: null,
    startTime: null,
    progressTimer: null,
    processing: false,
    cancelProcessing: false,
    uploadedFile: null,
    videoData: null,
    isYoutubeAuth: false
};

export let currentAbortController = null;
export function setAbortController(c) { currentAbortController = c; }
export function getAbortController() { return currentAbortController; }
export function abortCurrentRequest() {
    if (currentAbortController) {
        currentAbortController.abort();
        currentAbortController = null;
    }
}

// ---------- الأدوات المساعدة ----------
export function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

export function formatDuration(seconds) {
    if (!seconds || isNaN(seconds)) return '—';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${String(secs).padStart(2, '0')}`;
}

export function formatNumber(num) {
    if (!num) return '—';
    if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
    if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
    return num.toString();
}

export function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    return (bytes / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
}

// ---------- الإشعارات ----------
export function showToast(message, type = 'info') {
    document.querySelectorAll('.toast-message').forEach(t => t.remove());
    const toast = document.createElement('div');
    const colors = { success: 'bg-green-600', error: 'bg-red-600', warning: 'bg-yellow-600', info: 'bg-blue-600' };
    toast.className = `toast-message fixed bottom-4 right-4 ${colors[type] || colors.info} text-white px-6 py-3 rounded-lg shadow-lg z-50 transition-all duration-300 transform translate-y-full opacity-0 max-w-md`;
    toast.textContent = message;
    document.body.appendChild(toast);
    requestAnimationFrame(() => toast.classList.remove('translate-y-full', 'opacity-0'));
    setTimeout(() => {
        toast.classList.add('translate-y-full', 'opacity-0');
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// ---------- الدردشة ----------
export function addMessage(role, content, timestamp = new Date()) {
    const container = document.getElementById('chat-messages');
    const timeStr = timestamp.toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' });
    const messageDiv = document.createElement('div');
    messageDiv.className = `flex items-start gap-3 ${role === 'user' ? 'flex-row-reverse' : ''}`;
    const avatar = document.createElement('div');
    avatar.className = `w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${role === 'user' ? 'bg-blue-600' : 'bg-indigo-600'}`;
    avatar.innerHTML = role === 'user'
        ? '<svg class="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/></svg>'
        : '<svg class="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/></svg>';
    const bubble = document.createElement('div');
    bubble.className = `flex-1 ${role === 'user' ? 'bg-blue-600/30 rounded-2xl rounded-tl-sm' : 'bg-slate-800 rounded-2xl rounded-tr-sm'} px-4 py-3 max-w-[85%]`;
    bubble.innerHTML = `<p class="text-sm text-slate-300 whitespace-pre-wrap">${escapeHtml(content)}</p>`;
    const time = document.createElement('span');
    time.className = 'text-[10px] text-slate-600 flex-shrink-0 self-end';
    time.textContent = timeStr;
    if (role === 'user') messageDiv.append(time, bubble, avatar);
    else messageDiv.append(avatar, bubble, time);
    container.appendChild(messageDiv);
    container.scrollTop = container.scrollHeight;
    state.chatHistory.push({ role, content, timestamp });
}

export function clearChat() {
    if (!confirm('هل أنت متأكد من مسح المحادثة؟')) return;
    document.getElementById('chat-messages').innerHTML = '';
    state.chatHistory = [];
    addMessage('assistant', 'مرحباً! 👋 أنا مساعدك الذكي لإنشاء فيديوهات...');
}

export function addSuggestion(text) {
    document.getElementById('chat-input').value = text;
    document.getElementById('chat-input').focus();
}

// ---------- واجهة التقدم ----------
export function showProgress(title, percent = 0) {
    const area = document.getElementById('progress-area');
    area.classList.remove('hidden');
    document.getElementById('progress-title').textContent = title;
    document.getElementById('progress-percent').textContent = percent + '%';
    document.getElementById('progress-bar').style.width = percent + '%';
    document.getElementById('progress-status').textContent = 'جاري التهيئة...';
    document.getElementById('progress-detail').textContent = 'في انتظار بدء المعالجة...';
    document.getElementById('video-info-loading').classList.remove('hidden');
    hideProgressWarning();
    hideProgressError();
    state.processing = true;
    state.cancelProcessing = false;
    state.startTime = Date.now();
    setAbortController(new AbortController());
    if (state.progressTimer) clearInterval(state.progressTimer);
    state.progressTimer = setInterval(updateElapsedTime, 1000);
}

export function showProgressWarning(msg) {
    document.getElementById('progress-warning').classList.remove('hidden');
    document.getElementById('progress-warning-text').textContent = msg;
}

export function hideProgressWarning() {
    document.getElementById('progress-warning').classList.add('hidden');
}

export function showProgressError(msg) {
    document.getElementById('progress-error').classList.remove('hidden');
    document.getElementById('progress-error-text').textContent = msg;
}

export function hideProgressError() {
    document.getElementById('progress-error').classList.add('hidden');
}

export function updateElapsedTime() {
    if (!state.startTime) return;
    const elapsed = Math.floor((Date.now() - state.startTime) / 1000);
    const mins = String(Math.floor(elapsed / 60)).padStart(2, '0');
    const secs = String(elapsed % 60).padStart(2, '0');
    document.getElementById('progress-time').textContent = `${mins}:${secs}`;
}

export function hideProgress() {
    document.getElementById('progress-area').classList.add('hidden');
    state.processing = false;
    if (state.progressTimer) {
        clearInterval(state.progressTimer);
        state.progressTimer = null;
    }
}

export function cancelProcessing() {
    if (!confirm('هل تريد إلغاء المعالجة الجارية؟')) return;
    state.cancelProcessing = true;
    abortCurrentRequest();
    showToast('تم إلغاء المعالجة', 'warning');
    hideProgress();
    addMessage('assistant', '⏹️ تم إلغاء المعالجة بناءً على طلبك.');
}

export function updateLoadingVideoInfo(format, size, duration, dimensions) {
    document.getElementById('loading-format').textContent = format;
    document.getElementById('loading-size').textContent = size;
    document.getElementById('loading-duration').textContent = duration;
    document.getElementById('loading-dimensions').textContent = dimensions;
}

// ---------- الاتصال والتهيئة ----------
export async function checkConnection() {
    const status = document.getElementById('connection-status');
    const text = document.getElementById('connection-text');
    try {
        const response = await fetch('/api/v1/projects/video/health', {
            method: 'GET',
            signal: AbortSignal.timeout(5000)
        });
        if (response.ok) {
            const data = await response.json();
            status.className = 'w-3 h-3 bg-green-500 rounded-full animate-pulse';
            text.textContent = 'متصل';
            text.className = 'text-xs text-green-400';
            if (data.youtube_authenticated) {
                state.isYoutubeAuth = true;
                document.getElementById('auth-status').textContent = '✅ مسجل';
                document.getElementById('auth-status').className = 'text-xs text-green-400';
            }
        } else throw new Error('Server error');
    } catch (error) {
        status.className = 'w-3 h-3 bg-red-500 rounded-full';
        text.textContent = 'غير متصل';
        text.className = 'text-xs text-red-400';
    }
}

export function initSession() {
    state.sessionId = 'session_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
}
