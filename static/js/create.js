// ============================================
// الحالة العامة
// ============================================
let state = {
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

// ============================================
// وظائف الدردشة
// ============================================
function addMessage(role, content, timestamp = new Date()) {
    const container = document.getElementById('chat-messages');
    const timeStr = timestamp.toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' });
    
    const messageDiv = document.createElement('div');
    messageDiv.className = `flex items-start gap-3 ${role === 'user' ? 'flex-row-reverse' : ''}`;
    
    const avatar = document.createElement('div');
    avatar.className = `w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${
        role === 'user' ? 'bg-blue-600' : 'bg-indigo-600'
    }`;
    avatar.innerHTML = role === 'user' 
        ? '<svg class="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/></svg>'
        : '<svg class="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/></svg>';
    
    const bubble = document.createElement('div');
    bubble.className = `flex-1 ${
        role === 'user' ? 'bg-blue-600/30 rounded-2xl rounded-tl-sm' : 'bg-slate-800 rounded-2xl rounded-tr-sm'
    } px-4 py-3 max-w-[85%]`;
    bubble.innerHTML = `<p class="text-sm text-slate-300 whitespace-pre-wrap">${content}</p>`;
    
    const time = document.createElement('span');
    time.className = 'text-[10px] text-slate-600 flex-shrink-0 self-end';
    time.textContent = timeStr;
    
    if (role === 'user') {
        messageDiv.appendChild(time);
        messageDiv.appendChild(bubble);
        messageDiv.appendChild(avatar);
    } else {
        messageDiv.appendChild(avatar);
        messageDiv.appendChild(bubble);
        messageDiv.appendChild(time);
    }
    
    container.appendChild(messageDiv);
    container.scrollTop = container.scrollHeight;
    state.chatHistory.push({ role, content, timestamp });
}

function clearChat() {
    if (!confirm('هل أنت متأكد من مسح المحادثة؟')) return;
    const container = document.getElementById('chat-messages');
    container.innerHTML = '';
    state.chatHistory = [];
    addMessage('assistant', 'مرحباً! 👋 أنا مساعدك الذكي لإنشاء فيديوهات. أخبرني عن فكرة الفيديو الذي ترغب في إنشائه، أو أضف رابط فيديو من الإنترنت لاستخدامه كمصدر إلهام.\n\n💡 يمكنك أيضاً تحميل فيديو من جهازك مباشرة.\n\n🎬 يدعم يوتيوب، تيك توك، فيسبوك، إنستغرام، Vimeo والمزيد!');
}

function addSuggestion(text) {
    document.getElementById('chat-input').value = text;
    document.getElementById('chat-input').focus();
}

// ============================================
// إدارة الروابط
// ============================================
function addVideoLink() {
    const input = document.getElementById('url-input');
    const url = input.value.trim();
    
    if (!url) {
        showToast('الرجاء إدخال رابط صحيح', 'warning');
        return;
    }
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
        showToast('الرجاء إدخال رابط صحيح يبدأ بـ http:// أو https://', 'warning');
        return;
    }
    
    let siteName = 'فيديو';
    try {
        const urlObj = new URL(url);
        siteName = urlObj.hostname.replace('www.', '').split('.')[0];
    } catch(e) {}
    
    state.videoLinks.push(url);
    updateVideoLinksUI();
    input.value = '';
    
    addMessage('user', `📎 أضفت رابط فيديو من ${siteName}: ${url}`);
    addMessage('assistant', `✅ تم استلام الرابط! جاري معالجة الفيديو...`);
    
    processVideoLink(url);
}

function updateVideoLinksUI() {
    const container = document.getElementById('video-links-container');
    const list = document.getElementById('video-links-list');
    
    if (state.videoLinks.length === 0) {
        container.classList.add('hidden');
        return;
    }
    container.classList.remove('hidden');
    list.innerHTML = state.videoLinks.map((url, index) => `
        <span class="inline-flex items-center gap-1 bg-slate-700/50 rounded-full px-3 py-1 text-xs text-slate-300">
            🔗 ${url.length > 40 ? url.substring(0, 40) + '...' : url}
            <button onclick="removeVideoLink(${index})" class="text-slate-400 hover:text-red-400 transition">
                <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                </svg>
            </button>
        </span>
    `).join('');
}

function removeVideoLink(index) {
    state.videoLinks.splice(index, 1);
    updateVideoLinksUI();
    showToast('تم حذف الرابط', 'info');
}

// ============================================
// تحميل فيديو من جهاز المستخدم
// ============================================
function uploadVideoFile(event) {
    const file = event.target.files[0];
    if (!file) return;
    
    if (file.size > 100 * 1024 * 1024) {
        showToast('⚠️ حجم الفيديو كبير جداً. الحد الأقصى 100MB', 'warning');
        return;
    }
    
    const fileName = document.getElementById('file-name');
    fileName.textContent = file.name;
    
    state.uploadedFile = file;
    
    const reader = new FileReader();
    reader.onload = function(e) {
        const videoUrl = e.target.result;
        
        showPreviewWithInfo(videoUrl, {
            url: videoUrl,
            title: file.name,
            duration: 0,
            format: file.type.split('/')[1] || 'mp4',
            size: formatFileSize(file.size),
            dimensions: '—',
            uploaded: true,
            file: file
        });
        
        state.generatedVideo = {
            url: videoUrl,
            data: {
                title: file.name,
                description: 'فيديو مرفوع من المستخدم',
                duration: 0,
                format: file.type.split('/')[1] || 'mp4',
                size: formatFileSize(file.size),
                dimensions: '—',
                uploaded: true,
                file: file
            },
            links: state.videoLinks,
            session_id: state.sessionId
        };
        
        showToast('✅ تم تحميل الفيديو بنجاح!', 'success');
        addMessage('assistant', '🎬 تم استلام الفيديو من جهازك! يمكنك معاينته أدناه.');
    };
    reader.readAsDataURL(file);
}

function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    return (bytes / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
}

// ============================================
// معالجة الفيديو
// ============================================
async function processVideoLink(url) {
    showProgress('جاري تحليل رابط الفيديو...', 5);
    hideProgressWarning();
    hideProgressError();
    hideWarning();
    
    try {
        const response = await fetch('/api/v1/projects/video/process', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                url: url, 
                session_id: state.sessionId,
                use_auth: state.isYoutubeAuth 
            })
        });
        
        if (!response.ok) {
            let errorMessage = 'فشل معالجة الفيديو';
            try {
                const errorData = await response.json();
                errorMessage = errorData.detail || errorMessage;
            } catch (e) {
                errorMessage = `خطأ ${response.status}: ${response.statusText}`;
            }
            throw new Error(errorMessage);
        }
        
        const data = await response.json();
        state.processingSessionId = data.session_id;
        state.videoData = data;
        
        console.log('✅ بدأت المعالجة، Session ID:', state.processingSessionId);
        console.log('📊 تحليل الفيديو:', data.analysis);
        
        if (data.analysis) {
            updateLoadingVideoInfo(
                data.analysis.format || '—',
                data.analysis.size || '—',
                data.analysis.duration ? formatDuration(data.analysis.duration) : '—',
                data.analysis.dimensions || '—'
            );
            
            if (data.analysis.uploader || data.analysis.view_count) {
                document.getElementById('loading-extra-info').classList.remove('hidden');
                document.getElementById('loading-uploader').textContent = data.analysis.uploader || '—';
                document.getElementById('loading-views').textContent = data.analysis.view_count ? formatNumber(data.analysis.view_count) : '—';
            }
            
            if (data.analysis.title) {
                document.getElementById('progress-title').textContent = '🎬 ' + data.analysis.title;
            }
            
            if (data.analysis.warning) {
                showProgressWarning(data.analysis.warning);
            }
        }
        
        await pollProcessingStatus(state.processingSessionId);
        
    } catch (error) {
        hideProgress();
        showToast('❌ فشل معالجة الفيديو: ' + error.message, 'error');
        addMessage('assistant', `❌ عذراً، فشلت معالجة الفيديو: ${error.message}`);
        console.error('Video processing error:', error);
    }
}

// ============================================
// مراقبة التقدم
// ============================================
async function pollProcessingStatus(sessionId) {
    let attempts = 0;
    const maxAttempts = 60;
    
    console.log('🔄 بدء مراقبة التقدم للجلسة:', sessionId);
    
    while (attempts < maxAttempts && !state.cancelProcessing) {
        try {
            const response = await fetch(`/api/v1/projects/video/process/${sessionId}/status`);
            
            if (!response.ok) {
                console.warn('⚠️ فشل الحصول على الحالة، إعادة المحاولة...');
                await new Promise(resolve => setTimeout(resolve, 2000));
                attempts++;
                continue;
            }
            
            const status = await response.json();
            console.log('📊 حالة المعالجة:', status);
            
            if (status.progress !== undefined) {
                const percent = status.progress || 0;
                document.getElementById('progress-percent').textContent = percent + '%';
                document.getElementById('progress-bar').style.width = percent + '%';
                
                if (status.step) {
                    document.getElementById('progress-status').textContent = status.step;
                }
                if (status.detail) {
                    document.getElementById('progress-detail').textContent = status.detail;
                }
                
                if (status.title) {
                    document.getElementById('progress-title').textContent = '🎬 ' + status.title;
                }
                
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
                
                if (status.warning) {
                    showProgressWarning(status.warning);
                }
            }
            
            if (status.completed) {
                if (status.error) {
                    showProgressError('❌ ' + status.error);
                    throw new Error(status.error);
                }
                
                console.log('✅ اكتملت المعالجة!');
                
                const videoUrl = status.video_url || 'https://sample-videos.com/video321/mp4/240/big_buck_bunny_240p_1mb.mp4';
                const isExternal = status.platform in ['youtube', 'tiktok', 'facebook', 'instagram'];
                
                showPreviewWithInfo(videoUrl, {
                    url: videoUrl,
                    title: status.title || 'فيديو معالج',
                    duration: status.duration || 0,
                    format: status.format || 'mp4',
                    size: status.size || '—',
                    dimensions: status.dimensions || '—',
                    uploader: status.uploader,
                    view_count: status.view_count,
                    like_count: status.like_count,
                    description: status.description,
                    thumbnail: status.thumbnail,
                    warning: status.warning,
                    processed: true,
                    session_id: sessionId,
                    isExternal: isExternal,
                    original_url: status.video_url,
                    download: status.download,
                    video_id: status.video_id,
                    published_at: status.published_at,
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
            if (error.message && error.message.includes('فشل')) {
                throw error;
            }
            console.warn('⚠️ خطأ في جلب الحالة:', error);
        }
        
        await new Promise(resolve => setTimeout(resolve, 1500));
        attempts++;
    }
    
    if (state.cancelProcessing) {
        console.log('⏹️ تم إلغاء المعالجة');
        return;
    }
    
    console.error('⏰ انتهى وقت المعالجة');
    showProgressError('⏰ انتهى وقت المعالجة. يرجى المحاولة مرة أخرى.');
    throw new Error('انتهى وقت المعالجة. يرجى المحاولة مرة أخرى.');
}

// ============================================
// توليد فيديو من البرومبت
// ============================================
async function generateVideoFromPrompt(prompt) {
    showProgress('جاري توليد الفيديو...', 5);
    hideProgressWarning();
    hideProgressError();
    
    try {
        const response = await fetch('/api/v1/projects/video/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                prompt: prompt,
                session_id: state.sessionId,
                links: state.videoLinks
            })
        });
        
        if (!response.ok) {
            let errorMessage = 'فشل توليد الفيديو';
            try {
                const errorData = await response.json();
                errorMessage = errorData.detail || errorMessage;
            } catch (e) {
                errorMessage = `خطأ ${response.status}: ${response.statusText}`;
            }
            throw new Error(errorMessage);
        }
        
        const data = await response.json();
        state.processingSessionId = data.session_id;
        console.log('✅ بدأ التوليد، Session ID:', state.processingSessionId);
        
        await pollGenerationStatus(state.processingSessionId);
        
    } catch (error) {
        hideProgress();
        showToast('❌ فشل توليد الفيديو: ' + error.message, 'error');
        addMessage('assistant', `❌ عذراً، فشل توليد الفيديو: ${error.message}`);
        console.error('Video generation error:', error);
    }
}

// ============================================
// مراقبة حالة التوليد
// ============================================
async function pollGenerationStatus(sessionId) {
    let attempts = 0;
    const maxAttempts = 90;
    
    console.log('🔄 بدء مراقبة التوليد للجلسة:', sessionId);
    
    while (attempts < maxAttempts && !state.cancelProcessing) {
        try {
            const response = await fetch(`/api/v1/projects/video/generate/${sessionId}/status`);
            
            if (!response.ok) {
                console.warn('⚠️ فشل الحصول على حالة التوليد، إعادة المحاولة...');
                await new Promise(resolve => setTimeout(resolve, 2000));
                attempts++;
                continue;
            }
            
            const status = await response.json();
            console.log('📊 حالة التوليد:', status);
            
            if (status.progress !== undefined) {
                const percent = status.progress || 0;
                document.getElementById('progress-percent').textContent = percent + '%';
                document.getElementById('progress-bar').style.width = percent + '%';
                
                if (status.step) {
                    document.getElementById('progress-status').textContent = status.step;
                }
                if (status.detail) {
                    document.getElementById('progress-detail').textContent = status.detail;
                }
                
                if (status.title) {
                    document.getElementById('progress-title').textContent = '🎬 ' + status.title;
                }
                
                if (status.format || status.size || status.duration || status.dimensions) {
                    document.getElementById('loading-format').textContent = status.format || '—';
                    document.getElementById('loading-size').textContent = status.size || '—';
                    document.getElementById('loading-duration').textContent = status.duration ? formatDuration(status.duration) : '—';
                    document.getElementById('loading-dimensions').textContent = status.dimensions || '—';
                    document.getElementById('video-info-loading').classList.remove('hidden');
                }
            }
            
            if (status.completed) {
                if (status.error) {
                    showProgressError('❌ ' + status.error);
                    throw new Error(status.error);
                }
                
                console.log('✅ اكتمل التوليد!');
                
                const videoUrl = status.video_url || 'https://sample-videos.com/video321/mp4/240/big_buck_bunny_240p_1mb.mp4';
                
                showPreviewWithInfo(videoUrl, {
                    url: videoUrl,
                    title: status.title || 'فيديو مولد',
                    description: prompt,
                    duration: status.duration || 0,
                    format: status.format || 'mp4',
                    size: status.size || '—',
                    dimensions: status.dimensions || '—',
                    generated: true,
                    session_id: sessionId
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
            if (error.message && error.message.includes('فشل')) {
                throw error;
            }
            console.warn('⚠️ خطأ في جلب حالة التوليد:', error);
        }
        
        await new Promise(resolve => setTimeout(resolve, 1500));
        attempts++;
    }
    
    if (state.cancelProcessing) {
        console.log('⏹️ تم إلغاء التوليد');
        return;
    }
    
    console.error('⏰ انتهى وقت التوليد');
    showProgressError('⏰ انتهى وقت التوليد. يرجى المحاولة مرة أخرى.');
    throw new Error('انتهى وقت التوليد. يرجى المحاولة مرة أخرى.');
}

// ============================================
// عرض التقدم
// ============================================
function showProgress(title, percent = 0) {
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
    
    if (state.progressTimer) clearInterval(state.progressTimer);
    state.progressTimer = setInterval(updateElapsedTime, 1000);
}

function showProgressWarning(message) {
    const warning = document.getElementById('progress-warning');
    warning.classList.remove('hidden');
    document.getElementById('progress-warning-text').textContent = message;
}

function hideProgressWarning() {
    document.getElementById('progress-warning').classList.add('hidden');
}

function showProgressError(message) {
    const error = document.getElementById('progress-error');
    error.classList.remove('hidden');
    document.getElementById('progress-error-text').textContent = message;
}

function hideProgressError() {
    document.getElementById('progress-error').classList.add('hidden');
}

function updateElapsedTime() {
    if (!state.startTime) return;
    const elapsed = Math.floor((Date.now() - state.startTime) / 1000);
    const mins = String(Math.floor(elapsed / 60)).padStart(2, '0');
    const secs = String(elapsed % 60).padStart(2, '0');
    document.getElementById('progress-time').textContent = `${mins}:${secs}`;
}

function hideProgress() {
    document.getElementById('progress-area').classList.add('hidden');
    state.processing = false;
    if (state.progressTimer) {
        clearInterval(state.progressTimer);
        state.progressTimer = null;
    }
}

function cancelProcessing() {
    if (confirm('هل تريد إلغاء المعالجة الجارية؟')) {
        state.cancelProcessing = true;
        showToast('تم إلغاء المعالجة', 'warning');
        hideProgress();
    }
}

// ============================================
// دوال مساعدة
// ============================================
function formatDuration(seconds) {
    if (!seconds || isNaN(seconds)) return '—';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${String(secs).padStart(2, '0')}`;
}

function formatNumber(num) {
    if (!num) return '—';
    if (num >= 1000000) {
        return (num / 1000000).toFixed(1) + 'M';
    }
    if (num >= 1000) {
        return (num / 1000).toFixed(1) + 'K';
    }
    return num.toString();
}

function updateLoadingVideoInfo(format, size, duration, dimensions) {
    document.getElementById('loading-format').textContent = format;
    document.getElementById('loading-size').textContent = size;
    document.getElementById('loading-duration').textContent = duration;
    document.getElementById('loading-dimensions').textContent = dimensions;
}

// ============================================
// عرض المعاينة
// ============================================
function showPreviewWithInfo(videoUrl, videoData) {
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
    if (videoData.isExternal) {
        finalVideoUrl = 'https://sample-videos.com/video321/mp4/240/big_buck_bunny_240p_1mb.mp4';
        setTimeout(() => {
            const warning = document.getElementById('video-warning');
            warning.classList.remove('hidden');
            document.getElementById('video-warning-text').textContent = '⚠️ تم استخدام فيديو تجريبي للعرض لأن الرابط الأصلي لا يدعم المعاينة المباشرة.';
        }, 1000);
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
    }
    
    if (videoData.video_id || videoData.published_at) {
        document.getElementById('video-youtube-info').classList.remove('hidden');
        document.getElementById('video-id').textContent = videoData.video_id || '—';
        document.getElementById('video-published').textContent = videoData.published_at ? new Date(videoData.published_at).toLocaleDateString('ar-SA') : '—';
    }
    
    if (videoData.warning) {
        const warning = document.getElementById('video-warning');
        warning.classList.remove('hidden');
        document.getElementById('video-warning-text').textContent = '⚠️ ' + videoData.warning;
    } else {
        hideWarning();
    }
    
    if (videoData.description) {
        document.getElementById('video-description').classList.remove('hidden');
        document.getElementById('video-description-text').textContent = videoData.description;
    }
    
    if (videoData.download && videoData.download.path) {
        document.getElementById('video-download').classList.remove('hidden');
        document.getElementById('video-download-link').href = videoData.download.path;
    }
    
    state.generatedVideo = {
        url: finalVideoUrl,
        data: videoData,
        links: state.videoLinks,
        session_id: videoData.session_id,
        original_url: videoData.original_url || videoUrl
    };
    
    video.addEventListener('loadedmetadata', function() {
        if (this.duration && !isNaN(this.duration)) {
            document.getElementById('video-duration').textContent = formatDuration(this.duration);
            if (state.generatedVideo) {
                state.generatedVideo.data.duration = this.duration;
            }
        }
        
        if (this.videoWidth && this.videoHeight) {
            const dimensions = `${this.videoWidth}×${this.videoHeight}`;
            document.getElementById('video-dimensions').textContent = dimensions;
            if (state.generatedVideo) {
                state.generatedVideo.data.dimensions = dimensions;
            }
        }
        
        overlay.classList.add('hidden');
    });
    
    video.addEventListener('progress', function() {
        if (this.buffered.length > 0) {
            const buffered = this.buffered.end(0);
            const duration = this.duration;
            if (duration > 0 && !isNaN(duration)) {
                const percent = Math.min(Math.round((buffered / duration) * 100), 100);
                loadingProgress.textContent = percent + '%';
                if (percent >= 100) {
                    loadingText.textContent = 'اكتمل التحميل!';
                }
            }
        }
    });
    
    video.onerror = function() {
        overlay.classList.add('hidden');
        if (finalVideoUrl !== 'https://sample-videos.com/video321/mp4/240/big_buck_bunny_240p_1mb.mp4') {
            showToast('⚠️ تعذر تحميل الفيديو، جاري استخدام فيديو تجريبي للعرض', 'warning');
            source.src = 'https://sample-videos.com/video321/mp4/240/big_buck_bunny_240p_1mb.mp4';
            video.load();
        } else {
            showToast('⚠️ تعذر تحميل معاينة الفيديو', 'warning');
        }
    };
    
    previewArea.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

function hideWarning() {
    document.getElementById('video-warning').classList.add('hidden');
}

function hidePreview() {
    document.getElementById('preview-area').classList.add('hidden');
    state.generatedVideo = null;
}

function cancelPreview() {
    hidePreview();
    showToast('تم إلغاء المعاينة', 'info');
}

// ============================================
// وظائف يوتيوب
// ============================================

async function handleYouTubeAuth() {
    try {
        const response = await fetch('/api/v1/youtube/auth/url');
        if (!response.ok) throw new Error('فشل الحصول على رابط المصادقة');
        
        const data = await response.json();
        
        if (data.auth_url) {
            const authWindow = window.open(data.auth_url, '_blank', 'width=600,height=700');
            showToast('🔑 افتح النافذة المنبثقة للمصادقة', 'info');
            
            let attempts = 0;
            const checkInterval = setInterval(async () => {
                attempts++;
                try {
                    const statusResponse = await fetch('/api/v1/youtube/auth/status?user_id=default');
                    if (statusResponse.ok) {
                        const statusData = await statusResponse.json();
                        if (statusData.authenticated) {
                            clearInterval(checkInterval);
                            state.isYoutubeAuth = true;
                            document.getElementById('auth-status').textContent = '✅ مسجل';
                            document.getElementById('auth-status').className = 'text-xs text-green-400';
                            showToast('✅ تم تسجيل الدخول إلى يوتيوب بنجاح!', 'success');
                            addMessage('assistant', '🔑 تم تسجيل الدخول إلى يوتيوب بنجاح! يمكنك الآن الوصول إلى فيديوهاتك ومعلومات إضافية.');
                        }
                    }
                } catch (e) {
                    console.log('⏳ في انتظار المصادقة...');
                }
                
                if (attempts > 30) {
                    clearInterval(checkInterval);
                    if (!state.isYoutubeAuth) {
                        showToast('⏰ انتهى وقت المصادقة. حاول مرة أخرى.', 'warning');
                    }
                }
            }, 1000);
        }
    } catch (error) {
        showToast('❌ فشل المصادقة: ' + error.message, 'error');
    }
}

async function loadMyVideos() {
    try {
        showProgress('جاري تحميل فيديوهاتك...', 10);
        
        const response = await fetch('/api/v1/youtube/my/videos?max_results=10');
        if (!response.ok) {
            if (response.status === 401) {
                showToast('⚠️ يرجى تسجيل الدخول أولاً', 'warning');
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
                    `🎬 ${video.title}\n` +
                    `👤 ${video.channel_title || 'غير معروف'}\n` +
                    `👁️ ${formatNumber(video.view_count)} مشاهدات\n` +
                    `⏱️ ${formatDuration(video.duration)}\n` +
                    `🔗 https://youtube.com/watch?v=${video.video_id}`
                );
            });
        } else {
            addMessage('assistant', '📭 لا توجد فيديوهات مرفوعة.');
        }
        
    } catch (error) {
        hideProgress();
        showToast('❌ ' + error.message, 'error');
    }
}

async function loadMySubscriptions() {
    try {
        showProgress('جاري تحميل القنوات المشترك فيها...', 10);
        
        const response = await fetch('/api/v1/youtube/my/subscriptions?max_results=10');
        if (!response.ok) {
            if (response.status === 401) {
                showToast('⚠️ يرجى تسجيل الدخول أولاً', 'warning');
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
                addMessage('assistant', 
                    `📺 ${sub.title}\n` +
                    `🆔 ${sub.channel_id}`
                );
            });
        } else {
            addMessage('assistant', '📭 لا توجد قنوات مشترك فيها.');
        }
        
    } catch (error) {
        hideProgress();
        showToast('❌ ' + error.message, 'error');
    }
}

async function searchYouTube() {
    const query = prompt('🔍 أدخل كلمة البحث:');
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
                addMessage('assistant', 
                    `🎬 ${video.title}\n` +
                    `👤 ${video.channel_title}\n` +
                    `🔗 ${video.url}`
                );
            });
        } else {
            addMessage('assistant', '📭 لا توجد نتائج.');
        }
        
    } catch (error) {
        hideProgress();
        showToast('❌ ' + error.message, 'error');
    }
}

// ============================================
// تأكيد وإنشاء المشروع
// ============================================
async function confirmProject() {
    if (!state.generatedVideo) {
        showToast('⚠️ لا يوجد فيديو لتأكيده', 'warning');
        return;
    }
    
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
            description: state.generatedVideo.data.description || '',
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
            let errorMessage = 'فشل إنشاء المشروع';
            try {
                const errorData = await response.json();
                errorMessage = errorData.detail || errorMessage;
            } catch (e) {
                errorMessage = `خطأ ${response.status}: ${response.statusText}`;
            }
            throw new Error(errorMessage);
        }
        
        const project = await response.json();
        state.currentProjectId = project.id;
        showToast('✅ تم إنشاء المشروع بنجاح!', 'success');
        
        window.dispatchEvent(new CustomEvent('projectCreated', { 
            detail: { projectId: project.id, project: project }
        }));
        
        setTimeout(() => {
            window.location.href = `/projects/${project.id}`;
        }, 1000);
        
    } catch (error) {
        showToast('❌ ' + error.message, 'error');
        console.error('Project creation error:', error);
        addMessage('assistant', `❌ عذراً، فشل إنشاء المشروع: ${error.message}`);
    } finally {
        confirmBtn.disabled = false;
        confirmBtn.innerHTML = `
            <svg class="w-4 h-4 inline ml-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
            </svg>
            تأكيد وإنشاء المشروع
        `;
    }
}

function buildScriptFromChat() {
    let script = '';
    const userMessages = state.chatHistory.filter(msg => msg.role === 'user');
    if (userMessages.length > 0) {
        script = userMessages.map(msg => `🎬 طلب: ${msg.content}`).join('\n\n');
    }
    if (state.videoLinks.length > 0) {
        script += '\n\n--- مصادر إلهام ---\n';
        state.videoLinks.forEach((url, i) => {
            script += `${i+1}. ${url}\n`;
        });
    }
    return script || 'نص الفيديو المستند إلى المحادثة';
}

// ============================================
// معالجة إرسال الدردشة
// ============================================
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
    
    try {
        await generateVideoFromPrompt(message);
    } catch (error) {
        showToast('❌ حدث خطأ: ' + error.message, 'error');
        console.error('Chat error:', error);
    } finally {
        btn.disabled = false;
        btn.innerHTML = `
            <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"/>
            </svg>
            إرسال
        `;
    }
});

// ============================================
// اختصارات لوحة المفاتيح
// ============================================
document.getElementById('chat-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        document.getElementById('chat-form').dispatchEvent(new Event('submit'));
    }
});

document.getElementById('url-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
        e.preventDefault();
        addVideoLink();
    }
});

// ============================================
// التحقق من الاتصال
// ============================================
async function checkConnection() {
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
        } else {
            throw new Error('Server error');
        }
    } catch (error) {
        status.className = 'w-3 h-3 bg-red-500 rounded-full';
        text.textContent = 'غير متصل';
        text.className = 'text-xs text-red-400';
        showToast('⚠️ تعذر الاتصال بالخادم.', 'warning');
    }
}

// ============================================
// تهيئة
// ============================================
function initSession() {
    state.sessionId = 'session_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
}

window.addEventListener('error', (event) => {
    console.error('Global error:', event.error);
    showToast('❌ حدث خطأ غير متوقع. يرجى تحديث الصفحة.', 'error');
});

window.addEventListener('unhandledrejection', (event) => {
    console.error('Unhandled rejection:', event.reason);
    showToast('❌ حدث خطأ غير متوقع. يرجى تحديث الصفحة.', 'error');
});

document.addEventListener('DOMContentLoaded', () => {
    initSession();
    checkConnection();
    setInterval(checkConnection, 30000);
    console.log('🎬 AI Video Creator - Create Page initialized');
    console.log('📡 YouTube API + OAuth 2.0 enabled');
});

function showToast(message, type = 'info') {
    const oldToasts = document.querySelectorAll('.toast-message');
    oldToasts.forEach(t => t.remove());
    
    const toast = document.createElement('div');
    const colors = {
        success: 'bg-green-600',
        error: 'bg-red-600',
        warning: 'bg-yellow-600',
        info: 'bg-blue-600'
    };
    toast.className = `toast-message fixed bottom-4 right-4 ${colors[type] || colors.info} text-white px-6 py-3 rounded-lg shadow-lg z-50 transition-all duration-300 transform translate-y-full opacity-0 max-w-md`;
    toast.textContent = message;
    document.body.appendChild(toast);
    
    requestAnimationFrame(() => {
        toast.classList.remove('translate-y-full', 'opacity-0');
    });
    
    setTimeout(() => {
        toast.classList.add('translate-y-full', 'opacity-0');
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}
