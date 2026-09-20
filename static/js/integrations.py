// ============================================
// integrations.js — YouTube + Projects + Events
// ============================================

import { state, showToast, addMessage, formatNumber, formatDuration } from './app.js';
import { generateVideoFromPrompt, addVideoLink } from './video.js';

// ---------- YouTube OAuth ----------
export async function handleYouTubeAuth() {
    try {
        const response = await fetch('/api/v1/youtube/auth/url');
        if (!response.ok) throw new Error('فشل الحصول على رابط المصادقة');
        const data = await response.json();

        if (data.auth_url) {
            window.open(data.auth_url, '_blank', 'width=600,height=700');
            showToast('🔑 افتح النافذة المنبثقة للمصادقة', 'info');

            let attempts = 0;
            const checkInterval = setInterval(async () => {
                attempts++;
                try {
                    const statusResponse = await fetch(`/api/v1/youtube/auth/status?user_id=${state.sessionId}`);
                    if (statusResponse.ok) {
                        const statusData = await statusResponse.json();
                        if (statusData.authenticated) {
                            clearInterval(checkInterval);
                            state.isYoutubeAuth = true;
                            document.getElementById('auth-status').textContent = '✅ مسجل';
                            document.getElementById('auth-status').className = 'text-xs text-green-400';
                            showToast('✅ تم تسجيل الدخول إلى يوتيوب بنجاح!', 'success');
                            addMessage('assistant', '🔑 تم تسجيل الدخول إلى يوتيوب بنجاح!');
                        }
                    }
                } catch (e) {}
                if (attempts > 30) {
                    clearInterval(checkInterval);
                    if (!state.isYoutubeAuth) showToast('⏰ انتهى وقت المصادقة.', 'warning');
                }
            }, 1000);
        }
    } catch (error) {
        showToast('❌ فشل المصادقة: ' + error.message, 'error');
    }
}

// ---------- YouTube: فيديوهاتي ----------
export async function loadMyVideos() {
    try {
        showProgress('جاري تحميل فيديوهاتك...', 10);
        const response = await fetch('/api/v1/youtube/my/videos?max_results=10');
        if (!response.ok) {
            if (response.status === 401) {
                showToast('⚠️ يرجى تسجيل الدخول أولاً', 'warning');
                hideProgress();
                handleYouTubeAuth();
                return;
            }
            throw new Error('فشل تحميل الفيديوهات');
        }
        const data = await response.json();
        hideProgress();
        if (data.videos && data.videos.length > 0) {
            addMessage('assistant', `📂 لديك ${data.videos.length} فيديو مرفوع:`);
            data.videos.forEach(video => {
                addMessage('assistant',
                    `🎬 ${video.title}\n👤 ${video.channel_title || 'غير معروف'}\n` +
                    `👁️ ${formatNumber(video.view_count)} مشاهدات\n` +
                    `⏱️ ${formatDuration(video.duration)}\n🔗 https://youtube.com/watch?v=${video.video_id}`);
            });
        } else addMessage('assistant', '📭 لا توجد فيديوهات مرفوعة.');
    } catch (error) {
        hideProgress();
        showToast('❌ ' + error.message, 'error');
    }
}

// ---------- YouTube: اشتراكاتي ----------
export async function loadMySubscriptions() {
    try {
        showProgress('جاري تحميل القنوات المشترك فيها...', 10);
        const response = await fetch('/api/v1/youtube/my/subscriptions?max_results=10');
        if (!response.ok) {
            if (response.status === 401) {
                showToast('⚠️ يرجى تسجيل الدخول أولاً', 'warning');
                hideProgress();
                handleYouTubeAuth();
                return;
            }
            throw new Error('فشل تحميل القنوات');
        }
        const data = await response.json();
        hideProgress();
        if (data.subscriptions && data.subscriptions.length > 0) {
            addMessage('assistant', `📺 أنت مشترك في ${data.subscriptions.length} قناة:`);
            data.subscriptions.forEach(sub => {
                addMessage('assistant', `📺 ${sub.title}\n🆔 ${sub.channel_id}`);
            });
        } else addMessage('assistant', '📭 لا توجد قنوات مشترك فيها.');
    } catch (error) {
        hideProgress();
        showToast('❌ ' + error.message, 'error');
    }
}

// ---------- YouTube: البحث ----------
export async function searchYouTube() {
    const query = window.prompt('🔍 أدخل كلمة البحث:');
    if (!query) return;
    try {
        showProgress(`جاري البحث عن: ${query}...`, 10);
        const response = await fetch('/api/v1/youtube/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query, max_results: 5 })
        });
        if (!response.ok) throw new Error('فشل البحث');
        const data = await response.json();
        hideProgress();
        if (data.videos && data.videos.length > 0) {
            addMessage('assistant', `🔍 نتائج البحث عن "${query}":`);
            data.videos.forEach(video => {
                addMessage('assistant', `🎬 ${video.title}\n👤 ${video.channel_title}\n🔗 ${video.url}`);
            });
        } else addMessage('assistant', '📭 لا توجد نتائج.');
    } catch (error) {
        hideProgress();
        showToast('❌ ' + error.message, 'error');
    }
}

// ---------- المشروع ----------
export async function confirmProject() {
    if (!state.generatedVideo) return showToast('⚠️ لا يوجد فيديو لتأكيده', 'warning');

    const confirmBtn = document.getElementById('confirm-btn');
    confirmBtn.disabled = true;
    confirmBtn.innerHTML = '<div class="spinner-sm"></div> جاري الحفظ...';

    try {
        const projectData = {
            title: state.generatedVideo.data.title || 'فيديو جديد',
            description: state.generatedVideo.data.description || 'تم إنشاؤه عبر الذكاء الاصطناعي',
            script: buildScriptFromChat(),
            tags: ['ai-generated', ...state.videoLinks.map(() => 'video-source')],
            video_url: state.generatedVideo.original_url || state.generatedVideo.url,
            video_links: state.videoLinks,
            duration: state.generatedVideo.data.duration || 0,
            format: state.generatedVideo.data.format || 'mp4',
            dimensions: state.generatedVideo.data.dimensions || '',
            uploader: state.generatedVideo.data.uploader || '',
            view_count: state.generatedVideo.data.view_count || 0,
            like_count: state.generatedVideo.data.like_count || 0,
            status: 'rendered',
            session_id: state.sessionId,
            thumbnail: state.generatedVideo.data.thumbnail || null,
            video_id: state.generatedVideo.data.video_id || null,
            platform: state.generatedVideo.data.platform || 'generic'
        };
        const response = await fetch('/api/v1/projects', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(projectData)
        });
        if (!response.ok) {
            let msg = 'فشل إنشاء المشروع';
            try { msg = (await response.json()).detail || msg; } catch (e) {}
            throw new Error(msg);
        }
        const project = await response.json();
        state.currentProjectId = project.id;
        showToast('✅ تم إنشاء المشروع بنجاح!', 'success');
        window.dispatchEvent(new CustomEvent('projectCreated', { detail: { projectId: project.id, project } }));
        setTimeout(() => window.location.href = `/projects/${project.id}`, 1000);
    } catch (error) {
        showToast('❌ ' + error.message, 'error');
        addMessage('assistant', `❌ عذراً، فشل إنشاء المشروع: ${error.message}`);
    } finally {
        confirmBtn.disabled = false;
        confirmBtn.innerHTML = `
            <svg class="w-4 h-4 inline ml-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
            </svg>
            تأكيد وإنشاء المشروع`;
    }
}

export function buildScriptFromChat() {
    let script = '';
    const userMessages = state.chatHistory.filter(msg => msg.role === 'user');
    if (userMessages.length > 0) script = userMessages.map(msg => `🎬 طلب: ${msg.content}`).join('\n\n');
    if (state.videoLinks.length > 0) {
        script += '\n\n--- مصادر إلهام ---\n';
        state.videoLinks.forEach((url, i) => { script += `${i + 1}. ${url}\n`; });
    }
    return script || 'نص الفيديو المستند إلى المحادثة';
}

// ---------- مستمعو الأحداث ----------
export function setupEventListeners() {
    document.getElementById('chat-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const input = document.getElementById('chat-input');
        const message = input.value.trim();
        if (!message) return;
        input.value = '';
        addMessage('user', message);
        const btn = document.getElementById('send-btn');
        btn.disabled = true;
        btn.innerHTML = '<div class="spinner-sm"></div>';
        try { await generateVideoFromPrompt(message); }
        catch (error) { showToast('❌ حدث خطأ: ' + error.message, 'error'); }
        finally {
            btn.disabled = false;
            btn.innerHTML = `
                <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"/>
                </svg> إرسال`;
        }
    });

    document.getElementById('chat-input').addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            document.getElementById('chat-form').dispatchEvent(new Event('submit'));
        }
    });

    document.getElementById('url-input').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); addVideoLink(); }
    });
}
