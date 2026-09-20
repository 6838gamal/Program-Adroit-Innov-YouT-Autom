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
    addMessage('assistant', '✅ تم استلام الرابط! جاري جلب معلومات الفيديو...');
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

// ---------- معالجة الفيديو (flow جديد: info → quality → fetch) ----------
export async function processVideoLink(url) {
    showProgress('جاري جلب معلومات الفيديو...', 20);
    hideProgressWarning();
    hideProgressError();

    try {
        const infoRes = await fetch('/api/video/info', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url }),
            signal: getAbortController()?.signal
        });

        if (!infoRes.ok) {
            const err = await infoRes.json().catch(() => ({}));
            throw new Error(err.detail || err.message || 'فشل جلب معلومات الفيديو.');
        }

        const info = await infoRes.json();
        state.pendingVideoUrl    = url;
        state.pendingVideoSource = info.source || 'generic';
        state.pendingFormats     = info.formats || [];

        hideProgress();
        renderQualityPicker(info);

    } catch (error) {
        if (error.name === 'AbortError') return;
        hideProgress();
        showToast('❌ ' + error.message, 'error');
        addMessage('assistant', `❌ فشل جلب معلومات الفيديو: ${error.message}`);
    }
}

// ---------- عرض قائمة الجودات ----------
export function renderQualityPicker(info) {
    const card       = document.getElementById('quality-card');
    const list       = document.getElementById('quality-list');
    const titleEl    = document.getElementById('info-title');
    const sourceEl   = document.getElementById('info-source');
    const durationEl = document.getElementById('info-duration');

    if (!card || !list) return downloadSelectedQuality(null);

    titleEl.textContent    = info.title || '—';
    sourceEl.textContent   = 'المصدر: ' + (info.source === 'youtube' ? 'YouTube' : 'عام');
    durationEl.textContent = 'المدة: ' + (info.duration ? formatDuration(info.duration) : '—');

    list.innerHTML = `
        <label class="flex items-center gap-3 p-3 bg-slate-800/50 border border-slate-700 rounded-lg cursor-pointer hover:border-indigo-500 transition">
            <input type="radio" name="quality" value="__auto__" class="accent-indigo-500" checked>
            <div class="flex-1">
                <p class="text-sm text-white font-medium">تلقائي (أفضل جودة)</p>
                <p class="text-xs text-slate-500">سيتم اختيار الأفضل تلقائياً</p>
            </div>
        </label>
    `;

    (info.formats || []).forEach(f => {
        const size  = f.filesize ? formatFileSize(f.filesize) : '';
        const audio = f.has_audio ? '🎵 صوت مدموج' : '🎬 فيديو فقط';
        list.innerHTML += `
            <label class="flex items-center gap-3 p-3 bg-slate-800/50 border border-slate-700 rounded-lg cursor-pointer hover:border-indigo-500 transition">
                <input type="radio" name="quality" value="${f.format_id}" class="accent-indigo-500">
                <div class="flex-1">
                    <p class="text-sm text-white font-medium">${escapeHtml(f.label)} • ${(f.ext || 'mp4').toUpperCase()}</p>
                    <p class="text-xs text-slate-500">${audio}${size ? ' • ' + size : ''}</p>
                </div>
            </label>
        `;
    });

    card.classList.remove('hidden');
    card.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

// ---------- تنزيل الجودة المختارة + عرض المعاينة ----------
export async function downloadSelectedQuality(formatId) {
    const qualityCard = document.getElementById('quality-card');
    const url         = state.pendingVideoUrl;
    const source      = state.pendingVideoSource;

    if (!url) return showToast('⚠️ لا يوجد رابط معلّق', 'warning');

    if (formatId === undefined) {
        const checked = document.querySelector('input[name="quality"]:checked');
        formatId = (checked && checked.value !== '__auto__') ? checked.value : null;
    }

    showProgress('جاري تنزيل الفيديو...', 25);
    if (qualityCard) qualityCard.classList.add('hidden');

    try {
        const res = await fetch('/api/video/fetch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url, format_id: formatId, source }),
            signal: getAbortController()?.signal
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || err.message || 'فشل تنزيل الفيديو.');
        }

        const data = await res.json();
        hideProgress();

        state.currentDownloadData = data;

        const previewUrl = data.preview_url || data.url || data.download_url;

        showPreviewWithInfo(previewUrl, {
            url: data.url || previewUrl,
            original_url: data.url || previewUrl,
            title: data.title || 'فيديو',
            description: data.description || '',
            duration: data.duration || 0,
            format: data.format || (data.filename || '').split('.').pop() || 'mp4',
            size: data.size ? formatFileSize(data.size) : '—',
            dimensions: data.dimensions || '—',
            uploader: data.uploader || null,
            view_count: data.view_count || null,
            like_count: data.like_count || null,
            thumbnail: data.thumbnail || null,
            published_at: data.published_at || null,
            video_id: data.video_id || null,
            processed: true,
            platform: source,
            isExternal: source === 'youtube' || source === 'generic',
            download: {
                path: data.download_url || data.url || previewUrl,
                filename: data.filename || (data.title || 'video') + '.mp4'
            },
            session_id: state.sessionId
        });

        addMessage('assistant', '🎬 تم تنزيل الفيديو بنجاح! يمكنك معاينته وتنزيله أدناه.');
        showToast('✅ تم التنزيل بنجاح!', 'success');

    } catch (error) {
        if (error.name === 'AbortError') return;
        hideProgress();
        showToast('❌ ' + error.message, 'error');
        addMessage('assistant', `❌ فشل التنزيل: ${error.message}`);
    }
}

// ---------- إلغاء قائمة الجودات ----------
export function cancelQualityPicker() {
    const card = document.getElementById('quality-card');
    if (card) card.classList.add('hidden');
    state.pendingVideoUrl = null;
    state.pendingVideoSource = null;
    state.pendingFormats = [];
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
    const filename = videoData.download?.filename
        || (videoData.title || 'video') + '.mp4';

    // 1) رابط تنزيل مباشر من السيرفر
    if (downloadPath) {
        bindDownloadButton(link, downloadPath, filename);
        size.textContent = videoData.size || 'حجم غير معروف';
        return;
    }

    // 2) فيديو مرفوع من المستخدم
    if (videoData.uploaded && previewUrl) {
        bindDownloadButton(link, previewUrl, filename);
        size.textContent = videoData.size || '—';
        return;
    }

    // 3) منصة خارجية بدون تنزيل مباشر
    if (originalUrl && videoData.isExternal) {
        link.classList.add('hidden');
        size.textContent = 'يتطلب فتح الرابط الأصلي';
        if (openBtn) {
            openBtn.classList.remove('hidden');
            openBtn.onclick = () => window.open(originalUrl, '_blank', 'noopener,noreferrer');
        }
        return;
    }

    // 4) رابط معاينة عادي
    if (previewUrl && !previewUrl.startsWith('data:')) {
        bindDownloadButton(link, previewUrl, filename);
        size.textContent = videoData.size || '—';
        return;
    }

    section.classList.add('hidden');
}

// ربط زر التنزيل بالدالة الصحيحة
function bindDownloadButton(link, url, filename) {
    link.href = url;
    link.setAttribute('download', filename);
    link.onclick = (e) => {
        e.preventDefault();
        downloadVideoFile(url, filename);
    };
}

export function openOriginalUrl() {
    const url = state.generatedVideo?.original_url || state.generatedVideo?.url;
    if (url) window.open(url, '_blank', 'noopener,noreferrer');
    else showToast('⚠️ لا يوجد رابط أصلي', 'warning');
}

// ---------- تنزيل الفيديو (مع دعم CORS/fallback) ----------
export async function downloadVideoFile(url, filename) {
    const progressDiv = document.getElementById('download-progress');
    const progressBar = document.getElementById('download-progress-bar');
    const progressText = document.getElementById('download-progress-text');

    if (!progressDiv) {
        triggerNativeDownload(url, filename);
        return;
    }

    try {
        progressDiv.classList.remove('hidden');
        progressBar.style.width = '0%';
        progressText.textContent = 'بدء التنزيل...';

        const response = await fetch(url, { mode: 'cors' });
        if (!response.ok) throw new Error('فشل التنزيل: ' + response.status);

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
            } else {
                progressText.textContent = formatFileSize(received);
            }
        }

        const blob = new Blob(chunks);
        const blobUrl = URL.createObjectURL(blob);
        triggerNativeDownload(blobUrl, filename || 'video.mp4');
        setTimeout(() => URL.revokeObjectURL(blobUrl), 1500);

        progressText.textContent = '✅ اكتمل التنزيل!';
        showToast('✅ تم تنزيل الفيديو بنجاح!', 'success');
        setTimeout(() => progressDiv.classList.add('hidden'), 2000);

    } catch (error) {
        console.warn('fetch download failed, falling back:', error);
        progressText.textContent = '⚠️ جارٍ التنزيل بطريقة بديلة...';
        triggerNativeDownload(url, filename || 'video.mp4');
        setTimeout(() => progressDiv.classList.add('hidden'), 2000);
        showToast('ℹ️ تم بدء التنزيل عبر المتصفح', 'info');
    }
}

// تنزيل أصلي عبر المتصفح
function triggerNativeDownload(url, filename) {
    const a = document.createElement('a');
    a.href = url;
    a.download = filename || 'video.mp4';
    a.rel = 'noopener';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}
