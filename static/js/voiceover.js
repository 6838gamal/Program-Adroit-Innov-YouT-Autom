/**
 * voiceover.js — نظام شامل لتسجيل/توليد/استنساخ الصوت
 * Multi-Provider: Edge TTS + HuggingFace + ElevenLabs + D-ID
 *
 * ✅ إصلاح: state is not defined
 * ✅ إصلاح: إضافة المقطع للخط الزمني
 * ✅ إصلاح: توافق كامل مع timeline-core.js و timeline-timeline.js
 */

// ============================================================
// Safe Accessors — الوصول الآمن لمتغيرات timeline-core.js
// ============================================================

function safeGetProjectData() {
    if (typeof projectData !== 'undefined' && projectData) {
        return projectData;
    }
    console.warn('⚠️ projectData غير معرّف — استخدام fallback');
    return {
        clips: [],
        layers: [{ name: 'طبقة 1', visible: true, locked: false }],
        mediaFiles: [],
        totalDuration: 10,
        cellWidth: 80,
    };
}

function safeGetProjectId() {
    if (typeof projectId !== 'undefined' && projectId) {
        return projectId;
    }
    return '';
}

function safeGetCurrentTime() {
    if (typeof currentTime !== 'undefined' && currentTime != null) {
        return currentTime;
    }
    return 0;
}


// ============================================================
// حالة النظام
// ============================================================
const VoiceoverState = {
    currentModal: null,
    recording: null,
    mediaRecorder: null,
    audioChunks: [],
    recognition: null,
    transcript: '',
    scriptSegments: [],
    ttsVoices: [],
    selectedVoice: null,
    isRecordingScript: false,
    startTime: 0,
    recTimer: null,
    pendingBlob: null,
    pendingUrl: null,
    pendingFileName: null,
    pendingDuration: 0,
    source: null,
};


const VoiceCloneState = {
    savedVoices: [],
    edgeVoices: [],
    selectedVoiceId: null,
    selectedProvider: 'auto',
    isCloning: false,
    isGenerating: false,
    lastTextHash: null,
};


const SyncProcessState = {
    rawAudioBlob: null,
    rawAudioUrl: null,
    processedBlob: null,
    processedUrl: null,
    alignedSegments: [],
    processingOptions: {
        normalize: true,
        denoise: false,
        trimSilence: true,
        targetLUFS: -16,
        compress: false,
    },
    isProcessing: false,
    isAligned: false,
    clonedVoiceId: null,
    clonedVoiceName: null,
    clonedRemoteUrl: null,
    clonedDuration: 0,
    lastTextHash: null,
};


const TalkingHeadState = {
    imageBlob: null,
    imageUrl: null,
    currentTalkId: null,
    pollingInterval: null,
    resultUrl: null,
    isGenerating: false,
};


// ============================================================
// تحميل أصوات TTS
// ============================================================
function loadTTSVoices() {
    if (!('speechSynthesis' in window)) return [];
    const voices = speechSynthesis.getVoices();
    VoiceoverState.ttsVoices = voices;
    return voices;
}

if ('speechSynthesis' in window) {
    speechSynthesis.onvoiceschanged = loadTTSVoices;
    loadTTSVoices();
}


// ============================================================
// فتح/إغلاق نافذة الاستوديو
// ============================================================
function openVoiceoverStudio(clipId = null) {
    const modal = document.getElementById('voiceoverModal');
    if (!modal) return;

    VoiceoverState.currentModal = clipId;

    document.getElementById('voiceoverScript').value = '';
    document.getElementById('voiceoverTranscript').innerHTML = '';
    document.getElementById('voiceoverSegments').innerHTML =
        '<div style="color:#64748b;font-size:12px;text-align:center;padding:8px;">لا توجد مقاطع بعد</div>';
    document.getElementById('voiceoverPreview').innerHTML = '';
    document.getElementById('voiceoverFileInfo').style.display = 'none';
    document.getElementById('voiceoverFileInfo').innerHTML = '';
    VoiceoverState.scriptSegments = [];

    hideSyncButton();

    const ttsRadio = document.querySelector('input[name="voiceoverMode"][value="tts"]');
    if (ttsRadio) {
        ttsRadio.checked = true;
        ttsRadio.dispatchEvent(new Event('change'));
    }

    populateVoiceSelect();

    const pd = safeGetProjectData();
    if (clipId && pd.clips) {
        const clip = pd.clips.find(c => c.id === clipId);
        if (clip) {
            document.getElementById('voiceoverScript').value = clip.script || '';
            document.getElementById('voiceoverTitle').value = clip.title || '';
            if (clip.scriptSegments) {
                VoiceoverState.scriptSegments = clip.scriptSegments;
                renderSegments();
            }
            if (clip.url && clip.source) {
                showSyncButton();
            }
        }
    }

    modal.classList.remove('hidden');
}

function closeVoiceoverStudio() {
    stopVoiceoverRecording();
    if (VoiceoverState.recognition) {
        try { VoiceoverState.recognition.stop(); } catch (e) { }
    }
    if ('speechSynthesis' in window) {
        speechSynthesis.cancel();
    }
    const modal = document.getElementById('voiceoverModal');
    if (modal) modal.classList.add('hidden');
    VoiceoverState.currentModal = null;
}


// ============================================================
// إظهار/إخفاء الأزرار
// ============================================================
function showSyncButton() {
    const el = document.getElementById('openSyncBtnContainer');
    if (el) {
        el.innerHTML = `
            <button onclick="openVoiceCloneModal()"
                    class="btn-primary btn-sm w-full sync-open-btn">
                🎙️ استنساخ صوتي + توليد النص
            </button>
        `;
        el.style.display = 'block';
    }

    const thEl = document.getElementById('openTalkingHeadBtnContainer');
    if (thEl) {
        thEl.style.display = 'block';
    }
}

function hideSyncButton() {
    const el = document.getElementById('openSyncBtnContainer');
    if (el) el.style.display = 'none';

    const thEl = document.getElementById('openTalkingHeadBtnContainer');
    if (thEl) thEl.style.display = 'none';
}


// ============================================================
// تعبئة قائمة أصوات TTS
// ============================================================
function populateVoiceSelect() {
    const select = document.getElementById('voiceoverVoiceSelect');
    if (!select) return;
    select.innerHTML = '<option value="">— اختر صوتاً —</option>';

    const voices = loadTTSVoices();
    const sorted = [...voices].sort((a, b) => {
        const aAr = a.lang.startsWith('ar') ? 0 : 1;
        const bAr = b.lang.startsWith('ar') ? 0 : 1;
        return aAr - bAr;
    });

    sorted.forEach((v) => {
        const opt = document.createElement('option');
        opt.value = v.name;
        opt.textContent = `${v.name} (${v.lang}) ${v.lang.startsWith('ar') ? '🇸🇦' : ''}`;
        opt.dataset.name = v.name;
        opt.dataset.lang = v.lang;
        select.appendChild(opt);
    });
}


// ============================================================
// معاينة TTS
// ============================================================
function previewTTS() {
    const script = document.getElementById('voiceoverScript').value.trim();
    const voiceName = document.getElementById('voiceoverVoiceSelect').value;
    const rate = parseFloat(document.getElementById('voiceoverRate').value) || 1;
    const pitch = parseFloat(document.getElementById('voiceoverPitch').value) || 1;

    if (!script) return showToast('⚠️ اكتب النص أولاً', 'warning');
    if (!('speechSynthesis' in window)) return showToast('❌ المتصفح لا يدعم TTS', 'error');

    speechSynthesis.cancel();
    const utter = new SpeechSynthesisUtterance(script);
    const voice = VoiceoverState.ttsVoices.find(v => v.name === voiceName);
    if (voice) utter.voice = voice;
    utter.rate = rate;
    utter.pitch = pitch;
    utter.lang = voice?.lang || 'ar-SA';

    const previewEl = document.getElementById('voiceoverPreview');
    utter.onstart = () => {
        previewEl.innerHTML = '<span style="color:#10b981;">🔊 جاري التشغيل...</span>';
    };
    utter.onend = () => {
        previewEl.innerHTML = '<span style="color:#64748b;">⏹ انتهى</span>';
    };

    speechSynthesis.speak(utter);
}


// ============================================================
// 🎙️ التسجيل المباشر
// ============================================================
function toggleVoiceoverRec() {
    if (VoiceoverState.mediaRecorder &&
        VoiceoverState.mediaRecorder.state === 'recording') {
        stopVoiceoverRecording();
    } else {
        startVoiceoverRecording();
    }
}

async function startVoiceoverRecording() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({
            audio: { echoCancellation: true, noiseSuppression: true, sampleRate: 44100 }
        });

        VoiceoverState.audioChunks = [];
        VoiceoverState.recording = stream;

        const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
            ? 'audio/webm;codecs=opus'
            : 'audio/webm';

        VoiceoverState.mediaRecorder = new MediaRecorder(stream, { mimeType });

        VoiceoverState.mediaRecorder.ondataavailable = (e) => {
            if (e.data.size > 0) VoiceoverState.audioChunks.push(e.data);
        };

        VoiceoverState.mediaRecorder.onstop = async () => {
            const blob = new Blob(VoiceoverState.audioChunks, { type: mimeType });
            await handleRecordedAudio(blob);
            stream.getTracks().forEach(t => t.stop());
        };

        startSpeechRecognition();

        VoiceoverState.startTime = performance.now();
        VoiceoverState.mediaRecorder.start(100);

        const btn = document.getElementById('voiceoverRecBtn');
        btn.innerHTML = '⏹️ إيقاف';
        btn.classList.add('recording');
        document.getElementById('voiceoverRecTimer').style.display = 'inline-block';
        startRecTimer();

        showToast('🎙️ بدأ التسجيل... تحدّث الآن', 'info');
    } catch (err) {
        showToast('❌ تعذّر الوصول للميكروفون: ' + err.message, 'error');
    }
}

function stopVoiceoverRecording() {
    if (VoiceoverState.mediaRecorder &&
        VoiceoverState.mediaRecorder.state !== 'inactive') {
        VoiceoverState.mediaRecorder.stop();
    }
    if (VoiceoverState.recognition) {
        try { VoiceoverState.recognition.stop(); } catch (e) { }
    }
    if (VoiceoverState.recTimer) {
        clearInterval(VoiceoverState.recTimer);
        VoiceoverState.recTimer = null;
    }

    const btn = document.getElementById('voiceoverRecBtn');
    if (btn) {
        btn.innerHTML = '🎙️ تسجيل';
        btn.classList.remove('recording');
    }
    const timer = document.getElementById('voiceoverRecTimer');
    if (timer) timer.style.display = 'none';
}

function startRecTimer() {
    const el = document.getElementById('voiceoverRecTimer');
    const t0 = performance.now();
    VoiceoverState.recTimer = setInterval(() => {
        const s = (performance.now() - t0) / 1000;
        el.textContent = `● ${s.toFixed(1)}s`;
    }, 100);
}


// ============================================================
// التعرف على الكلام
// ============================================================
function startSpeechRecognition() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
        console.warn('SpeechRecognition غير مدعوم');
        return;
    }

    const rec = new SR();
    rec.lang = 'ar-SA';
    rec.continuous = true;
    rec.interimResults = true;

    let segmentStart = performance.now();

    rec.onresult = (event) => {
        let interim = '';

        for (let i = event.resultIndex; i < event.results.length; i++) {
            const transcript = event.results[i][0].transcript;
            if (event.results[i].isFinal) {
                const now = (performance.now() - VoiceoverState.startTime) / 1000;
                const start = (segmentStart - VoiceoverState.startTime) / 1000;

                VoiceoverState.scriptSegments.push({
                    text: transcript.trim(),
                    start: Math.max(0, start),
                    end: now,
                    speaker: 'المتحدث'
                });
                segmentStart = performance.now();
            } else {
                interim += transcript;
            }
        }

        const transEl = document.getElementById('voiceoverTranscript');
        if (transEl) {
            const live = VoiceoverState.scriptSegments.map(s => s.text).join(' ');
            transEl.innerHTML = live +
                (interim ? ` <span style="color:#f59e0b;">${interim}</span>` : '');
        }
        renderSegments();
    };

    rec.onerror = (e) => console.warn('SR error:', e.error);
    rec.onend = () => {
        if (VoiceoverState.mediaRecorder?.state === 'recording') {
            try { rec.start(); } catch (e) { }
        }
    };

    try { rec.start(); } catch (e) { }
    VoiceoverState.recognition = rec;
}


// ============================================================
// معالجة الصوت المسجل
// ============================================================
async function handleRecordedAudio(blob) {
    const url = URL.createObjectURL(blob);
    const previewEl = document.getElementById('voiceoverPreview');
    previewEl.innerHTML = `
        <audio controls src="${url}" style="width:100%;height:36px;"></audio>
        <div style="font-size:11px;color:#64748b;margin-top:4px;">
            الحجم: ${(blob.size / 1024).toFixed(1)} KB
        </div>
    `;

    VoiceoverState.pendingBlob = blob;
    VoiceoverState.pendingUrl = url;
    VoiceoverState.source = 'recording';

    showSyncButton();
    showToast('✅ تم التسجيل، يمكنك الاستنساخ الآن', 'success');
}


// ============================================================
// عرض مقاطع النص
// ============================================================
function renderSegments() {
    const container = document.getElementById('voiceoverSegments');
    if (!container) return;

    if (VoiceoverState.scriptSegments.length === 0) {
        container.innerHTML =
            '<div style="color:#64748b;font-size:12px;text-align:center;padding:8px;">لا توجد مقاطع نصية بعد</div>';
        return;
    }

    container.innerHTML = VoiceoverState.scriptSegments.map((seg, i) => `
        <div class="segment-item" data-idx="${i}">
            <div class="seg-time">${formatTime(seg.start)} → ${formatTime(seg.end)}</div>
            <div class="seg-text" contenteditable="true"
                 onblur="updateSegmentText(${i}, this.textContent)">${seg.text}</div>
            <button class="seg-del" onclick="deleteSegment(${i})">✕</button>
        </div>
    `).join('');
}

function updateSegmentText(idx, text) {
    if (VoiceoverState.scriptSegments[idx]) {
        VoiceoverState.scriptSegments[idx].text = text.trim();
    }
}

function deleteSegment(idx) {
    VoiceoverState.scriptSegments.splice(idx, 1);
    renderSegments();
}

function formatTime(s) {
    if (!isFinite(s)) s = 0;
    const m = Math.floor(s / 60);
    const sec = (s % 60).toFixed(1);
    return `${String(m).padStart(2, '0')}:${String(sec).padStart(4, '0')}`;
}


// ============================================================
// 🎵 اختيار ملف صوتي
// ============================================================
function pickAudioFile() {
    const input = document.getElementById('voiceoverFileInput');
    if (input) input.click();
}

async function handleAudioFileSelected(event) {
    const file = event.target.files?.[0];
    if (!file) return;

    if (!file.type.startsWith('audio/') && !file.name.match(/\.(mp3|wav|m4a|ogg|webm|aac|flac)$/i)) {
        showToast('❌ الرجاء اختيار ملف صوتي صالح', 'error');
        return;
    }

    if (file.size > 100 * 1024 * 1024) {
        showToast('❌ حجم الملف كبير جداً (الحد 100MB)', 'error');
        return;
    }

    await loadAudioFile(file);
}

async function loadAudioFile(file) {
    const url = URL.createObjectURL(file);

    VoiceoverState.pendingBlob = file;
    VoiceoverState.pendingUrl = url;
    VoiceoverState.pendingFileName = file.name;
    VoiceoverState.source = 'file';

    const audio = new Audio(url);
    await new Promise((resolve) => {
        audio.addEventListener('loadedmetadata', resolve, { once: true });
        audio.addEventListener('error', resolve, { once: true });
        setTimeout(resolve, 3000);
    });

    const duration = audio.duration || 0;
    VoiceoverState.pendingDuration = duration;

    renderAudioPreview(file, url, duration);

    const infoEl = document.getElementById('voiceoverFileInfo');
    infoEl.style.display = 'block';
    infoEl.innerHTML = `
        <div style="display:flex;align-items:center;gap:8px;">
            <span style="font-size:20px;">🎵</span>
            <div style="flex:1;min-width:0;">
                <div style="color:#e2e8f0;font-size:12px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
                    ${file.name}
                </div>
                <div style="color:#64748b;font-size:10px;">
                    ${(file.size / 1024 / 1024).toFixed(2)} MB • ${formatTime(duration)}
                </div>
            </div>
            <button onclick="clearAudioFile()" class="text-red-400 hover:text-red-300 text-lg">✕</button>
        </div>
    `;

    showSyncButton();
    showToast('✅ تم تحميل الملف. يمكنك الاستنساخ الآن', 'success');
}

function renderAudioPreview(file, url, duration) {
    const el = document.getElementById('voiceoverPreview');
    if (!el) return;

    el.innerHTML = `
        <div class="audio-file-preview">
            <audio controls src="${url}" style="width:100%;height:40px;" id="voiceoverAudioPreview"></audio>
            <div class="audio-waveform-placeholder" id="voiceoverWaveform">
                ${generateWaveformBars(60)}
            </div>
        </div>
    `;

    const audioEl = document.getElementById('voiceoverAudioPreview');
    const waveEl = document.getElementById('voiceoverWaveform');
    if (audioEl && waveEl) {
        audioEl.ontimeupdate = () => {
            const progress = (audioEl.currentTime / (audioEl.duration || 1)) * 100;
            waveEl.style.setProperty('--progress', progress + '%');
        };
    }
}

function generateWaveformBars(count) {
    let bars = '';
    for (let i = 0; i < count; i++) {
        const h = 20 + Math.random() * 60;
        bars += `<span style="height:${h}%"></span>`;
    }
    return bars;
}

function clearAudioFile() {
    if (VoiceoverState.pendingUrl) URL.revokeObjectURL(VoiceoverState.pendingUrl);
    VoiceoverState.pendingBlob = null;
    VoiceoverState.pendingUrl = null;
    VoiceoverState.pendingFileName = null;
    VoiceoverState.pendingDuration = 0;
    VoiceoverState.source = null;

    document.getElementById('voiceoverFileInfo').style.display = 'none';
    document.getElementById('voiceoverFileInfo').innerHTML = '';
    document.getElementById('voiceoverPreview').innerHTML = '';
    const input = document.getElementById('voiceoverFileInput');
    if (input) input.value = '';
    hideSyncButton();
}


// ============================================================
// 🎬 استخراج النص
// ============================================================
async function extractTranscriptFromFile() {
    if (!VoiceoverState.pendingBlob) {
        return showToast('⚠️ اختر ملفاً صوتياً أولاً', 'warning');
    }

    const useServer = confirm(
        'اختر طريقة الاستخراج:\n\n' +
        '✅ موافق = استخراج عبر الخادم (Whisper - أدق)\n' +
        '❌ إلغاء = استخراج محلي (أسرع، دقة أقل)'
    );

    if (useServer) {
        await extractTranscriptServer();
    } else {
        await extractTranscriptLocal();
    }
}

async function extractTranscriptServer() {
    const progressEl = showExtractProgress('🔄 جاري رفع الملف للخادم...');

    try {
        const formData = new FormData();
        formData.append('file', VoiceoverState.pendingBlob,
            VoiceoverState.pendingFileName || 'audio.webm');
        formData.append('language', 'ar');
        formData.append('with_timestamps', 'true');
        formData.append('model_size', 'base');

        const res = await fetch('/api/media/transcribe', {
            method: 'POST',
            body: formData
        });

        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (!data.success) throw new Error(data.error || 'فشل الاستخراج');

        document.getElementById('voiceoverScript').value = data.text || '';

        if (data.segments && data.segments.length) {
            VoiceoverState.scriptSegments = data.segments.map(s => ({
                text: s.text,
                start: s.start,
                end: s.end,
                speaker: 'المتحدث'
            }));
            renderSegments();
        }

        progressEl.remove();
        showToast(`✅ تم استخراج النص (${data.segments?.length || 0} مقطع)`, 'success');
    } catch (err) {
        progressEl.remove();
        showToast('❌ فشل الاستخراج: ' + err.message, 'error');
        console.error(err);
    }
}

async function extractTranscriptLocal() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) return showToast('❌ المتصفح لا يدعم التعرف على الكلام', 'error');

    showToast('🎧 سيتم تشغيل الملف واستخراج النص...', 'info');

    const audio = new Audio(VoiceoverState.pendingUrl);
    audio.volume = 1.0;

    const rec = new SR();
    rec.lang = 'ar-SA';
    rec.continuous = true;
    rec.interimResults = true;

    const segments = [];
    const startT = performance.now();
    let lastFinalEnd = 0;

    rec.onresult = (event) => {
        for (let i = event.resultIndex; i < event.results.length; i++) {
            const res = event.results[i];
            if (res.isFinal) {
                const text = res[0].transcript.trim();
                const now = (performance.now() - startT) / 1000;
                segments.push({
                    text: text,
                    start: lastFinalEnd,
                    end: now,
                    speaker: 'المتحدث'
                });
                lastFinalEnd = now;

                document.getElementById('voiceoverTranscript').innerHTML =
                    segments.map(s => s.text).join(' ');
            }
        }
    };

    rec.onerror = (e) => console.warn('SR:', e.error);

    audio.onended = () => {
        try { rec.stop(); } catch (e) { }
        VoiceoverState.scriptSegments = segments;

        const fullText = segments.map(s => s.text).join(' ');
        document.getElementById('voiceoverScript').value = fullText;
        renderSegments();

        showToast(`✅ تم استخراج ${segments.length} مقطع`, 'success');
    };

    try {
        rec.start();
        await audio.play();
    } catch (err) {
        showToast('❌ فشل التشغيل: ' + err.message, 'error');
    }
}

function showExtractProgress(text) {
    const el = document.createElement('div');
    el.className = 'extract-progress';
    el.innerHTML = `
        <div class="spinner" style="width:16px;height:16px;border-width:2px;"></div>
        <span>${text}</span>
    `;
    document.getElementById('voiceoverPreview')?.appendChild(el);
    return el;
}


// ============================================================
// 💾 حفظ موحّد
// ============================================================
async function saveVoiceoverUnified() {
    const mode = document.querySelector('input[name="voiceoverMode"]:checked')?.value || 'tts';

    if (mode === 'file') {
        return saveAudioFileToTimeline();
    }
    if (mode === 'record') {
        return saveRecordingToTimeline();
    }
    return saveTTSToTimeline();
}


// ============================================================
// 💾 حفظ TTS
// ============================================================
async function saveTTSToTimeline() {
    const title = document.getElementById('voiceoverTitle').value.trim() || 'مقطع صوتي (TTS)';
    const script = document.getElementById('voiceoverScript').value.trim();

    if (!script) {
        return showToast('⚠️ اكتب النص أولاً', 'warning');
    }

    const voiceName = document.getElementById('voiceoverVoiceSelect').value;
    const voice = VoiceoverState.ttsVoices.find(v => v.name === voiceName);

    const segments = VoiceoverState.scriptSegments.length
        ? VoiceoverState.scriptSegments
        : autoSegmentScript(script);

    const clipData = {
        type: 'audio',
        title: title,
        script: script,
        script_segments: segments,
        tts: {
            voiceName: voice?.name || null,
            voiceLang: voice?.lang || 'ar-SA',
            rate: parseFloat(document.getElementById('voiceoverRate').value) || 1,
            pitch: parseFloat(document.getElementById('voiceoverPitch').value) || 1,
        },
        duration: estimateSpeechDuration(script),
        start: safeGetCurrentTime(),
        source: 'tts',
        url: null,
    };

    await addVoiceoverClip(clipData);
    showToast('✅ تم إضافة المقطع الصوتي (TTS)', 'success');
    closeVoiceoverStudio();
}


// ============================================================
// 💾 حفظ التسجيل
// ============================================================
async function saveRecordingToTimeline() {
    if (!VoiceoverState.pendingBlob) {
        return showToast('⚠️ لم يتم تسجيل صوت بعد', 'warning');
    }

    const title = document.getElementById('voiceoverTitle').value.trim() || 'تسجيل صوتي';
    const script = document.getElementById('voiceoverScript').value.trim();

    const formData = new FormData();
    formData.append('file', VoiceoverState.pendingBlob, `voiceover_${Date.now()}.webm`);
    formData.append('project_id', safeGetProjectId());
    formData.append('title', title);
    formData.append('script', script);
    formData.append('script_segments', JSON.stringify(VoiceoverState.scriptSegments));
    formData.append('source', 'recording');
    formData.append('start', String(safeGetCurrentTime()));

    try {
        const res = await fetch('/api/media/upload-voiceover', {
            method: 'POST',
            body: formData
        });
        const data = await res.json();
        if (!data.success) throw new Error(data.error || 'فشل الرفع');

        await addVoiceoverClip({
            type: 'audio',
            title: title,
            url: data.url,
            path: data.path,
            mediaId: data.media_id,
            script: script,
            script_segments: VoiceoverState.scriptSegments,
            duration: data.duration || VoiceoverState.pendingDuration || 3,
            start: safeGetCurrentTime(),
            source: 'recording',
        });

        showToast('✅ تم حفظ التسجيل في المشروع', 'success');
        closeVoiceoverStudio();
    } catch (err) {
        showToast('❌ فشل رفع التسجيل: ' + err.message, 'error');
    }
}


// ============================================================
// 💾 حفظ الملف الصوتي
// ============================================================
async function saveAudioFileToTimeline() {
    if (!VoiceoverState.pendingBlob) {
        return showToast('⚠️ اختر ملفاً صوتياً أولاً', 'warning');
    }

    const title = document.getElementById('voiceoverTitle').value.trim() ||
        VoiceoverState.pendingFileName || 'مقطع صوتي';
    const script = document.getElementById('voiceoverScript').value.trim();

    const formData = new FormData();
    formData.append('file', VoiceoverState.pendingBlob,
        VoiceoverState.pendingFileName || 'audio.webm');
    formData.append('project_id', safeGetProjectId());
    formData.append('title', title);
    formData.append('script', script);
    formData.append('script_segments', JSON.stringify(VoiceoverState.scriptSegments));
    formData.append('source', 'file');
    formData.append('start', String(safeGetCurrentTime()));

    try {
        const res = await fetch('/api/media/upload-voiceover', {
            method: 'POST',
            body: formData
        });
        const data = await res.json();
        if (!data.success) throw new Error(data.error || 'فشل الرفع');

        await addVoiceoverClip({
            type: 'audio',
            title: title,
            url: data.url,
            path: data.path,
            mediaId: data.media_id,
            script: script,
            script_segments: VoiceoverState.scriptSegments,
            duration: data.duration || VoiceoverState.pendingDuration || 3,
            start: safeGetCurrentTime(),
            source: 'file',
            fileName: VoiceoverState.pendingFileName,
        });

        showToast('✅ تم حفظ الملف الصوتي في المشروع', 'success');
        closeVoiceoverStudio();
    } catch (err) {
        showToast('❌ فشل الرفع: ' + err.message, 'error');
    }
}


// ============================================================
// ✅ إضافة مقطع للخط الزمني — متوافق مع timeline-core.js
// ============================================================
async function addVoiceoverClip(clipData) {
    // ── 1. التحقق من projectData ─────────────────────
    if (typeof projectData === 'undefined') {
        console.error('❌ projectData غير معرّف');
        showToast('❌ خطأ في النظام — أعد تحميل الصفحة', 'error');
        return null;
    }

    if (!projectData.clips) projectData.clips = [];
    if (!projectData.layers) {
        projectData.layers = [{ name: 'طبقة 1', visible: true, locked: false }];
    }

    // ── 2. تحديد الطبقة كرقم ────────────────────────
    let layerIndex = 0;
    if (typeof selectedLayerIndex !== 'undefined' && selectedLayerIndex != null) {
        layerIndex = selectedLayerIndex;
    }
    if (clipData.layer !== undefined && clipData.layer !== null) {
        layerIndex = clipData.layer;
    }

    // ── 3. توليد ID رقمي ────────────────────────────
    let newId;
    if (typeof clipIdCounter !== 'undefined') {
        newId = clipIdCounter++;
    } else {
        const existingIds = projectData.clips
            .map(c => typeof c.id === 'number' ? c.id : 0)
            .filter(id => id > 0);
        newId = existingIds.length > 0 ? Math.max(...existingIds) + 1 : 1;
        window.clipIdCounter = newId + 1;
    }

    // ── 4. حساب البداية والمدة ──────────────────────
    const startTime = (typeof clipData.start === 'number' && clipData.start >= 0)
        ? clipData.start
        : safeGetCurrentTime();

    let duration = clipData.duration || 0;
    if (duration <= 0 && clipData.script) {
        duration = estimateSpeechDuration(clipData.script);
    }
    if (duration <= 0) duration = 3;

    // ── 5. بناء المقطع ──────────────────────────────
    const clip = {
        // حقول أساسية (مطلوبة)
        id: newId,
        type: clipData.type || 'audio',
        layer: layerIndex,
        start: round2(startTime),
        duration: round2(duration),
        title: clipData.title || `مقطع صوتي ${newId}`,
        content: clipData.url || null,
        color: clipData.color || '#059669',
        icon: clipData.icon || '🎤',

        // حقول إضافية
        url: clipData.url || null,
        path: clipData.path || null,
        mediaId: clipData.mediaId || null,
        script: clipData.script || '',
        scriptSegments: clipData.script_segments || clipData.scriptSegments || [],
        tts: clipData.tts || null,
        source: clipData.source || 'tts',
        fileName: clipData.fileName || null,
        voice_id: clipData.voice_id || null,
        processed: clipData.processed || false,
        processingOptions: clipData.processingOptions || null,
        metadata: clipData.metadata || {},
    };

    // ── 6. أضف المقطع ──────────────────────────────
    projectData.clips.push(clip);
    console.log(`✅ [addVoiceoverClip] مقطع جديد id=${newId}`, clip);

    // ── 7. حدّث المدة الإجمالية ─────────────────────
    const endTime = clip.start + clip.duration;
    if (endTime > (projectData.totalDuration || 0)) {
        projectData.totalDuration = endTime + 2;
    }

    // ── 8. إعادة الرسم ─────────────────────────────
    try {
        if (typeof renderTimeline === 'function') {
            renderTimeline();
            console.log('🔄 [addVoiceoverClip] renderTimeline() نُفِّذ');
        } else {
            console.warn('⚠️ renderTimeline غير معرّفة');
        }
    } catch (e) {
        console.error('❌ خطأ في renderTimeline:', e);
    }

    try {
        if (typeof renderLayers === 'function') renderLayers();
    } catch (e) { console.warn('renderLayers:', e); }

    try {
        if (typeof updateStatus === 'function') updateStatus();
    } catch (e) { console.warn('updateStatus:', e); }

    try {
        if (typeof renderPreview === 'function') renderPreview(safeGetCurrentTime());
    } catch (e) { console.warn('renderPreview:', e); }

    // ── 9. احفظ في السحابة ─────────────────────────
    if (typeof saveProjectData === 'function') {
        try {
            await saveProjectData();
            console.log('✅ [addVoiceoverClip] تم الحفظ');
        } catch (e) {
            console.warn('⚠️ فشل الحفظ:', e);
        }
    }

    // ── 10. Scroll للمقطع الجديد ────────────────────
    setTimeout(() => {
        try { scrollToClipById(newId); } catch (e) { }
    }, 300);

    return clip;
}


/**
 * تمرير الخط الزمني لمقطع + وميض
 */
function scrollToClipById(clipId) {
    const clipEl = document.querySelector(`.clip-block[data-id="${clipId}"]`) ||
                   document.querySelector(`[data-clip-id="${clipId}"]`);

    if (!clipEl) {
        console.log(`ℹ️ لم يُعثر على clip-block للمقطع ${clipId}`);
        return;
    }

    clipEl.scrollIntoView({
        behavior: 'smooth',
        block: 'nearest',
        inline: 'center',
    });

    clipEl.style.transition = 'box-shadow 0.5s';
    clipEl.style.boxShadow = '0 0 20px 4px rgba(59, 130, 246, 0.8)';
    setTimeout(() => { clipEl.style.boxShadow = ''; }, 1500);
}


// ============================================================
// أدوات مساعدة
// ============================================================
function autoSegmentScript(script, wordsPerSecond = 2.5) {
    const sentences = script.split(/[.!?؟।\n]+/).filter(s => s.trim());
    let t = 0;
    return sentences.map(s => {
        const dur = Math.max(1, s.trim().split(/\s+/).length / wordsPerSecond);
        const seg = {
            text: s.trim(),
            start: round2(t),
            end: round2(t + dur),
            speaker: 'المتحدث'
        };
        t += dur;
        return seg;
    });
}

function estimateSpeechDuration(script, wordsPerSecond = 2.5) {
    const words = script.trim().split(/\s+/).length;
    return Math.max(1, words / wordsPerSecond);
}

function getCurrentPlayheadTime() {
    return safeGetCurrentTime();
}

function round2(n) {
    return Math.round(n * 100) / 100;
}

function escapeHtml(text) {
    if (!text) return '';
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}


// ============================================================
// تشغيل النص أثناء العرض
// ============================================================
function syncScriptWithPlayback(playbackTime) {
    const pd = safeGetProjectData();
    if (!pd.clips) return;

    const audioClips = pd.clips.filter(c =>
        c.type === 'audio' && c.scriptSegments?.length
    );

    for (const clip of audioClips) {
        const localT = playbackTime - clip.start;
        if (localT < 0 || localT > clip.duration) continue;

        const activeSeg = clip.scriptSegments.find(s =>
            localT >= s.start && localT <= s.end
        );
        if (activeSeg) {
            showScriptOverlay(activeSeg.text, clip.title);
            return;
        }
    }
}

function showScriptOverlay(text, title) {
    const el = document.getElementById('scriptOverlay');
    if (!el) return;

    const titleEl = document.getElementById('scriptOverlayTitle');
    const textEl = document.getElementById('scriptOverlayText');
    if (titleEl) titleEl.textContent = title || '';
    if (textEl) textEl.textContent = text || '';
    el.classList.add('visible');

    clearTimeout(el._hideTimer);
    el._hideTimer = setTimeout(() => el.classList.remove('visible'), 2500);
}


// ============================================================
// 🎙️ VOICE CLONING
// ============================================================
function initSavedVoices() {
    try {
        const configEl = document.getElementById('timeline-config');
        if (!configEl) return;
        const config = JSON.parse(configEl.textContent);
        VoiceCloneState.savedVoices = config.savedVoices || [];
    } catch (e) {
        VoiceCloneState.savedVoices = [];
    }
}


function openVoiceCloneModal() {
    if (!VoiceoverState.pendingBlob) {
        return showToast('⚠️ سجّل صوتك أو اختر ملفاً أولاً', 'warning');
    }

    const modal = document.getElementById('voiceCloneModal');
    if (!modal) return;

    initSavedVoices();
    VoiceCloneState.selectedVoiceId = null;

    renderVoiceCloneRawAudio();
    renderSavedVoicesList();
    renderScriptForVoiceClone();

    const player = document.getElementById('generatedAudioPlayer');
    if (player) player.style.display = 'none';

    const statusEl = document.getElementById('voiceCloneStatus');
    if (statusEl) statusEl.innerHTML = '';

    const genBtn = document.getElementById('btnGenerateWithVoice');
    if (genBtn) genBtn.disabled = true;

    modal.classList.remove('hidden');
}


function closeVoiceCloneModal() {
    const modal = document.getElementById('voiceCloneModal');
    if (modal) modal.classList.add('hidden');
}


function renderVoiceCloneRawAudio() {
    const el = document.getElementById('voiceCloneRawAudio');
    if (!el) return;

    const url = URL.createObjectURL(VoiceoverState.pendingBlob);
    el.innerHTML = `
        <audio controls src="${url}" style="width:100%;height:36px;"></audio>
        <div class="sync-audio-meta">
            <span>🎤 صوتك المرجعي</span>
            <span>💾 ${(VoiceoverState.pendingBlob.size / 1024).toFixed(1)} KB</span>
            <span>🔊 ${VoiceoverState.source === 'recording' ? 'تسجيل مباشر' : 'ملف مرفوع'}</span>
        </div>
    `;
}


function renderScriptForVoiceClone() {
    const scriptEl = document.getElementById('voiceCloneScript');
    const originalScript = document.getElementById('voiceoverScript');

    if (scriptEl && originalScript && originalScript.value) {
        scriptEl.value = originalScript.value;
    }

    updateCharCounter();
}


function updateCharCounter() {
    const ta = document.getElementById('voiceCloneScript');
    const counter = document.getElementById('voiceCloneCharCount');
    if (!ta || !counter) return;

    const len = ta.value.length;
    counter.textContent = `${len} حرف`;

    counter.classList.remove('warning', 'danger');
    if (len > 9000) {
        counter.classList.add('danger');
    } else if (len > 8000) {
        counter.classList.add('warning');
    }
}


// ============================================================
// 🎙️ قائمة الأصوات المحفوظة
// ============================================================
function renderSavedVoicesList() {
    const el = document.getElementById('savedVoicesList');
    if (!el) return;

    const voices = VoiceCloneState.savedVoices;

    if (!voices.length) {
        el.innerHTML = `
            <div class="voice-empty-state">
                <div style="font-size:32px;margin-bottom:8px;">🎙️</div>
                <div style="color:#94a3b8;font-size:12px;">
                    لا توجد أصوات محفوظة بعد
                </div>
                <div style="color:#64748b;font-size:10px;margin-top:4px;">
                    اضغط "استنسخ صوتي" لإنشاء صوتك الأول
                </div>
                <div style="color:#64748b;font-size:10px;margin-top:4px;">
                    أو اختر صوتاً جاهزاً من الأسفل
                </div>
            </div>
        `;
        return;
    }

    el.innerHTML = voices.map((voice) => {
        const isSelected = VoiceCloneState.selectedVoiceId === voice.voice_id;
        const displayName = voice.display_name || voice.name || 'صوت بدون اسم';
        const dateStr = voice.created_at
            ? new Date(voice.created_at).toLocaleDateString('ar-EG')
            : '';

        let providerBadge = '';
        if (voice.provider === 'edge_tts') {
            providerBadge = '<span style="background:rgba(16,185,129,0.2);color:#34d399;padding:1px 6px;border-radius:8px;font-size:9px;margin-right:4px;">🔊 Edge TTS</span>';
        } else if (voice.provider === 'huggingface') {
            providerBadge = '<span style="background:rgba(59,130,246,0.2);color:#60a5fa;padding:1px 6px;border-radius:8px;font-size:9px;margin-right:4px;">🤗 HuggingFace</span>';
        } else if (voice.provider === 'elevenlabs') {
            providerBadge = '<span style="background:rgba(124,58,237,0.2);color:#a78bfa;padding:1px 6px;border-radius:8px;font-size:9px;margin-right:4px;">✨ ElevenLabs</span>';
        }

        return `
            <div class="saved-voice-item ${isSelected ? 'selected' : ''} ${voice.imported ? 'imported' : ''}"
                 data-voice-id="${voice.voice_id}"
                 onclick="selectSavedVoice('${voice.voice_id}')">

                <div class="saved-voice-icon">🎙️</div>

                <div class="saved-voice-info">
                    <div class="saved-voice-name">
                        ${providerBadge}
                        ${escapeHtml(displayName)}
                    </div>
                    <div class="saved-voice-meta">
                        ${dateStr}
                        ${voice.imported ? ' • 📥 مستورد' : ''}
                        ${voice.temporary ? ' • ⏱️ مؤقت' : ''}
                    </div>
                </div>

                <div class="saved-voice-actions">
                    <button class="saved-voice-btn"
                            onclick="event.stopPropagation(); previewSavedVoice('${voice.voice_id}', this)"
                            title="معاينة سريعة">▶️</button>
                    <button class="saved-voice-btn"
                            onclick="event.stopPropagation(); renameVoice('${voice.id}', '${escapeHtml(displayName)}')"
                            title="إعادة تسمية">✏️</button>
                    <button class="saved-voice-btn danger"
                            onclick="event.stopPropagation(); deleteSavedVoice('${voice.id}', '${escapeHtml(displayName)}')"
                            title="حذف">🗑️</button>
                </div>

                <div class="saved-voice-check">${isSelected ? '✓' : ''}</div>
            </div>
        `;
    }).join('');
}


function selectSavedVoice(voiceId) {
    VoiceCloneState.selectedVoiceId = voiceId;
    renderSavedVoicesList();

    const genBtn = document.getElementById('btnGenerateWithVoice');
    if (genBtn) genBtn.disabled = false;

    const statusEl = document.getElementById('voiceCloneStatus');
    if (statusEl) {
        const voice = VoiceCloneState.savedVoices.find(v => v.voice_id === voiceId);
        statusEl.innerHTML = `
            <div style="color:#34d399;font-size:12px;">
                ✅ تم اختيار: <strong>${escapeHtml(voice?.display_name || voice?.name || voiceId)}</strong>
                ${voice?.provider ? `<span style="color:#64748b;"> (${voice.provider})</span>` : ''}
            </div>
        `;
    }
}


// ============================================================
// 🎙️ استنساخ صوت جديد
// ============================================================
async function cloneVoiceAndSave() {
    if (!VoiceoverState.pendingBlob) {
        return showToast('⚠️ لا يوجد صوت مرجعي', 'warning');
    }

    const nameInput = document.getElementById('newVoiceName');
    const displayName = (nameInput?.value || '').trim() || 'صوتي';

    const btn = document.getElementById('btnCloneVoice');
    const statusEl = document.getElementById('voiceCloneStatus');

    btn.disabled = true;
    btn.innerHTML = '⏳ جاري الاستنساخ...';

    if (statusEl) {
        statusEl.innerHTML = `
            <div style="color:#fbbf24;">
                🎙️ جاري تحليل صوتك وإنشاء نسخة ذكية...
                <br><small>يستغرق 20-60 ثانية</small>
            </div>
        `;
    }

    try {
        const formData = new FormData();
        formData.append('file', VoiceoverState.pendingBlob, 'my_voice.webm');
        formData.append('name', displayName);
        formData.append('description', displayName);
        formData.append('project_id', safeGetProjectId());

        const res = await fetch('/api/voice/clone', {
            method: 'POST',
            body: formData,
        });

        let data;
        try {
            data = await res.json();
        } catch (e) {
            const text = await res.text();
            throw new Error(text || `HTTP ${res.status}`);
        }

        if (!data.success) {
            throw new Error(data.error || data.detail || 'فشل الاستنساخ');
        }

        const saveRes = await fetch(`/api/voice/saved/${safeGetProjectId()}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                voice_id: data.voice_id,
                name: data.name,
                display_name: displayName,
                description: displayName,
                provider: data.provider || 'huggingface',
                temporary: data.temporary || false,
            }),
        });

        const saveData = await saveRes.json();
        if (!saveData.success) {
            throw new Error(saveData.error || 'فشل حفظ الصوت');
        }

        VoiceCloneState.savedVoices.push(saveData.voice);
        VoiceCloneState.selectedVoiceId = data.voice_id;

        renderSavedVoicesList();

        if (statusEl) {
            const providerMsg = data.provider === 'huggingface' && data.temporary
                ? '<br><small style="color:#f59e0b;">⚠️ HuggingFace: ستحتاج رفع المرجع في كل مرة</small>'
                : '';

            statusEl.innerHTML = `
                <div style="color:#34d399;background:rgba(52,211,153,0.1);
                            border:1px solid rgba(52,211,153,0.3);
                            border-radius:8px;padding:10px;font-size:12px;line-height:1.8;">
                    ✅ تم استنساخ الصوت!
                    <br>🎙️ <strong>${escapeHtml(displayName)}</strong>
                    <br>📡 المزود: <strong>${data.provider || 'auto'}</strong>
                    ${providerMsg}
                    <br>💡 يمكنك الآن توليد النص بصوتك
                </div>
            `;
        }

        showToast(`🎙️ تم حفظ الصوت "${displayName}"`, 'success');

        const genBtn = document.getElementById('btnGenerateWithVoice');
        if (genBtn) genBtn.disabled = false;

        if (nameInput) nameInput.value = '';

    } catch (err) {
        console.error(err);
        if (statusEl) {
            statusEl.innerHTML = `
                <div style="color:#ef4444;background:rgba(239,68,68,0.1);
                            border:1px solid rgba(239,68,68,0.3);
                            border-radius:8px;padding:10px;font-size:11px;
                            line-height:1.8;white-space:pre-wrap;direction:rtl;">
                    ❌ ${err.message}
                </div>
            `;
        }
        showToast('❌ فشل الاستنساخ', 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '🎙️ استنسخ صوتي';
    }
}


// ============================================================
// 🔊 تحميل أصوات Edge TTS
// ============================================================
async function loadEdgeVoices() {
    const select = document.getElementById('edgeVoiceSelect');
    if (!select) return;

    try {
        const res = await fetch('/api/voice/edge-voices');
        const data = await res.json();

        if (data.success && data.voices) {
            VoiceCloneState.edgeVoices = data.voices;
            select.innerHTML = '<option value="">— اختر صوتاً جاهزاً —</option>';
            data.voices.forEach(v => {
                const opt = document.createElement('option');
                opt.value = v.id;
                opt.textContent = `${v.name} (${v.lang})`;
                select.appendChild(opt);
            });
        }
    } catch (e) {
        console.warn('Failed to load edge voices:', e);
        const fallbackVoices = [
            { id: 'ar-SA-HamedNeural', name: 'حامد (سعودي)', lang: 'ar-SA' },
            { id: 'ar-SA-ZariyahNeural', name: 'زارية (سعودية)', lang: 'ar-SA' },
            { id: 'ar-EG-ShakirNeural', name: 'شاكر (مصري)', lang: 'ar-EG' },
            { id: 'ar-EG-SalmaNeural', name: 'سلمى (مصرية)', lang: 'ar-EG' },
        ];
        VoiceCloneState.edgeVoices = fallbackVoices;
        select.innerHTML = '<option value="">— اختر صوتاً جاهزاً —</option>';
        fallbackVoices.forEach(v => {
            const opt = document.createElement('option');
            opt.value = v.id;
            opt.textContent = `${v.name} (${v.lang})`;
            select.appendChild(opt);
        });
    }
}


function selectEdgeVoice(voiceId) {
    if (!voiceId) return;

    const voiceInfo = VoiceCloneState.edgeVoices.find(v => v.id === voiceId);
    const displayName = voiceInfo ? `🔊 ${voiceInfo.name}` : `🔊 ${voiceId}`;

    let voice = VoiceCloneState.savedVoices.find(v => v.voice_id === voiceId);
    if (!voice) {
        voice = {
            id: `edge-${voiceId}`,
            voice_id: voiceId,
            name: voiceId,
            display_name: displayName,
            provider: 'edge_tts',
            created_at: new Date().toISOString(),
            temporary: false,
        };
        VoiceCloneState.savedVoices.push(voice);
        renderSavedVoicesList();
    }

    VoiceCloneState.selectedVoiceId = voiceId;

    const genBtn = document.getElementById('btnGenerateWithVoice');
    if (genBtn) genBtn.disabled = false;

    const statusEl = document.getElementById('voiceCloneStatus');
    if (statusEl) {
        statusEl.innerHTML = `
            <div style="color:#34d399;font-size:12px;">
                ✅ تم اختيار صوت Edge TTS: <strong>${displayName}</strong>
            </div>
        `;
    }

    showToast(`🔊 تم اختيار: ${displayName}`, 'success');
}


// ============================================================
// 🎙️ توليد النص بالصوت المُختار
// ============================================================
async function generateWithCache() {
    if (!VoiceCloneState.selectedVoiceId) {
        return showToast('⚠️ اختر صوتاً أولاً', 'warning');
    }

    const script = document.getElementById('voiceCloneScript').value.trim();
    if (!script) {
        return showToast('⚠️ اكتب النص أولاً', 'warning');
    }

    if (script.length > 10000) {
        return showToast('⚠️ النص طويل جداً (الحد 10000 حرف)', 'warning');
    }

    const btn = document.getElementById('btnGenerateWithVoice');
    const statusEl = document.getElementById('voiceCloneStatus');
    const useCache = document.getElementById('useCacheCheckbox')?.checked ?? true;

    btn.disabled = true;
    btn.innerHTML = '⏳ جاري التوليد...';

    const selectedVoice = VoiceCloneState.savedVoices.find(
        v => v.voice_id === VoiceCloneState.selectedVoiceId
    );
    const isHuggingFace = selectedVoice?.provider === 'huggingface';

    if (statusEl) {
        statusEl.innerHTML = `
            <div style="color:#fbbf24;">
                🎙️ ${isHuggingFace ? 'جاري الاستنساخ عبر HuggingFace (قد يستغرق 1-3 دقائق)...' : 'جاري التوليد...'}
                ${useCache && !isHuggingFace ? '<br><small>💾 سيُستخدم Cache إن وُجد</small>' : ''}
            </div>
        `;
    }

    try {
        let res, remoteUrl, duration, cacheHit, provider;

        if (isHuggingFace && VoiceoverState.pendingBlob) {
            const formData = new FormData();
            formData.append('file', VoiceoverState.pendingBlob, 'reference.webm');
            formData.append('text', script);
            formData.append('language', 'ar');
            formData.append('project_id', safeGetProjectId());

            res = await fetch('/api/voice/hf-clone', {
                method: 'POST',
                body: formData,
            });

            if (!res.ok) {
                const errData = await res.json().catch(() => ({}));
                throw new Error(errData.error || errData.detail || `HTTP ${res.status}`);
            }

            remoteUrl = res.headers.get('X-Cloned-URL');
            duration = parseFloat(res.headers.get('X-Duration') || '0');
            cacheHit = false;
            provider = 'huggingface';
        }
        else {
            const formData = new FormData();
            formData.append('voice_id', VoiceCloneState.selectedVoiceId);
            formData.append('script', script);
            formData.append('project_id', safeGetProjectId());
            formData.append('use_cache', useCache ? 'true' : 'false');
            formData.append('speed', '1.0');

            res = await fetch('/api/voice/generate-cached', {
                method: 'POST',
                body: formData,
            });

            if (!res.ok) {
                const errData = await res.json().catch(() => ({}));
                throw new Error(errData.error || errData.detail || `HTTP ${res.status}`);
            }

            remoteUrl = res.headers.get('X-Cloned-URL');
            duration = parseFloat(res.headers.get('X-Duration') || '0');
            cacheHit = res.headers.get('X-Cache-Hit') === 'true';
            provider = res.headers.get('X-Provider') || 'edge_tts';
        }

        const blob = await res.blob();
        const localUrl = URL.createObjectURL(blob);

        SyncProcessState.processedBlob = blob;
        SyncProcessState.processedUrl = localUrl;
        SyncProcessState.clonedRemoteUrl = remoteUrl;
        SyncProcessState.clonedDuration = duration;
        SyncProcessState.clonedVoiceId = VoiceCloneState.selectedVoiceId;

        const originalScript = document.getElementById('voiceoverScript');
        if (originalScript) originalScript.value = script;

        if (!VoiceoverState.scriptSegments.length) {
            VoiceoverState.scriptSegments = autoSegmentScript(script);
        }

        const totalChars = VoiceoverState.scriptSegments.reduce((sum, s) => sum + s.text.length, 0);
        let cursor = 0;
        VoiceoverState.scriptSegments.forEach((seg) => {
            const ratio = totalChars > 0 ? seg.text.length / totalChars : 0;
            const dur = duration * ratio;
            seg.start = round2(cursor);
            seg.end = round2(Math.min(cursor + dur, duration));
            cursor = seg.end;
        });
        if (VoiceoverState.scriptSegments.length > 0) {
            VoiceoverState.scriptSegments[VoiceoverState.scriptSegments.length - 1].end = round2(duration);
        }

        SyncProcessState.isAligned = true;

        renderGeneratedAudio(localUrl, duration, script, cacheHit, provider);

        if (statusEl) {
            statusEl.innerHTML = `
                <div style="color:#34d399;background:rgba(52,211,153,0.1);
                            border:1px solid rgba(52,211,153,0.3);
                            border-radius:8px;padding:10px;font-size:12px;line-height:1.8;">
                    ${cacheHit ? '💾 من Cache (بدون استهلاك)' : '✅ تم التوليد بنجاح!'}
                    <br>📡 المزود: <strong>${provider}</strong>
                    <br>⏱️ المدة: ${duration.toFixed(1)} ثانية
                    <br>📝 الأحرف: ${script.length}
                    <br><br>💡 اضغط "حفظ في المشروع" لإضافته للخط الزمني
                </div>
            `;
        }

        showToast(
            cacheHit ? '💾 تم الجلب من Cache' : '🎙️ تم التوليد — اضغط حفظ',
            'success'
        );

    } catch (err) {
        console.error(err);
        if (statusEl) {
            statusEl.innerHTML = `
                <div style="color:#ef4444;background:rgba(239,68,68,0.1);
                            border:1px solid rgba(239,68,68,0.3);
                            border-radius:8px;padding:10px;font-size:11px;
                            line-height:1.8;white-space:pre-wrap;direction:rtl;">
                    ❌ ${err.message}
                </div>
            `;
        }
        showToast('❌ فشل التوليد', 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '🎙️ توليد النص بصوتي';
    }
}


// ============================================================
// 🎬 عرض الصوت المُولَّد
// ============================================================
function renderGeneratedAudio(localUrl, duration, script, cacheHit = false, provider = 'edge_tts') {
    const el = document.getElementById('generatedAudioPlayer');
    if (!el) return;

    const providerBadge = {
        'edge_tts': '<span class="sync-badge-green">🔊 Edge TTS</span>',
        'huggingface': '<span class="sync-badge-green">🤗 HuggingFace</span>',
        'elevenlabs': '<span class="sync-badge-green">✨ ElevenLabs</span>',
    }[provider] || '<span class="sync-badge-green">✨ AI</span>';

    el.style.display = 'block';
    el.innerHTML = `
        <div class="sync-audio-container">
            <audio controls src="${localUrl}"
                   style="width:100%;height:36px;" id="generatedPlayer"></audio>
            <div class="sync-audio-meta">
                <span>🎙️ صوت مُولَّد</span>
                <span>⏱️ ${formatTime(duration)}</span>
                ${cacheHit ? '<span class="cache-badge">من Cache</span>' : providerBadge}
            </div>
            <div style="display:flex;gap:8px;margin-top:10px;">
                <button onclick="saveGeneratedToProject()" class="btn-primary btn-sm" style="flex:1;">
                    💾 حفظ في المشروع (أضف للخط الزمني)
                </button>
                <button onclick="downloadGenerated()" class="btn-secondary btn-sm">
                    ⬇️ تحميل
                </button>
            </div>
        </div>
    `;

    setTimeout(() => {
        const player = document.getElementById('generatedPlayer');
        if (player) player.play().catch(() => {});
    }, 100);
}


// ============================================================
// 💾 حفظ الصوت المُولَّد — مع إغلاق تلقائي
// ============================================================
async function saveGeneratedToProject() {
    if (!SyncProcessState.processedBlob) {
        return showToast('⚠️ لا يوجد صوت مُولَّد', 'warning');
    }

    const scriptEl = document.getElementById('voiceCloneScript');
    const script = scriptEl?.value.trim() || '';
    const titleInput = document.getElementById('voiceoverTitle');
    const title = (titleInput?.value || '').trim() || 'صوت مُولَّد';

    const selectedVoice = VoiceCloneState.savedVoices.find(
        v => v.voice_id === VoiceCloneState.selectedVoiceId
    );
    const source = selectedVoice?.provider === 'edge_tts' ? 'tts' : 'cloned';

    const formData = new FormData();
    formData.append('file', SyncProcessState.processedBlob, 'generated.mp3');
    formData.append('project_id', safeGetProjectId());
    formData.append('title', title);
    formData.append('script', script);
    formData.append('script_segments', JSON.stringify(VoiceoverState.scriptSegments));
    formData.append('source', source);
    formData.append('start', String(safeGetCurrentTime()));
    formData.append('processed', 'true');
    formData.append('processing_options', JSON.stringify({
        voice_id: VoiceCloneState.selectedVoiceId,
        provider: selectedVoice?.provider || 'edge_tts',
    }));

    try {
        const res = await fetch('/api/media/upload-voiceover', {
            method: 'POST',
            body: formData,
        });
        const data = await res.json();
        if (!data.success) throw new Error(data.error || 'فشل الحفظ');

        // ✅ إضافة المقطع للخط الزمني
        const addedClip = await addVoiceoverClip({
            type: 'audio',
            title: title,
            url: data.url,
            path: data.path,
            mediaId: data.media_id,
            script: script,
            script_segments: VoiceoverState.scriptSegments,
            duration: data.duration || SyncProcessState.clonedDuration || 0,
            start: safeGetCurrentTime(),
            source: source,
            processed: true,
            voice_id: VoiceCloneState.selectedVoiceId,
        });

        if (addedClip) {
            showToast('✅ تم إضافة المقطع للخط الزمني', 'success');
        } else {
            showToast('⚠️ تم الحفظ لكن فشلت الإضافة للخط الزمني', 'warning');
        }

        // ✅ أغلق النافذة تلقائياً بعد الحفظ
        setTimeout(() => {
            closeVoiceCloneModal();
            closeVoiceoverStudio();
        }, 500);

    } catch (err) {
        console.error(err);
        showToast('❌ فشل الحفظ: ' + err.message, 'error');
    }
}


// ============================================================
// ⬇️ تحميل
// ============================================================
function downloadGenerated() {
    if (!SyncProcessState.processedUrl) return;
    const a = document.createElement('a');
    a.href = SyncProcessState.processedUrl;
    a.download = `voice_${Date.now()}.mp3`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}


// ============================================================
// ▶️ معاينة سريعة
// ============================================================
async function previewSavedVoice(voiceId, btn) {
    const originalText = btn.innerHTML;
    btn.innerHTML = '⏳';
    btn.disabled = true;

    try {
        const formData = new FormData();
        formData.append('voice_id', voiceId);
        formData.append('text', 'مرحباً، هذا اختبار لصوتي.');

        const res = await fetch('/api/voice/preview', {
            method: 'POST',
            body: formData,
        });

        if (!res.ok) {
            throw new Error(`HTTP ${res.status}`);
        }

        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);

        btn.innerHTML = '🔊';
        audio.play();

        audio.onended = () => {
            btn.innerHTML = originalText;
            btn.disabled = false;
            URL.revokeObjectURL(url);
        };

        audio.onerror = () => {
            btn.innerHTML = originalText;
            btn.disabled = false;
            showToast('❌ فشل التشغيل', 'error');
        };

    } catch (err) {
        console.error(err);
        showToast('❌ فشل المعاينة: ' + err.message, 'error');
        btn.innerHTML = originalText;
        btn.disabled = false;
    }
}


// ============================================================
// ✏️ إعادة تسمية
// ============================================================
async function renameVoice(recordId, currentName) {
    const newName = prompt('الاسم الجديد:', currentName);
    if (!newName || newName === currentName) return;

    try {
        const res = await fetch(`/api/voice/saved/${safeGetProjectId()}/${recordId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ display_name: newName }),
        });
        const data = await res.json();
        if (!data.success) throw new Error(data.error);

        const voice = VoiceCloneState.savedVoices.find(v => v.id === recordId);
        if (voice) voice.display_name = newName;
        renderSavedVoicesList();
        showToast('✅ تم التحديث', 'success');
    } catch (err) {
        showToast('❌ فشل التحديث: ' + err.message, 'error');
    }
}


// ============================================================
// 🗑️ حذف صوت
// ============================================================
async function deleteSavedVoice(recordId, name) {
    if (!confirm(`حذف الصوت "${name}"؟`)) return;

    try {
        const res = await fetch(`/api/voice/saved/${safeGetProjectId()}/${recordId}`, {
            method: 'DELETE',
        });
        const data = await res.json();
        if (!data.success) throw new Error(data.error);

        VoiceCloneState.savedVoices = VoiceCloneState.savedVoices.filter(v => v.id !== recordId);
        if (VoiceCloneState.selectedVoiceId === data.voice_id) {
            VoiceCloneState.selectedVoiceId = null;
        }
        renderSavedVoicesList();
        showToast('✅ تم الحذف', 'success');
    } catch (err) {
        showToast('❌ فشل الحذف: ' + err.message, 'error');
    }
}


// ============================================================
// 📤 تصدير / 📥 استيراد
// ============================================================
async function exportVoices() {
    const pid = safeGetProjectId();
    if (!pid) {
        return showToast('⚠️ لا يوجد مشروع', 'warning');
    }

    try {
        const url = `/api/voice/export/${pid}`;
        const a = document.createElement('a');
        a.href = url;
        a.download = `voices_${pid.slice(0, 8)}_${Date.now()}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);

        showToast('📤 جاري تصدير الأصوات...', 'info');

    } catch (err) {
        showToast('❌ فشل التصدير: ' + err.message, 'error');
    }
}


function triggerImportVoices() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json,application/json';
    input.onchange = (e) => {
        const file = e.target.files?.[0];
        if (file) importVoicesFromFile(file);
    };
    input.click();
}


async function importVoicesFromFile(file) {
    const pid = safeGetProjectId();
    if (!pid) {
        return showToast('⚠️ لا يوجد مشروع', 'warning');
    }

    const merge = confirm(
        'اختر طريقة الاستيراد:\n\n' +
        '✅ موافق = دمج (إضافة الأصوات الجديدة فقط)\n' +
        '❌ إلغاء = استبدال (حذف كل الأصوات الحالية)'
    );

    try {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('merge', merge ? 'true' : 'false');

        const res = await fetch(`/api/voice/import/${pid}`, {
            method: 'POST',
            body: formData,
        });

        const data = await res.json();
        if (!data.success) throw new Error(data.error || 'فشل الاستيراد');

        await reloadSavedVoices();

        showToast(
            `✅ تم استيراد ${data.added} صوت (تخطي ${data.skipped})`,
            'success'
        );

    } catch (err) {
        showToast('❌ فشل الاستيراد: ' + err.message, 'error');
    }
}


async function reloadSavedVoices() {
    const pid = safeGetProjectId();
    if (!pid) return;

    try {
        const res = await fetch(`/api/voice/saved/${pid}`);
        const data = await res.json();
        if (data.success) {
            VoiceCloneState.savedVoices = data.voices || [];
            renderSavedVoicesList();
        }
    } catch (err) {
        console.warn('Failed to reload voices:', err);
    }
}


// ============================================================
// 💾 إحصائيات Cache
// ============================================================
async function showCacheStats() {
    try {
        const res = await fetch('/api/voice/cache/stats');
        const data = await res.json();
        if (!data.success) throw new Error('فشل جلب الإحصائيات');

        const msg = `💾 إحصائيات Cache:\n\n` +
                    `📁 عدد الملفات: ${data.files}\n` +
                    `💽 الحجم: ${data.total_size_mb} MB\n\n` +
                    `هل تريد مسح الـ cache؟`;

        if (confirm(msg)) {
            const clearRes = await fetch('/api/voice/cache/clear', {
                method: 'DELETE',
            });
            const clearData = await clearRes.json();
            if (clearData.success) {
                showToast(`✅ تم مسح ${clearData.deleted} ملف`, 'success');
            }
        }
    } catch (err) {
        showToast('❌ ' + err.message, 'error');
    }
}


// ============================================================
// 🎚️ معالجة الصوت
// ============================================================
async function processAudio() {
    if (!SyncProcessState.rawAudioBlob && !VoiceoverState.pendingBlob) {
        return showToast('⚠️ لا يوجد صوت', 'warning');
    }

    const btn = document.getElementById('btnProcessAudio');
    const progressEl = document.getElementById('syncProcessProgress');

    if (!btn || !progressEl) return;

    btn.disabled = true;
    progressEl.style.display = 'block';
    progressEl.innerHTML = `
        <div class="sync-progress-bar">
            <div class="sync-progress-fill" id="syncProgressFill" style="width:0%"></div>
        </div>
        <div class="sync-progress-text" id="syncProgressText">🔄 جاري الرفع...</div>
    `;

    try {
        const opts = {
            normalize: document.getElementById('optNormalize')?.checked ?? true,
            denoise: document.getElementById('optDenoise')?.checked ?? false,
            trim_silence: document.getElementById('optTrimSilence')?.checked ?? true,
            compress: document.getElementById('optCompress')?.checked ?? false,
            target_lufs: parseFloat(document.getElementById('optTargetLufs')?.value || -16),
        };

        SyncProcessState.processingOptions = opts;

        const formData = new FormData();
        const blob = SyncProcessState.rawAudioBlob || VoiceoverState.pendingBlob;
        formData.append('file', blob, 'audio.webm');
        formData.append('options', JSON.stringify(opts));

        updateSyncProgress(20, '🎚️ معالجة الصوت...');

        const res = await fetch('/api/media/process-audio', {
            method: 'POST',
            body: formData,
        });

        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        updateSyncProgress(80, '📥 استلام الصوت المعالج...');

        const processedBlob = await res.blob();
        const url = URL.createObjectURL(processedBlob);

        SyncProcessState.processedBlob = processedBlob;
        SyncProcessState.processedUrl = url;

        updateSyncProgress(100, '✅ اكتملت المعالجة');

        setTimeout(() => {
            progressEl.style.display = 'none';
        }, 800);

        showToast('✅ تمت معالجة الصوت بنجاح', 'success');

    } catch (err) {
        console.error(err);
        progressEl.innerHTML = `
            <div class="sync-progress-text" style="color:#ef4444;">
                ❌ فشل المعالجة: ${err.message}
            </div>
        `;
        showToast('❌ فشل المعالجة: ' + err.message, 'error');
    } finally {
        btn.disabled = false;
    }
}

function updateSyncProgress(percent, text) {
    const fill = document.getElementById('syncProgressFill');
    const txt = document.getElementById('syncProgressText');
    if (fill) fill.style.width = percent + '%';
    if (txt) txt.textContent = text;
}


// ============================================================
// 📝 تحديث المقاطع
// ============================================================
function updateSyncSegmentText(idx, text) {
    if (VoiceoverState.scriptSegments[idx]) {
        VoiceoverState.scriptSegments[idx].text = text.trim();
    }
}

function updateSyncSegmentTime(idx, field, value) {
    const v = parseFloat(value);
    if (isNaN(v) || v < 0) return;
    if (VoiceoverState.scriptSegments[idx]) {
        VoiceoverState.scriptSegments[idx][field] = v;
    }
}

function deleteSyncSegment(idx) {
    VoiceoverState.scriptSegments.splice(idx, 1);
    renderSegmentsForSync();
}

function autoSegmentFromScript() {
    const scriptEl = document.getElementById('voiceCloneScript') ||
                     document.getElementById('voiceoverScript');
    if (!scriptEl) return;
    const script = scriptEl.value.trim();
    if (!script) return showToast('⚠️ اكتب النص أولاً', 'warning');

    VoiceoverState.scriptSegments = autoSegmentScript(script);
    renderSegmentsForSync();
    showToast(`✅ تم تقسيم النص إلى ${VoiceoverState.scriptSegments.length} مقطع`, 'success');
}

function renderSegmentsForSync() {
    const el = document.getElementById('syncSegmentsList');
    if (!el) return;

    const segments = VoiceoverState.scriptSegments;

    if (!segments.length) {
        el.innerHTML = `
            <div class="sync-empty">
                <span style="font-size:24px;">📝</span>
                <p>لا توجد مقاطع نصية</p>
                <button onclick="autoSegmentFromScript()" class="btn-secondary btn-sm">
                    ✨ تقسيم النص تلقائياً
                </button>
            </div>
        `;
        return;
    }

    el.innerHTML = segments.map((seg, i) => `
        <div class="sync-segment" data-idx="${i}">
            <div class="sync-seg-num">${i + 1}</div>
            <input type="text" class="sync-seg-text-input"
                   value="${escapeHtml(seg.text)}"
                   onchange="updateSyncSegmentText(${i}, this.value)"
                   dir="auto">
            <div class="sync-seg-times">
                <input type="number" step="0.1" min="0"
                       value="${seg.start.toFixed(2)}"
                       onchange="updateSyncSegmentTime(${i}, 'start', this.value)"
                       class="sync-time-input">
                <span>→</span>
                <input type="number" step="0.1" min="0"
                       value="${seg.end.toFixed(2)}"
                       onchange="updateSyncSegmentTime(${i}, 'end', this.value)"
                       class="sync-time-input">
            </div>
            <button class="sync-seg-del" onclick="deleteSyncSegment(${i})">✕</button>
        </div>
    `).join('');

    const total = segments.reduce((sum, s) => sum + (s.end - s.start), 0);
    const totalEl = document.getElementById('syncSegmentsTotal');
    if (totalEl) {
        totalEl.textContent = `${segments.length} مقطع • ${total.toFixed(1)} ثانية`;
    }
}


// ============================================================
// 🎭 TALKING HEAD
// ============================================================
function openTalkingHeadModal() {
    const modal = document.getElementById('talkingHeadModal');
    if (!modal) {
        showToast('❌ نافذة Talking Head غير موجودة', 'error');
        return;
    }

    TalkingHeadState.imageBlob = null;
    TalkingHeadState.imageUrl = null;
    TalkingHeadState.currentTalkId = null;
    TalkingHeadState.resultUrl = null;
    TalkingHeadState.isGenerating = false;

    if (TalkingHeadState.pollingInterval) {
        clearInterval(TalkingHeadState.pollingInterval);
        TalkingHeadState.pollingInterval = null;
    }

    resetTalkingHeadUI();
    populateTalkingHeadVoices();

    const originalScript = document.getElementById('voiceoverScript');
    const talkingScript = document.getElementById('talkingHeadScript');
    if (talkingScript && originalScript && originalScript.value) {
        talkingScript.value = originalScript.value;
        updateTalkingHeadCharCount();
    }

    modal.classList.remove('hidden');
}


function closeTalkingHeadModal() {
    const modal = document.getElementById('talkingHeadModal');
    if (modal) modal.classList.add('hidden');

    if (TalkingHeadState.pollingInterval) {
        clearInterval(TalkingHeadState.pollingInterval);
        TalkingHeadState.pollingInterval = null;
    }
}


function resetTalkingHeadUI() {
    const preview = document.getElementById('talkingHeadImagePreview');
    if (preview) preview.innerHTML = '';

    const result = document.getElementById('talkingHeadResult');
    if (result) result.style.display = 'none';

    const status = document.getElementById('talkingHeadStatus');
    if (status) status.innerHTML = '';

    const progress = document.getElementById('talkingHeadProgress');
    if (progress) progress.style.display = 'none';

    const btn = document.getElementById('btnGenerateTalkingHead');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '🎭 إنشاء الفيديو';
    }
}


function pickTalkingHeadImage() {
    const input = document.getElementById('talkingHeadImageInput');
    if (input) input.click();
}


async function handleTalkingHeadImage(event) {
    const file = event.target.files?.[0];
    if (!file) return;

    if (!file.type.startsWith('image/')) {
        showToast('❌ الرجاء اختيار صورة صالحة', 'error');
        return;
    }

    if (file.size > 10 * 1024 * 1024) {
        showToast('❌ الصورة كبيرة جداً (الحد 10MB)', 'error');
        return;
    }

    TalkingHeadState.imageBlob = file;
    TalkingHeadState.imageUrl = URL.createObjectURL(file);

    renderTalkingHeadImagePreview(file, TalkingHeadState.imageUrl);
    updateTalkingHeadGenerateBtn();

    showToast('✅ تم تحميل الصورة', 'success');
}


function renderTalkingHeadImagePreview(file, url) {
    const el = document.getElementById('talkingHeadImagePreview');
    if (!el) return;

    el.innerHTML = `
        <div class="talking-head-image-container">
            <img src="${url}" alt="preview" class="talking-head-img">
            <div class="talking-head-image-info">
                <div class="talking-head-image-name">${escapeHtml(file.name)}</div>
                <div class="talking-head-image-meta">
                    ${(file.size / 1024).toFixed(1)} KB
                </div>
            </div>
            <button onclick="clearTalkingHeadImage()" class="talking-head-image-clear">✕</button>
        </div>
    `;
}


function clearTalkingHeadImage() {
    if (TalkingHeadState.imageUrl) {
        URL.revokeObjectURL(TalkingHeadState.imageUrl);
    }
    TalkingHeadState.imageBlob = null;
    TalkingHeadState.imageUrl = null;

    const el = document.getElementById('talkingHeadImagePreview');
    if (el) el.innerHTML = '';

    const input = document.getElementById('talkingHeadImageInput');
    if (input) input.value = '';

    updateTalkingHeadGenerateBtn();
}


function populateTalkingHeadVoices() {
    const select = document.getElementById('talkingHeadVoice');
    if (!select) return;

    select.innerHTML = '<option value="">— اختر صوتاً —</option>';

    const voices = VoiceCloneState.savedVoices || [];

    voices.forEach((voice) => {
        const opt = document.createElement('option');
        opt.value = voice.voice_id;
        opt.textContent = voice.display_name || voice.name || 'صوت';
        select.appendChild(opt);
    });

    if (!voices.length && VoiceCloneState.edgeVoices.length) {
        VoiceCloneState.edgeVoices.forEach((v) => {
            const opt = document.createElement('option');
            opt.value = v.id;
            opt.textContent = `${v.name} (${v.lang})`;
            select.appendChild(opt);
        });
    }

    if (select.options.length > 1) {
        select.selectedIndex = 1;
    }

    updateTalkingHeadGenerateBtn();
}


function updateTalkingHeadCharCount() {
    const ta = document.getElementById('talkingHeadScript');
    const counter = document.getElementById('talkingHeadCharCount');
    if (!ta || !counter) return;

    const len = ta.value.length;
    counter.textContent = `${len} / 1000 حرف`;

    counter.classList.remove('warning', 'danger');
    if (len > 900) {
        counter.classList.add('danger');
    } else if (len > 800) {
        counter.classList.add('warning');
    }

    updateTalkingHeadGenerateBtn();
}


function updateTalkingHeadGenerateBtn() {
    const btn = document.getElementById('btnGenerateTalkingHead');
    if (!btn) return;

    const hasImage = !!TalkingHeadState.imageBlob;
    const voiceSelect = document.getElementById('talkingHeadVoice');
    const hasVoice = voiceSelect && voiceSelect.value;
    const ta = document.getElementById('talkingHeadScript');
    const hasText = ta && ta.value.trim().length > 0;

    btn.disabled = !(hasImage && hasVoice && hasText);
}


async function generateTalkingHead() {
    if (!TalkingHeadState.imageBlob) {
        return showToast('⚠️ اختر صورة أولاً', 'warning');
    }

    const voiceSelect = document.getElementById('talkingHeadVoice');
    const voiceId = voiceSelect?.value;
    if (!voiceId) {
        return showToast('⚠️ اختر صوتاً أولاً', 'warning');
    }

    const scriptEl = document.getElementById('talkingHeadScript');
    const text = scriptEl?.value.trim();
    if (!text) {
        return showToast('⚠️ اكتب النص أولاً', 'warning');
    }

    const btn = document.getElementById('btnGenerateTalkingHead');
    const statusEl = document.getElementById('talkingHeadStatus');
    const progressEl = document.getElementById('talkingHeadProgress');

    btn.disabled = true;
    btn.innerHTML = '⏳ جاري الإنشاء...';
    TalkingHeadState.isGenerating = true;

    if (statusEl) {
        statusEl.innerHTML = `
            <div style="color:#fbbf24;">
                🎭 جاري إنشاء الفيديو...
                <br><small>يستغرق 30-90 ثانية</small>
            </div>
        `;
    }

    if (progressEl) {
        progressEl.style.display = 'block';
        progressEl.innerHTML = `
            <div class="sync-progress-bar">
                <div class="sync-progress-fill" id="thProgressFill" style="width:0%"></div>
            </div>
            <div class="sync-progress-text" id="thProgressText">🔄 جاري الرفع...</div>
        `;
    }

    try {
        const formData = new FormData();
        formData.append('image', TalkingHeadState.imageBlob, 'face.jpg');
        formData.append('text', text);
        formData.append('voice_id', voiceId);
        formData.append('language', 'ar');
        formData.append('project_id', safeGetProjectId());

        updateTHProgress(10, '🎭 جاري الرفع للخادم...');

        const res = await fetch('/api/talking-head/generate', {
            method: 'POST',
            body: formData,
        });

        const data = await res.json();

        if (!data.success) {
            throw new Error(data.error || 'فشل الإنشاء');
        }

        TalkingHeadState.currentTalkId = data.talk_id;

        updateTHProgress(20, '⏳ جاري معالجة الفيديو في D-ID...');

        startTalkingHeadPolling(data.talk_id);

    } catch (err) {
        console.error(err);
        if (statusEl) {
            statusEl.innerHTML = `
                <div style="color:#ef4444;">
                    ❌ فشل الإنشاء: ${err.message}
                </div>
            `;
        }
        if (progressEl) progressEl.style.display = 'none';
        showToast('❌ فشل الإنشاء: ' + err.message, 'error');
        btn.disabled = false;
        btn.innerHTML = '🎭 إنشاء الفيديو';
        TalkingHeadState.isGenerating = false;
    }
}


function startTalkingHeadPolling(talkId) {
    let attempts = 0;
    const maxAttempts = 60;

    TalkingHeadState.pollingInterval = setInterval(async () => {
        attempts++;

        if (attempts > maxAttempts) {
            clearInterval(TalkingHeadState.pollingInterval);
            TalkingHeadState.pollingInterval = null;
            handleTalkingHeadError('استغرق الفيديو وقتاً طويلاً — جرّب نصاً أقصر');
            return;
        }

        try {
            const res = await fetch(`/api/talking-head/status/${talkId}`);
            const data = await res.json();

            if (!data.success) {
                throw new Error(data.error || 'فشل جلب الحالة');
            }

            const status = data.status;

            if (status === 'done') {
                clearInterval(TalkingHeadState.pollingInterval);
                TalkingHeadState.pollingInterval = null;
                handleTalkingHeadSuccess(data.result_url);
            } else if (status === 'error') {
                clearInterval(TalkingHeadState.pollingInterval);
                TalkingHeadState.pollingInterval = null;
                handleTalkingHeadError(data.error || 'خطأ في D-ID');
            } else {
                const progress = 20 + Math.min(attempts * 3, 60);
                updateTHProgress(
                    progress,
                    `⏳ جاري المعالجة... (${status}) — ${attempts * 5}s`
                );
            }
        } catch (err) {
            console.warn('Polling error:', err);
        }
    }, 5000);
}


function updateTHProgress(percent, text) {
    const fill = document.getElementById('thProgressFill');
    const txt = document.getElementById('thProgressText');
    if (fill) fill.style.width = percent + '%';
    if (txt) txt.textContent = text;
}


function handleTalkingHeadSuccess(videoUrl) {
    const btn = document.getElementById('btnGenerateTalkingHead');
    const statusEl = document.getElementById('talkingHeadStatus');
    const progressEl = document.getElementById('talkingHeadProgress');
    const resultEl = document.getElementById('talkingHeadResult');

    if (btn) {
        btn.disabled = false;
        btn.innerHTML = '🎭 إنشاء فيديو جديد';
    }

    if (progressEl) progressEl.style.display = 'none';

    if (statusEl) {
        statusEl.innerHTML = `
            <div style="color:#34d399;">
                ✅ تم إنشاء الفيديو بنجاح!
            </div>
        `;
    }

    TalkingHeadState.resultUrl = videoUrl;
    TalkingHeadState.isGenerating = false;

    if (resultEl) {
        resultEl.style.display = 'block';
        resultEl.innerHTML = `
            <div class="talking-head-result-container">
                <video controls src="${videoUrl}"
                       class="talking-head-video"
                       poster=""></video>
                <div class="talking-head-result-actions">
                    <button onclick="saveTalkingHeadToProject()" 
                            class="btn-primary btn-sm" style="flex:1;">
                        💾 حفظ في المشروع
                    </button>
                    <button onclick="downloadTalkingHead()" 
                            class="btn-secondary btn-sm">
                        ⬇️ تحميل
                    </button>
                </div>
            </div>
        `;
    }

    showToast('🎭 تم إنشاء الفيديو بنجاح!', 'success');
}


function handleTalkingHeadError(message) {
    const btn = document.getElementById('btnGenerateTalkingHead');
    const statusEl = document.getElementById('talkingHeadStatus');
    const progressEl = document.getElementById('talkingHeadProgress');

    if (btn) {
        btn.disabled = false;
        btn.innerHTML = '🎭 إعادة المحاولة';
    }

    if (progressEl) progressEl.style.display = 'none';

    if (statusEl) {
        statusEl.innerHTML = `
            <div style="color:#ef4444;">
                ❌ ${message}
            </div>
        `;
    }

    TalkingHeadState.isGenerating = false;
    showToast('❌ ' + message, 'error');
}


async function saveTalkingHeadToProject() {
    if (!TalkingHeadState.resultUrl) {
        return showToast('⚠️ لا يوجد فيديو', 'warning');
    }

    const scriptEl = document.getElementById('talkingHeadScript');
    const text = scriptEl?.value.trim() || '';
    const voiceSelect = document.getElementById('talkingHeadVoice');
    const voiceId = voiceSelect?.value;

    try {
        const res = await fetch(`/api/talking-head/save/${safeGetProjectId()}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                video_url: TalkingHeadState.resultUrl,
                title: `Talking Head - ${new Date().toLocaleTimeString('ar')}`,
                text: text,
                voice_id: voiceId,
                start: safeGetCurrentTime(),
                duration: 5,
            }),
        });

        const data = await res.json();

        if (!data.success) throw new Error(data.error || 'فشل الحفظ');

        await addVoiceoverClip({
            type: 'video',
            title: data.clip.title,
            url: data.clip.url,
            script: text,
            script_segments: [],
            duration: data.clip.duration,
            start: data.clip.start,
            source: 'talking_head',
            voice_id: voiceId,
            color: '#7c3aed',
            icon: '🎭',
        });

        showToast('✅ تم حفظ الفيديو في المشروع', 'success');
        closeTalkingHeadModal();
        closeVoiceoverStudio();

    } catch (err) {
        showToast('❌ فشل الحفظ: ' + err.message, 'error');
    }
}


function downloadTalkingHead() {
    if (!TalkingHeadState.resultUrl) return;

    const a = document.createElement('a');
    a.href = TalkingHeadState.resultUrl;
    a.download = `talking_head_${Date.now()}.mp4`;
    a.target = '_blank';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}


// ============================================================
// Toast helper (fallback)
// ============================================================
if (typeof window.showToast !== 'function') {
    window.showToast = function (msg, type = 'info') {
        console.log(`[${type}] ${msg}`);
        const colors = {
            info: '#3b82f6',
            success: '#10b981',
            warning: '#f59e0b',
            error: '#ef4444',
        };
        const el = document.createElement('div');
        el.style.cssText = `
            position: fixed; top: 20px; right: 20px; z-index: 99999;
            background: ${colors[type] || colors.info}; color: #fff;
            padding: 10px 18px; border-radius: 8px; font-size: 14px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        `;
        el.textContent = msg;
        document.body.appendChild(el);
        setTimeout(() => el.remove(), 3500);
    };
}


// ============================================================
// تهيئة عند التحميل
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
    const ta = document.getElementById('voiceCloneScript');
    if (ta) {
        ta.addEventListener('input', updateCharCounter);
    }

    const thTa = document.getElementById('talkingHeadScript');
    if (thTa) {
        thTa.addEventListener('input', updateTalkingHeadCharCount);
    }

    const lufs = document.getElementById('optTargetLufs');
    if (lufs) {
        lufs.addEventListener('input', () => {
            document.getElementById('lufsVal').textContent = lufs.value;
        });
    }

    initSavedVoices();
    loadEdgeVoices();

    console.log('✅ voiceover.js loaded — بدون state، متوافق مع timeline-core.js');
});


// ============================================================
// تصدير الدوال للنطاق العام
// ============================================================
window.openVoiceoverStudio = openVoiceoverStudio;
window.closeVoiceoverStudio = closeVoiceoverStudio;
window.previewTTS = previewTTS;
window.toggleVoiceoverRec = toggleVoiceoverRec;
window.startVoiceoverRecording = startVoiceoverRecording;
window.stopVoiceoverRecording = stopVoiceoverRecording;
window.saveVoiceoverUnified = saveVoiceoverUnified;
window.saveTTSToTimeline = saveTTSToTimeline;
window.saveRecordingToTimeline = saveRecordingToTimeline;
window.saveAudioFileToTimeline = saveAudioFileToTimeline;
window.addVoiceoverClip = addVoiceoverClip;
window.updateSegmentText = updateSegmentText;
window.deleteSegment = deleteSegment;
window.renderSegments = renderSegments;
window.syncScriptWithPlayback = syncScriptWithPlayback;
window.showScriptOverlay = showScriptOverlay;
window.pickAudioFile = pickAudioFile;
window.handleAudioFileSelected = handleAudioFileSelected;
window.clearAudioFile = clearAudioFile;
window.extractTranscriptFromFile = extractTranscriptFromFile;
window.extractTranscriptServer = extractTranscriptServer;
window.extractTranscriptLocal = extractTranscriptLocal;
window.loadAudioFile = loadAudioFile;

window.showSyncButton = showSyncButton;
window.hideSyncButton = hideSyncButton;
window.openVoiceCloneModal = openVoiceCloneModal;
window.closeVoiceCloneModal = closeVoiceCloneModal;
window.selectSavedVoice = selectSavedVoice;
window.cloneVoiceAndSave = cloneVoiceAndSave;
window.generateWithCache = generateWithCache;
window.generateWithSavedVoice = generateWithCache;
window.previewSavedVoice = previewSavedVoice;
window.renameVoice = renameVoice;
window.deleteSavedVoice = deleteSavedVoice;
window.downloadGenerated = downloadGenerated;
window.saveGeneratedToProject = saveGeneratedToProject;
window.reloadSavedVoices = reloadSavedVoices;
window.updateCharCounter = updateCharCounter;

window.loadEdgeVoices = loadEdgeVoices;
window.selectEdgeVoice = selectEdgeVoice;

window.exportVoices = exportVoices;
window.triggerImportVoices = triggerImportVoices;
window.importVoicesFromFile = importVoicesFromFile;

window.showCacheStats = showCacheStats;

window.processAudio = processAudio;
window.renderSegmentsForSync = renderSegmentsForSync;
window.updateSyncSegmentText = updateSyncSegmentText;
window.updateSyncSegmentTime = updateSyncSegmentTime;
window.deleteSyncSegment = deleteSyncSegment;
window.autoSegmentFromScript = autoSegmentFromScript;

window.openTalkingHeadModal = openTalkingHeadModal;
window.closeTalkingHeadModal = closeTalkingHeadModal;
window.pickTalkingHeadImage = pickTalkingHeadImage;
window.handleTalkingHeadImage = handleTalkingHeadImage;
window.clearTalkingHeadImage = clearTalkingHeadImage;
window.generateTalkingHead = generateTalkingHead;
window.saveTalkingHeadToProject = saveTalkingHeadToProject;
window.downloadTalkingHead = downloadTalkingHead;
window.updateTalkingHeadCharCount = updateTalkingHeadCharCount;
window.populateTalkingHeadVoices = populateTalkingHeadVoices;
window.updateTalkingHeadGenerateBtn = updateTalkingHeadGenerateBtn;

window.escapeHtml = escapeHtml;
window.getCurrentPlayheadTime = getCurrentPlayheadTime;
window.safeGetProjectData = safeGetProjectData;
window.safeGetProjectId = safeGetProjectId;
window.safeGetCurrentTime = safeGetCurrentTime;
window.scrollToClipById = scrollToClipById;
