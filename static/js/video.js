// ============================================
// video.js — كل ما يتعلق بالفيديو
// ============================================

import {
    state, getAbortController,
    EXTERNAL_PLATFORMS, FALLBACK_VIDEO_URL, MAX_VIDEO_SIZE,
    addMessage, showToast, escapeHtml,
    formatDuration, formatNumber, formatFileSize,
    showProgress, hideProgress, showProgressWarning,
    hideProgressWarning, hideProgressError, showProgressError,
    updateLoadingVideoInfo
} from './app.js';

// ---------- إدارة الروابط ----------
export function addVideoLink() {
    const input = document.getElementById('url-input');
    const url = input.value.trim();
    if (!url) return showToast('الرجاء إدخال رابط صحيح', 'warning');
    if (!url.startsWith('http://') && !url.startsWith('https://'))
        return showToast('الرجاء إدخال رابط صحيح يبدأ بـ http:// أو https://', 'warning');

    let siteName = 'فيديو';
    try {
        siteName = new URL(url).hostname.replace('www.', '').split('.')[0];
    } catch (e) {}

    state.videoLinks.push(url);
    updateVideoLinksUI();
    input.value = '';
    addMessage('user', `📎 أضفت رابط فيديو من ${siteName}: ${url}`);
    addMessage('assistant', '✅ تم استلام الرابط! جاري معالجة الفيديو...');
    processVideoLink(url);
}

export function updateVideoLinksUI() {
    const container = document.getElementById('video-links-container');
    const list = document.getElementById('video-links-list');
    if (state.videoLinks.length === 0) return container.classList.add('hidden');
    container.classList.remove('hidden');
    list.innerHTML = state.videoLinks.map((url, i) => `
        <span class="inline-flex items-center gap-1 bg-slate-700/50 rounded-full px-3 py-1 text-xs text-slate-300">
            🔗 ${escapeHtml(url.length > 40 ? url.substring(0, 40) + '...' : url)}
            <button onclick="removeVideoLink(${i})" class="text-slate-400 hover:text-red-400 transition">
                <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                </svg>
            </button>
        </span>`).join('');
}

export function removeVideoLink(index) {
    state.videoLinks.splice(index, 1);
    updateVideoLinksUI();
    showToast('تم حذف الرابط', 'info');
}

// ---------- رفع فيديو من الجهاز ----------
export function uploadVideoFile(event) {
    const file = event.target.files[0];
    if (!file) return;
    if (file.size > MAX_VIDEO_SIZE) return showToast('⚠️ حجم الفيديو كبير جداً. الحد الأقصى 100MB', 'warning');

    document.getElementById('file-name').textContent = file.name;
    state.uploadedFile = file;

    const reader = new FileReader();
    reader.onload = function (e) {
        const videoUrl = e.target.result;
        showPreviewWithInfo(videoUrl, {
            url: videoUrl, title: file.name, duration: 0,
            format: file.type.split('/')[1] || 'mp4',
            size: formatFileSize(file.size), dimensions: '—',
            uploaded: true, file
        });
        state.generatedVideo = {
            url: videoUrl, original_url: videoUrl,
            data: {
                title: file.name, description: 'فيديو مرفوع من المستخدم',
                duration: 0, format: file.type.split('/')[1] || 'mp4',
                size: formatFileSize(file.size), dimensions: '—',
                uploaded: true, file
            },
            links: state.videoLinks, session_id: state.sessionId
        };
        showToast('✅ تم تحميل الفيديو بنجاح!', 'success');
        addMessage('assistant', '🎬 تم استلام الفيديو من جهازك! يمكنك معاينته أدناه.');
    };
    reader.readAsDataURL(file);
}

// ---------- معالجة الفيديو ----------
export async function processVideoLink(url) {
    showProgress('جاري تحليل رابط الفيديو...', 5);
    hideProgressWarning();
    hideProgressError();

    try {
        const response = await fetch('/api/v1/projects/video/process', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url, session_id: state.sessionId, use_auth: state.isYoutubeAuth }),
            signal: getAbortController()?.signal
        });

        if (!response.ok) {
            let msg = 'فشل معالجة الفيديو';
            try { msg = (await response.json()).detail || msg; }
            catch (e) { msg = `خطأ ${response.status}: ${response.statusText}`; }
            throw new Error(msg);
        }

        const data = await response.json();
        state.processingSessionId = data.session_id;
        state.videoData = data;

        if (data.analysis) {
            updateLoadingVideoInfo(
                data.analysis.format || '—', data.analysis.size || '—',
                data.analysis.duration ? formatDuration(data.analysis.duration) : '—',
                data.analysis.dimensions || '—'
            );
            if (data.analysis.uploader || data.analysis.view_count) {
                document.getElementById('loading-extra-info').classList.remove('hidden');
                document.getElementById('loading-uploader').textContent = data.analysis.uploader || '—';
                document.getElementById('loading-views').textContent = data.analysis.view_count ? formatNumber(data.analysis.view_count) : '—';
            }
            if (data.analysis.title) document.getElementById('progress-title').textContent = '🎬 ' + data.analysis.title;
            if (data.analysis.warning) showProgressWarning(data.analysis.warning);
        }

        await pollProcessingStatus(state.processingSessionId);
    } catch (error) {
        if (error.name === 'AbortError') return;
        hideProgress();
        showToast('❌ فشل معالجة الفيديو: ' + error.message, 'error');
        addMessage('assistant', `❌ عذراً، فشلت معالجة الفيديو: ${error.message}`);
    }
}

export async function pollProcessingStatus(sessionId) {
    let attempts = 0;
    while (attempts < 60 && !state.cancelProcessing) {
        try {
            const response = await fetch(`/api/v1/projects/video/process/${sessionId}/status`,
                { signal: getAbortController()?.signal });
            if (!response.ok) {
                await new Promise(r => setTimeout(r, 2000));
                attempts++;
                continue;
            }
            const status = await response.json();
            if (status.progress !== undefined) updateProgressUI(status);

            if (status.completed) {
                if (status.error) { showProgressError('❌ ' + status.error); throw new Error(status.error); }
                const platform = (status.platform || '').toLowerCase();
                const isExternal = EXTERNAL_PLATFORMS.includes(platform);
                let videoUrl = status.video_url || status.download?.path || null;
                const originalUrl = status.original_url || status.video_url || null;
                if (!videoUrl && originalUrl) videoUrl = originalUrl;

                showPreviewWithInfo(videoUrl, {
                    url: videoUrl, title: status.title || 'فيديو معالج',
                    duration: status.duration || 0, format: status.format || 'mp4',
                    size: status.size || '—', dimensions: status.dimensions || '—',
                    uploader: status.uploader, view_count: status.view_count,
                    like_count: status.like_count, description: status.description,
                    thumbnail: status.thumbnail, warning: status.warning,
                    processed: true, session_id: sessionId, platform, isExternal,
                    original_url: originalUrl, download: status.download || null,
                    video_id: status.video_id, published_at: status.published_at,
                    use_auth: status.use_auth
                });
                hideProgress();
                showToast('✅ تم معالجة الفيديو بنجاح!', 'success');
                addMessage('assistant', '🎬 تم معالجة الفيديو بنجاح! يمكنك معاينته أدناه.');
                return;
            }
            if (status.status === 'failed') {
                showProgressError('❌ ' + (status.detail || 'فشلت المعالجة'));
                throw new Error(status.detail || 'فشلت المعالجة');
            }
        } catch (error) {
            if (error.name === 'AbortError') return;
            if (error.message && error.message.includes('فشل')) throw error;
        }
        await new Promise(r => setTimeout(r, 1500));
        attempts++;
    }
    if (state.cancelProcessing) return;
    showProgressError('⏰ انتهى وقت المعالجة.');
    throw new Error('انتهى وقت المعالجة.');
}

// ---------- توليد الفيديو ----------
export async function generateVideoFromPrompt(prompt) {
    showProgress('جاري توليد الفيديو...', 5);
    hideProgressWarning();
    hideProgressError();
    try {
        const response = await fetch('/api/v1/projects/video/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt, session_id: state.sessionId, links: state.videoLinks }),
            signal: getAbortController()?.signal
        });
        if (!response.ok) {
            let msg = 'فشل توليد الفيديو';
            try { msg = (await response.json()).detail || msg; }
            catch (e) { msg = `خطأ ${response.status}`; }
            throw new Error(msg);
        }
        const data = await response.json();
        state.processingSessionId = data.session_id;
        await pollGenerationStatus(state.processingSessionId, prompt);
    } catch (error) {
        if (error.name === 'AbortError') return;
        hideProgress();
        showToast('❌ فشل توليد الفيديو: ' + error.message, 'error');
        addMessage('assistant', `❌ عذراً، فشل توليد الفيديو: ${error.message}`);
    }
}

export async function pollGenerationStatus(sessionId, prompt) {
    let attempts = 0;
    while (attempts < 90 && !state.cancelProcessing) {
        try {
            const response = await fetch(`/api/v1/projects/video/generate/${sessionId}/status`,
                { signal: getAbortController()?.signal });
            if (!response.ok) {
                await new Promise(r => setTimeout(r, 2000));
                attempts++;
                continue;
            }
            const status = await response.json();
            if (status.progress !== undefined) updateProgressUI(status);

            if (status.completed) {
                if (status.error) { showProgressError('❌ ' + status.error); throw new Error(status.error); }
                const videoUrl = status.video_url || FALLBACK_VIDEO_URL;
                showPreviewWithInfo(videoUrl, {
                    url: videoUrl, title: status.title || 'فيديو مولد',
                    description: prompt, duration: status.duration || 0,
                    format: status.format || 'mp4', size: status.size || '—',
                    dimensions: status.dimensions || '—', generated: true,
                    session_id: sessionId, download: status.download || null,
                    original_url: status.video_url
                });
                hideProgress();
                showToast('✅ تم توليد الفيديو بنجاح!', 'success');
                addMessage('assistant', '🎬 تم توليد الفيديو بناءً على طلبك!');
                return;
            }
            if (status.status === 'failed') {
                showProgressError('❌ ' + (status.detail || 'فشل التوليد'));
                throw new Error(status.detail || 'فشل التوليد');
            }
        } catch (error) {
            if (error.name === 'AbortError') return;
            if (error.message && error.message.includes('فشل')) throw error;
        }
        await new Promise(r => setTimeout(r, 1500));
        attempts++;
    }
    if (state.cancelProcessing) return;
    showProgressError('⏰ انتهى وقت التوليد.');
    throw new Error('انتهى وقت التوليد.');
}

// ---------- دالة مساعدة للتقدم ----------
function updateProgressUI(status) {
    const percent = status.progress || 0;
    document.getElementById('progress-percent').textContent = percent + '%';
    document.getElementById('progress-bar').style.width = percent + '%';
    if (status.step) document.getElementById('progress-status').textContent = status.step;
    if (status.detail) document.getElementById('progress-detail').textContent = status.detail;
    if (status.title) document.getElementById('progress-title').textContent = '🎬 ' + status.title;
    if (status.format || status.size || status.duration || status.dimensions) {
        document.getElementById('loading-format').textContent = status.format || '—';
        document.getElementById('loading-size').textContent = status.size || '—';
        document.getElementById('loading-duration').textContent = status.duration ? formatDuration(status.duration) : '—';
        document.getElementById('loading-dimensions').textContent = status.dimensions || '—';
        document.getElementById('video-info-loading').classList.remove('hidden');
    }
    if (status.uploader || status.view_count) {
        document.getElementById('loading-extra-info').classList.remove('hidden');
        document.getElementById('loading-uploader').textContent = status.uploader || '—';
        document.getElementById('loading-views').textContent = status.view_count ? formatNumber(status.view_count) : '—';
    }
    if (status.warning) showProgressWarning(status.warning);
}

// ---------- المعاينة ----------
export function showPreviewWithInfo(videoUrl, videoData) {
    const previewArea = document.getElementById('preview-area');
    const video = document.getElementById('video-preview');
    const source = document.getElementById('video-source');
    const overlay = document.getElementById('loading-overlay');
    const loadingText = document.getElementById('loading-text');
    const loadingProgress = document.getElementById('loading-progress');

    previewArea.classList.remove('hidden');
    overlay.classList.remove('hidden');
    loadingText.textContent = 'جاري تحميل الفيديو...';
    loadingProgress.textContent = '0%';

    let finalVideoUrl = videoUrl;
    let useFallback = false;
    const canPreview = !(videoData.isExternal && !videoData.download?.path && !videoData.processed);

    if (!canPreview || !finalVideoUrl) {
        finalVideoUrl = FALLBACK_VIDEO_URL;
        useFallback = true;
        setTimeout(() => {
            document.getElementById('video-warning').classList.remove('hidden');
            document.getElementById('video-warning-text').textContent =
                '⚠️ لا يمكن معاينة الفيديو مباشرة (منصة خارجية). يمكنك تنزيله أو فتح الرابط الأصلي.';
        }, 500);
    }

    source.src = finalVideoUrl;
    video.load();

    document.getElementById('video-format').textContent = videoData.format || 'mp4';
    document.getElementById('video-size').textContent = videoData.size || '—';
    document.getElementById('video-duration').textContent = videoData.duration ? formatDuration(videoData.duration) : '—';
    document.getElementById('video-dimensions').textContent = videoData.dimensions || '—';

    if (videoData.uploader || videoData.view_count || videoData.like_count) {
        document.getElementById('video-extra-info').classList.remove('hidden');
        document.getElementById('video-uploader').textContent = videoData.uploader || '—';
        document.getElementById('video-views').textContent = videoData.view_count ? formatNumber(videoData.view_count) : '—';
        document.getElementById('video-likes').textContent = videoData.like_count ? formatNumber(videoData.like_count) : '—';
    } else document.getElementById('video-extra-info').classList.add('hidden');

    if (videoData.video_id || videoData.published_at) {
        document.getElementById('video-youtube-info').classList.remove('hidden');
        document.getElementById('video-id').textContent = videoData.video_id || '—';
        document.getElementById('video-published').textContent = videoData.published_at
            ? new Date(videoData.published_at).toLocaleDateString('ar-SA') : '—';
    } else document.getElementById('video-youtube-info').classList.add('hidden');

    if (videoData.warning) {
        document.getElementById('video-warning').classList.remove('hidden');
        document.getElementById('video-warning-text').textContent = '⚠️ ' + videoData.warning;
    } else if (!useFallback) hideWarning();

    if (videoData.description) {
        document.getElementById('video-description').classList.remove('hidden');
        document.getElementById('video-description-text').textContent = videoData.description;
    } else document.getElementById('video-description').classList.add('hidden');

    setupDownloadSection(videoData, finalVideoUrl);

    state.generatedVideo = {
        url: finalVideoUrl,
        original_url: videoData.original_url || videoUrl,
        data: videoData, links: state.videoLinks,
        session_id: videoData.session_id
    };

    video.addEventListener('loadedmetadata', function () {
        if (this.duration && !isNaN(this.duration) && this.duration > 0) {
            document.getElementById('video-duration').textContent = formatDuration(this.duration);
            if (state.generatedVideo) state.generatedVideo.data.duration = this.duration;
        }
        if (this.videoWidth && this.videoHeight) {
            const dim = `${this.videoWidth}×${this.videoHeight}`;
            document.getElementById('video-dimensions').textContent = dim;
            if (state.generatedVideo) state.generatedVideo.data.dimensions = dim;
        }
        overlay.classList.add('hidden');
    });

    video.addEventListener('progress', function () {
        if (this.buffered.length > 0) {
            const buffered = this.buffered.end(0);
            const duration = this.duration;
            if (duration > 0 && !isNaN(duration)) {
                const percent = Math.min(Math.round((buffered / duration) * 100), 100);
                loadingProgress.textContent = percent + '%';
                if (percent >= 100) loadingText.textContent = 'اكتمل التحميل!';
            }
        }
    });

    video.onerror = function () {
        overlay.classList.add('hidden');
        if (finalVideoUrl !== FALLBACK_VIDEO_URL) {
            showToast('⚠️ تعذر تحميل الفيديو، جاري استخدام فيديو تجريبي', 'warning');
            source.src = FALLBACK_VIDEO_URL;
            video.load();
        } else showToast('⚠️ تعذر تحميل معاينة الفيديو', 'warning');
    };

    previewArea.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

export function hideWarning() {
    document.getElementById('video-warning').classList.add('hidden');
}

export function hidePreview() {
    document.getElementById('preview-area').classList.add('hidden');
    state.generatedVideo = null;
}

export function cancelPreview() {
    hidePreview();
    showToast('تم إلغاء المعاينة', 'info');
}

// ---------- التنزيل ----------
export function setupDownloadSection(videoData, previewUrl) {
    const section = document.getElementById('video-download');
    const link = document.getElementById('video-download-link');
    const size = document.getElementById('video-download-size');
    const openBtn = document.getElementById('open-original-btn');

    if (!section) return;
    section.classList.remove('hidden');
    link.classList.remove('hidden');
    if (openBtn) openBtn.classList.add('hidden');

    const downloadPath = videoData.download?.path;
    const originalUrl = videoData.original_url;

    if (downloadPath) {
        link.href = downloadPath;
        link.setAttribute('download', (videoData.title || 'video') + '.mp4');
        link.onclick = null;
        size.textContent = videoData.size || 'حجم غير معروف';
        return;
    }
    if (videoData.uploaded && previewUrl) {
        link.href = previewUrl;
        link.setAttribute('download', videoData.title || 'video.mp4');
        link.onclick = null;
        size.textContent = videoData.size || '—';
        return;
    }
    if (originalUrl && videoData.isExternal) {
        link.classList.add('hidden');
        size.textContent = 'يتطلب فتح الرابط الأصلي';
        if (openBtn) {
            openBtn.classList.remove('hidden');
            openBtn.onclick = () => window.open(originalUrl, '_blank', 'noopener,noreferrer');
        }
        return;
    }
    if (previewUrl && !previewUrl.startsWith('data:')) {
        link.href = previewUrl;
        link.setAttribute('download', (videoData.title || 'video') + '.mp4');
        link.onclick = null;
        size.textContent = videoData.size || '—';
        return;
    }
    section.classList.add('hidden');
}

export function openOriginalUrl() {
    const url = state.generatedVideo?.original_url || state.generatedVideo?.url;
    if (url) window.open(url, '_blank', 'noopener,noreferrer');
    else showToast('⚠️ لا يوجد رابط أصلي', 'warning');
}

export async function downloadVideoFile(url, filename) {
    const progressDiv = document.getElementById('download-progress');
    const progressBar = document.getElementById('download-progress-bar');
    const progressText = document.getElementById('download-progress-text');

    if (!progressDiv) {
        const a = document.createElement('a');
        a.href = url; a.download = filename; a.click();
        return;
    }
    try {
        progressDiv.classList.remove('hidden');
        progressBar.style.width = '0%';
        progressText.textContent = 'بدء التنزيل...';
        const response = await fetch(url);
        if (!response.ok) throw new Error('فشل التنزيل');
        const contentLength = response.headers.get('content-length');
        const total = contentLength ? parseInt(contentLength, 10) : 0;
        const reader = response.body.getReader();
        const chunks = [];
        let received = 0;
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            chunks.push(value);
            received += value.length;
            if (total > 0) {
                const percent = Math.round((received / total) * 100);
                progressBar.style.width = percent + '%';
                progressText.textContent = `${percent}% (${formatFileSize(received)} / ${formatFileSize(total)})`;
            } else progressText.textContent = formatFileSize(received);
        }
        const blob = new Blob(chunks);
        const blobUrl = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = blobUrl; a.download = filename || 'video.mp4';
        document.body.appendChild(a); a.click(); document.body.removeChild(a);
        setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
        progressText.textContent = '✅ اكتمل التنزيل!';
        showToast('✅ تم تنزيل الفيديو بنجاح!', 'success');
        setTimeout(() => progressDiv.classList.add('hidden'), 2000);
    } catch (error) {
        showToast('❌ فشل التنزيل: ' + error.message, 'error');
        progressText.textContent = '❌ فشل التنزيل';
        setTimeout(() => progressDiv.classList.add('hidden'), 3000);
    }
}
