// ============================================
// integrations.js — YouTube + Projects + Events
// ============================================

import {
    state, showToast, addMessage,
    formatNumber, formatDuration,
    showProgress, hideProgress
} from './app.js';

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
                            const authStatus = document.getElementById('auth-status');
                            if (authStatus) {
                                authStatus.textContent = '✅ مسجل';
                                authStatus.className = 'text-xs text-green-400';
                            }
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

// ---------- المشروع: تأكيد وإنشاء ----------
export async function confirmProject() {
    // ⭐ دعم حالتين: التنزيل + التوليد
    const downloadData = state.currentDownloadData;
    const generatedData = state.generatedVideo;
    const data = downloadData || generatedData?.data;

    if (!data) {
        return showToast('⚠️ لا يوجد فيديو لتأكيده', 'warning');
    }

    const confirmBtn = document.getElementById('confirm-btn');
    if (confirmBtn) {
        confirmBtn.disabled = true;
        confirmBtn.innerHTML = '<div class="spinner-sm"></div> جاري الحفظ...';
    }

    showProgress('جاري إنشاء المشروع...', 30);

    try {
        let project;

        // ⭐ الحالة 1: التنزيل عبر الرابط (عندنا filename)
        if (downloadData?.filename) {
            // 1) حفظ الفيديو (نقله من preview → downloads)
            const saveRes = await fetch('/api/video/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    url: downloadData.url,
                    title: downloadData.title,
                    filename: downloadData.filename
                })
            });

            if (!saveRes.ok) {
                const err = await saveRes.json().catch(() => ({}));
                throw new Error(err.detail || 'فشل حفظ الفيديو');
            }

            // 2) إنشاء Project (مع رفع Supabase)
            const projRes = await fetch('/api/projects/create-from-video', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    title: downloadData.title || 'مشروع جديد',
                    description: buildScriptFromChat(),
                    script: buildScriptFromChat(),
                    tags: ['video-download', 'ai-project'],
                    filename: downloadData.filename,
                    source: downloadData.source,
                    duration: downloadData.duration,
                    platform: downloadData.platform,
                })
            });

            if (!projRes.ok) {
                const err = await projRes.json().catch(() => ({}));
                throw new Error(err.detail || 'فشل إنشاء المشروع');
            }

            project = await projRes.json();
        }

        // ⭐ الحالة 2: التوليد (الطريقة القديمة)
        else if (generatedData) {
            const projectData = {
                title: generatedData.data.title || 'فيديو جديد',
                description: generatedData.data.description || 'تم إنشاؤه عبر الذكاء الاصطناعي',
                script: buildScriptFromChat(),
                tags: ['ai-generated', ...state.videoLinks.map(() => 'video-source')],
                video_url: generatedData.original_url || generatedData.url,
                video_links: state.videoLinks,
                duration: generatedData.data.duration || 0,
                format: generatedData.data.format || 'mp4',
                dimensions: generatedData.data.dimensions || '',
                uploader: generatedData.data.uploader || '',
                view_count: generatedData.data.view_count || 0,
                like_count: generatedData.data.like_count || 0,
                status: 'rendered',
                session_id: state.sessionId,
                thumbnail: generatedData.data.thumbnail || null,
                video_id: generatedData.data.video_id || null,
                platform: generatedData.data.platform || 'generic'
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

            project = await response.json();
        }

        else {
            throw new Error('لا توجد بيانات كافية لإنشاء المشروع');
        }

        // ⭐ حفظ project_id والانتقال
        state.currentProjectId = project.id || project.project_id;

        hideProgress();
        showToast('✅ تم إنشاء المشروع بنجاح!', 'success');
        addMessage('assistant', '🎬 تم إنشاء المشروع بنجاح! جاري الانتقال...');

        window.dispatchEvent(new CustomEvent('projectCreated', {
            detail: { projectId: state.currentProjectId, project }
        }));

        setTimeout(() => {
            window.location.href = `/projects/${state.currentProjectId}`;
        }, 1000);

    } catch (error) {
        hideProgress();
        showToast('❌ ' + error.message, 'error');
        addMessage('assistant', `❌ عذراً، فشل إنشاء المشروع: ${error.message}`);
    } finally {
        if (confirmBtn) {
            confirmBtn.disabled = false;
            confirmBtn.innerHTML = `
                <svg class="w-4 h-4 inline ml-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
                </svg>
                تأكيد وإنشاء المشروع`;
        }
    }
}

// ---------- بناء السكريبت من الدردشة ----------
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
    const chatForm = document.getElementById('chat-form');
    if (chatForm) {
        chatForm.addEventListener('submit', async (e) => {
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
    }

    const chatInput = document.getElementById('chat-input');
    if (chatInput && chatForm) {
        chatInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                chatForm.dispatchEvent(new Event('submit'));
            }
        });
    }

    const urlInput = document.getElementById('url-input');
    if (urlInput) {
        urlInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); addVideoLink(); }
        });
    }
}
