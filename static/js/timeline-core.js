// ============================================================
//  timeline-core.js — الإعدادات + Supabase + الأدوات المساعدة
// ============================================================

// قراءة الإعدادات من HTML
const _cfg = JSON.parse(document.getElementById('timeline-config').textContent);
const scenes = _cfg.scenes;
const projectId = _cfg.projectId;
const currentUserId = _cfg.userId;
const currentUserEmail = _cfg.userEmail;

// ====== الحالة العامة (مشتركة بين كل الملفات عبر window) ======
let projectData = {
    clips: [],
    layers: [],
    mediaFiles: [],
    totalDuration: 10,
    cellWidth: 80
};

let selectedClipId = null;
let selectedLayerIndex = 0;
let currentTime = 0;
let isPlaying = false;
let playInterval = null;
let playbackSpeed = 1;
let isMuted = false;
let isLooping = false;
let isRecording = false;
let mediaRecorder = null;
let recordedChunks = [];
let recordingStartTime = 0;
let recordingTimerInterval = null;
let recordingStream = null;
let recordingWallStart = 0;
let recordingBoundClipId = null;
let recordingMaxEnd = 0;
let recordingLastEndCheck = 0;
let recordingInitialMaxEnd = 0;
let clipIdCounter = 0;
let currentClipAtTime = null;
let renderPollInterval = null;
let renderJobId = null;
let isSyncing = false;
let isDataLoaded = false;

let canvas = null;
let ctx = null;
let audioPlayer = null;
let isCanvasReady = false;
let imageCache = {};
let videoElements = {};

// ====== محرك الصوت ======
let audioContext = null;
let audioBuffers = {};
let audioNodes = [];
let lastAudioSyncTime = -1;

// ====== ثوابت ======
const COLORS = {
    video: '#2563eb',
    audio: '#059669',
    image: '#f59e0b',
    text: '#d97706'
};

const TYPE_ICONS = {
    video: '🎬',
    audio: '🎤',
    image: '🖼️',
    text: '📝'
};

// ============================================================
//  UTILITY
// ============================================================
function formatTime(seconds) {
    if (!seconds || isNaN(seconds)) return '00:00:00';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
    return `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
}

function showToast(msg, type = 'info') {
    const oldToast = document.querySelector('.toast-message');
    if (oldToast) oldToast.remove();

    const toast = document.createElement('div');
    toast.className = `toast-message fixed bottom-20 left-1/2 transform -translate-x-1/2 px-4 py-2 rounded-lg text-white text-sm z-50 transition-all duration-300 max-w-md text-center`;
    const colors = {
        success: 'bg-emerald-600',
        error: 'bg-red-600',
        warning: 'bg-amber-600',
        info: 'bg-blue-600'
    };
    toast.classList.add(colors[type] || colors.info);
    toast.textContent = msg;
    document.body.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// ============================================================
//  SUPABASE — رفع / حفظ / تحميل
// ============================================================
async function uploadFileToSupabase(file, projectId) {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("project_id", projectId);

    try {
        const resp = await fetch("/api/v1/storage/upload-media", {
            method: "POST",
            body: formData,
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.error || `HTTP ${resp.status}`);
        }

        const data = await resp.json();
        if (!data.url) throw new Error("لا يوجد رابط في الاستجابة");
        return data.url;

    } catch (e) {
        console.error("❌ Upload failed:", e);
        return null;
    }
}

async function saveProjectToSupabase(projectId, data) {
    try {
        const response = await fetch(`/api/v1/projects/save`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                project_id: projectId,
                user_id: currentUserId,
                data: {
                    clips: data.clips.map(c => ({
                        id: c.id,
                        type: c.type,
                        layer: c.layer,
                        start: c.start,
                        duration: c.duration,
                        title: c.title,
                        content: (c.content && c.content.startsWith('http')) ? c.content : null,
                        color: c.color,
                        icon: c.icon,
                        metadata: c.metadata || {}
                    })),
                    layers: data.layers,
                    total_duration: data.totalDuration,
                    cell_width: data.cellWidth,
                    media_files: data.mediaFiles.map(f => ({
                        name: f.name,
                        size: f.size,
                        type: f.type,
                        url: f.url || null,
                    }))
                }
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'فشل الحفظ');
        }

        const result = await response.json();
        updateSyncStatus('synced');
        return result;

    } catch(e) {
        console.error('❌ فشل الحفظ على Supabase:', e);
        updateSyncStatus('error');
        throw e;
    }
}

async function loadProjectFromSupabase(projectId) {
    try {
        const response = await fetch(`/api/v1/projects/${projectId}?user_id=${currentUserId}`);

        if (response.status === 404) return null;
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'فشل التحميل');
        }

        const result = await response.json();
        const saved = result.data;

        if (saved && saved.data) {
            return {
                clips: saved.data.clips || [],
                layers: saved.data.layers || [{ name: 'طبقة 1', visible: true, locked: false }],
                totalDuration: saved.data.total_duration || 10,
                cellWidth: saved.data.cell_width || 80,
                mediaFiles: saved.data.media_files || []
            };
        }

        return null;

    } catch(e) {
        console.error('❌ فشل التحميل:', e);
        throw e;
    }
}

async function shareProjectWithUser(projectId, email) {
    try {
        const response = await fetch(`/api/v1/projects/${projectId}/share`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email: email })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'فشل المشاركة');
        }

        const result = await response.json();
        showToast('✅ ' + result.message, 'success');
        return true;

    } catch(e) {
        showToast('❌ ' + e.message, 'error');
        return false;
    }
}

// ============================================================
//  SYNC STATUS
// ============================================================
function updateSyncStatus(status) {
    const el = document.getElementById('syncStatus');
    if (!el) return;

    el.className = 'sync-status';
    if (status === 'synced') {
        el.classList.add('synced');
        el.textContent = '✅ متزامن';
    } else if (status === 'syncing') {
        el.classList.add('syncing');
        el.textContent = '🔄 جاري...';
    } else if (status === 'error') {
        el.classList.add('error');
        el.textContent = '⚠️ خطأ';
    }
}

async function syncProject() {
    if (isSyncing) return;
    isSyncing = true;
    updateSyncStatus('syncing');
    showToast('🔄 جاري المزامنة...', 'info');

    try {
        await saveProjectToSupabase(projectId, {
            clips: projectData.clips,
            layers: projectData.layers,
            totalDuration: projectData.totalDuration,
            cellWidth: projectData.cellWidth,
            mediaFiles: projectData.mediaFiles
        });
        showToast('✅ تمت المزامنة بنجاح', 'success');
    } catch(e) {
        showToast('❌ فشل المزامنة: ' + e.message, 'error');
        updateSyncStatus('error');
    }

    isSyncing = false;
}

function openShareModal() {
    document.getElementById('shareModal').classList.remove('hidden');
    document.getElementById('shareEmail').value = '';
    document.getElementById('shareEmail').focus();
}

function closeShareModal() {
    document.getElementById('shareModal').classList.add('hidden');
}

async function shareProject() {
    const email = document.getElementById('shareEmail').value.trim();
    if (!email || !email.includes('@')) {
        showToast('⚠️ بريد إلكتروني غير صحيح', 'warning');
        return;
    }
    const success = await shareProjectWithUser(projectId, email);
    if (success) closeShareModal();
}

// ============================================================
//  SAVE / LOAD / EXPORT
// ============================================================
function saveProjectData() {
    if (!isDataLoaded) return;

    saveProjectToSupabase(projectId, {
        clips: projectData.clips,
        layers: projectData.layers,
        totalDuration: projectData.totalDuration,
        cellWidth: projectData.cellWidth,
        mediaFiles: projectData.mediaFiles
    }).catch(() => updateSyncStatus('error'));
}

async function loadProjectData() {
    const overlay = document.getElementById('loadingOverlay');
    overlay.classList.remove('hidden');

    try {
        const data = await loadProjectFromSupabase(projectId);

        if (data) {
            projectData.clips = data.clips || [];
            projectData.layers = data.layers || [{ name: 'طبقة 1', visible: true, locked: false }];
            projectData.totalDuration = data.totalDuration || 10;
            projectData.cellWidth = data.cellWidth || 80;
            projectData.mediaFiles = data.mediaFiles || [];

            if (projectData.clips.length > 0) {
                clipIdCounter = Math.max(...projectData.clips.map(c => c.id)) + 1;
            }

            renderLayers();
            renderTimeline();
            updateStatus();
            renderMediaGallery();
            renderPreview(currentTime);

            updateSyncStatus('synced');
            isDataLoaded = true;
            overlay.classList.add('hidden');
            showToast('✅ تم تحميل المشروع', 'success');
            return;
        }

        if (scenes && scenes.length > 0) {
            scenes.forEach((scene, i) => {
                const clip = {
                    id: clipIdCounter++,
                    type: 'image',
                    layer: 0,
                    start: scene.start_time || i * 3,
                    duration: scene.duration || 3,
                    title: scene.title || `مشهد ${i+1}`,
                    content: scene.content || '',
                    color: COLORS.image,
                    icon: '🖼️',
                    metadata: { scene_id: scene.id }
                };
                projectData.clips.push(clip);
            });
            projectData.totalDuration = Math.max(...projectData.clips.map(c => c.start + c.duration), 10);

            renderLayers();
            renderTimeline();
            updateStatus();
            renderMediaGallery();
            renderPreview(currentTime);

            await saveProjectData();

            isDataLoaded = true;
            overlay.classList.add('hidden');
            showToast('✅ تم إنشاء مشروع جديد', 'success');
            return;
        }

        projectData.layers = [{ name: 'طبقة 1', visible: true, locked: false }];
        renderLayers();
        renderTimeline();
        updateStatus();
        renderMediaGallery();
        renderPreview(currentTime);

        isDataLoaded = true;
        overlay.classList.add('hidden');

    } catch(e) {
        console.error('❌ فشل تحميل المشروع:', e);
        overlay.classList.add('hidden');
        showToast('❌ تعذر تحميل المشروع: ' + e.message, 'error');
        updateSyncStatus('error');

        projectData.layers = [{ name: 'طبقة 1', visible: true, locked: false }];
        renderLayers();
        renderTimeline();
        updateStatus();
        renderMediaGallery();
        renderPreview(currentTime);
        isDataLoaded = true;
    }
}

function exportProject() {
    const data = {
        project: projectId,
        version: '2.0',
        exportedAt: new Date().toISOString(),
        clips: projectData.clips.map(c => ({
            ...c,
            content: c.content && c.content.startsWith('blob:') ? 'blob' : c.content,
            _fileRef: c.metadata && c.metadata.file ? c.metadata.file : null
        })),
        layers: projectData.layers,
        totalDuration: projectData.totalDuration,
        mediaFiles: projectData.mediaFiles.map(f => ({
            name: f.name,
            size: f.size,
            type: f.type,
            url: f.url
        }))
    };

    const blob = new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `project_${projectId}_export.json`;
    a.click();
    URL.revokeObjectURL(url);
    showToast('✅ تم التصدير', 'success');
}

// ============================================================
//  RENDER (Backend)
// ============================================================
function startRender(projectId) {
    const btn = document.getElementById('renderBtn');
    const loading = document.getElementById('renderLoading');
    const status = document.getElementById('renderStatus');
    const progressFill = document.getElementById('renderProgressFill');

    btn.disabled = true;
    btn.style.opacity = '0.5';
    loading.classList.add('active');
    status.textContent = 'جاري التجهيز...';
    progressFill.style.width = '0%';

    const renderData = {
        project_id: projectId,
        clips: projectData.clips.map(c => ({
            type: c.type,
            start: c.start,
            duration: c.duration,
            layer: c.layer,
            content: (c.content && c.content.startsWith('http')) ? c.content : null,
            title: c.title,
            metadata: c.metadata
        })),
        layers: projectData.layers,
        duration: projectData.totalDuration,
        mediaFiles: projectData.mediaFiles.map(f => ({
            name: f.name,
            type: f.type,
            size: f.size,
            url: f.url || null,
        }))
    };

    fetch('/api/v1/production/render', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(renderData)
    })
    .then(resp => {
        if (!resp.ok) {
            return resp.json().then(err => { throw new Error(err.detail || 'فشل الرندر'); });
        }
        return resp.json();
    })
    .then(data => {
        if (data.job_id) {
            renderJobId = data.job_id;
            status.textContent = 'جاري الرندر...';
            pollRenderStatus(renderJobId);
        } else if (data.status === 'completed') {
            showToast('✅ تم الرندر بنجاح! جاري فتح صفحة المشروع...', 'success');
            loading.classList.remove('active');
            btn.disabled = false;
            btn.style.opacity = '1';
            setTimeout(() => {
                window.location.href = `/projects/${projectId}`;
            }, 1200);
        } else {
            throw new Error('استجابة غير متوقعة');
        }
    })
    .catch(err => {
        showToast('❌ ' + err.message, 'error');
        loading.classList.remove('active');
        btn.disabled = false;
        btn.style.opacity = '1';
    });
}

function pollRenderStatus(jobId) {
    if (renderPollInterval) {
        clearInterval(renderPollInterval);
        renderPollInterval = null;
    }

    let attempts = 0;
    let consecutiveErrors = 0;
    const maxConsecutiveErrors = 5;

    const statusEl = document.getElementById('renderStatus');
    const progressFill = document.getElementById('renderProgressFill');
    const loading = document.getElementById('renderLoading');

    renderPollInterval = setInterval(() => {
        attempts++;

        fetch(`/api/v1/production/jobs/${jobId}/status`)
            .then(resp => {
                if (!resp.ok) {
                    if (resp.status === 404) {
                        clearInterval(renderPollInterval);
                        renderPollInterval = null;
                        if (statusEl) statusEl.textContent = '❌ لم يتم العثور على المهمة';
                        showToast('⚠️ لم يتم العثور على المهمة', 'warning');
                        resetRenderUI();
                        return;
                    }
                    consecutiveErrors++;
                    if (consecutiveErrors >= maxConsecutiveErrors) {
                        clearInterval(renderPollInterval);
                        renderPollInterval = null;
                        if (statusEl) statusEl.textContent = '❌ فشل الاتصال بالخادم';
                        showToast('❌ فشل الاتصال بالخادم', 'error');
                        resetRenderUI();
                        return;
                    }
                    return null;
                }
                consecutiveErrors = 0;
                return resp.json();
            })
            .then(data => {
                if (!data) return;

                if (progressFill && data.progress !== undefined) {
                    progressFill.style.width = Math.min(data.progress, 100) + '%';
                }

                if (data.status === 'completed') {
                    clearInterval(renderPollInterval);
                    renderPollInterval = null;
                    if (statusEl) statusEl.textContent = '✅ اكتمل الرندر بنجاح!';
                    if (loading) loading.classList.remove('active');
                    if (progressFill) progressFill.style.width = '100%';
                    resetRenderUI();
                    showToast('✅ تم الرندر بنجاح!', 'success');
                    setTimeout(() => {
                        window.location.href = `/projects/${projectId}`;
                    }, 1200);

                } else if (data.status === 'failed') {
                    clearInterval(renderPollInterval);
                    renderPollInterval = null;
                    const errorMsg = data.error || 'خطأ غير معروف';
                    if (statusEl) statusEl.textContent = `❌ فشل الرندر: ${errorMsg}`;
                    if (loading) loading.classList.remove('active');
                    resetRenderUI();
                    showToast(`❌ فشل الرندر: ${errorMsg}`, 'error');

                } else if (data.status === 'processing') {
                    if (statusEl) {
                        let msg = `🔄 جاري الرندر... ${Math.round(data.progress || 0)}%`;
                        if (data.current_stage) msg += ` - ${data.current_stage}`;
                        statusEl.textContent = msg;
                    }

                } else if (data.status === 'pending') {
                    if (statusEl) statusEl.textContent = '⏳ في انتظار البدء...';
                } else {
                    if (statusEl) statusEl.textContent = `📊 الحالة: ${data.status}`;
                }
            })
            .catch(err => {
                console.error('❌ Error polling status:', err);
                if (attempts % 6 === 0) {
                    if (statusEl) statusEl.textContent = '🔄 جاري المحاولة مرة أخرى...';
                }
            });
    }, 5000);
}

function resetRenderUI() {
    const btn = document.getElementById('renderBtn');
    const loading = document.getElementById('renderLoading');
    if (btn) {
        btn.disabled = false;
        btn.style.opacity = '1';
    }
    if (loading) loading.classList.remove('active');
}
