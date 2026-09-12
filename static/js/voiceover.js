/**
 * voiceover.js — نظام تسجيل/توليد/اختيار الصوت مع النص المخصص
 * يعتمد على: timeline-core.js (state, API)
 *
 * يدعم 3 أوضاع:
 *   1) TTS — صوت جاهز من Web Speech API
 *   2) Record — تسجيل مباشر من الميكروفون مع STT
 *   3) File — اختيار ملف صوتي موجود + استخراج النص (Whisper)
 *
 * + نظام المزامنة والمعالجة والاستعراض الكامل
 */

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
    scriptSegments: [],      // [{ text, start, end, speaker }]
    ttsVoices: [],
    selectedVoice: null,
    isRecordingScript: false,
    startTime: 0,
    recTimer: null,
    // ملفات
    pendingBlob: null,
    pendingUrl: null,
    pendingFileName: null,
    pendingDuration: 0,
    source: null,
};


// ============================================================
// أصوات TTS المتاحة (Web Speech API)
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

    // إعادة تعيين الحقول
    document.getElementById('voiceoverScript').value = '';
    document.getElementById('voiceoverTranscript').innerHTML = '';
    document.getElementById('voiceoverSegments').innerHTML =
        '<div style="color:#64748b;font-size:12px;text-align:center;padding:8px;">لا توجد مقاطع بعد</div>';
    document.getElementById('voiceoverPreview').innerHTML = '';
    document.getElementById('voiceoverFileInfo').style.display = 'none';
    document.getElementById('voiceoverFileInfo').innerHTML = '';
    VoiceoverState.scriptSegments = [];

    // ✅ أخفِ زر المزامنة عند الفتح
    hideSyncButton();

    // أعد تعيين الوضع إلى tts
    const ttsRadio = document.querySelector('input[name="voiceoverMode"][value="tts"]');
    if (ttsRadio) {
        ttsRadio.checked = true;
        ttsRadio.dispatchEvent(new Event('change'));
    }

    // تعبئة قائمة الأصوات
    populateVoiceSelect();

    // إذا كان هناك مقطع موجود، حمّل نصه
    if (clipId && typeof state !== 'undefined' && state.clips) {
        const clip = state.clips.find(c => c.id === clipId);
        if (clip) {
            document.getElementById('voiceoverScript').value = clip.script || '';
            document.getElementById('voiceoverTitle').value = clip.title || '';
            if (clip.scriptSegments) {
                VoiceoverState.scriptSegments = clip.scriptSegments;
                renderSegments();
            }
            // ✅ إذا كان هناك صوت محفوظ، أظهر زر المزامنة
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
// ✅ إظهار/إخفاء زر المزامنة
// ============================================================
function showSyncButton() {
    const el = document.getElementById('openSyncBtnContainer');
    if (el) el.style.display = 'block';
}

function hideSyncButton() {
    const el = document.getElementById('openSyncBtnContainer');
    if (el) el.style.display = 'none';
}


// ============================================================
// تعبئة قائمة أصوات TTS
// ============================================================
function populateVoiceSelect() {
    const select = document.getElementById('voiceoverVoiceSelect');
    if (!select) return;
    select.innerHTML = '<option value="">— اختر صوتاً —</option>';

    const voices = loadTTSVoices();
    // ترتيب: العربي أولاً
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
// 🎙️ وضع التسجيل المباشر
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

        // بدء التعرف على الكلام
        startSpeechRecognition();

        VoiceoverState.startTime = performance.now();
        VoiceoverState.mediaRecorder.start(100);

        // تحديث الواجهة
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
// التعرف على الكلام (Speech Recognition)
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

        // عرض النص المباشر
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

    // ✅ أظهر زر المزامنة
    showSyncButton();

    showToast('✅ تم التسجيل، يمكنك المزامنة والمعالجة الآن', 'success');
}


// ============================================================
// عرض مقاطع النص المُزامن
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
// 🎵 خيار اختيار ملف صوتي موجود
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

    // اقرأ المدة
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

    // ✅ أظهر زر المزامنة
    showSyncButton();

    showToast('✅ تم تحميل الملف. يمكنك المزامنة والمعالجة الآن', 'success');
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

    // ✅ أخفِ زر المزامنة
    hideSyncButton();
}


// ============================================================
// 🎬 استخراج النص من ملف صوتي
// ============================================================

async function extractTranscriptFromFile() {
    if (!VoiceoverState.pendingBlob) {
        return showToast('⚠️ اختر ملفاً صوتياً أولاً', 'warning');
    }

    const useServer = confirm(
        'اختر طريقة الاستخراج:\n\n' +
        '✅ موافق = استخراج عبر الخادم (Whisper - أدق، يحتاج اتصال)\n' +
        '❌ إلغاء = استخراج محلي (Speech Recognition - أسرع، دقة أقل)'
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
        showToast('❌ فشل الاستخراج عبر الخادم: ' + err.message, 'error');
        console.error(err);
    }
}

async function extractTranscriptLocal() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) return showToast('❌ المتصفح لا يدعم التعرف على الكلام', 'error');

    showToast('🎧 سيتم تشغيل الملف واستخراج النص... ارفع الصوت', 'info');

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
// 💾 حفظ موحّد حسب الوضع
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
// 💾 حفظ TTS في الخط الزمني
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
        start: getCurrentPlayheadTime(),
        source: 'tts',
        url: null,
    };

    await addVoiceoverClip(clipData);
    showToast('✅ تم إضافة المقطع الصوتي (TTS)', 'success');
    closeVoiceoverStudio();
}


// ============================================================
// 💾 حفظ التسجيل في الخط الزمني
// ============================================================
async function saveRecordingToTimeline() {
    if (!VoiceoverState.pendingBlob) {
        return showToast('⚠️ لم يتم تسجيل صوت بعد', 'warning');
    }

    const title = document.getElementById('voiceoverTitle').value.trim() || 'تسجيل صوتي';
    const script = document.getElementById('voiceoverScript').value.trim();

    const formData = new FormData();
    formData.append('file', VoiceoverState.pendingBlob,
        `voiceover_${Date.now()}.webm`);
    formData.append('project_id', state.projectId);
    formData.append('title', title);
    formData.append('script', script);
    formData.append('script_segments', JSON.stringify(VoiceoverState.scriptSegments));
    formData.append('source', 'recording');
    formData.append('start', String(getCurrentPlayheadTime()));

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
            start: getCurrentPlayheadTime(),
            source: 'recording',
        });

        showToast('✅ تم حفظ التسجيل في المشروع', 'success');
        closeVoiceoverStudio();
    } catch (err) {
        showToast('❌ فشل رفع التسجيل: ' + err.message, 'error');
    }
}


// ============================================================
// 💾 حفظ الملف الصوتي المُختار
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
    formData.append('project_id', state.projectId);
    formData.append('title', title);
    formData.append('script', script);
    formData.append('script_segments', JSON.stringify(VoiceoverState.scriptSegments));
    formData.append('source', 'file');
    formData.append('start', String(getCurrentPlayheadTime()));

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
            start: getCurrentPlayheadTime(),
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
// إضافة مقطع صوتي للخط الزمني
// ============================================================
async function addVoiceoverClip(clipData) {
    if (!state.clips) state.clips = [];
    if (!state.layers) state.layers = [{ id: 'layer-1', name: 'الطبقة 1', visible: true }];

    const clip = {
        id: 'clip-' + Date.now() + '-' + Math.random().toString(36).slice(2, 7),
        layerId: state.layers[state.layers.length - 1].id,
        start: clipData.start || 0,
        duration: clipData.duration || 3,
        ...clipData,
        script: clipData.script || '',
        scriptSegments: clipData.script_segments || clipData.scriptSegments || [],
        tts: clipData.tts || null,
        source: clipData.source || 'tts',
        fileName: clipData.fileName || null,
    };

    state.clips.push(clip);

    // أعد الرسم
    if (typeof renderTimeline === 'function') renderTimeline();
    if (typeof renderLayers === 'function') renderLayers();
    if (typeof updateStatusBar === 'function') updateStatusBar();
    if (typeof drawPreview === 'function') drawPreview();

    // حفظ في السحابة
    if (typeof saveProject === 'function') {
        try { await saveProject(); } catch (e) { console.warn(e); }
    }
    return clip;
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
    if (typeof state !== 'undefined' && state.currentTime != null) return state.currentTime;
    return 0;
}

function round2(n) {
    return Math.round(n * 100) / 100;
}


// ============================================================
// تشغيل النص أثناء العرض
// ============================================================
function syncScriptWithPlayback(currentTime) {
    if (!state.clips) return;
    const audioClips = state.clips.filter(c =>
        c.type === 'audio' && c.scriptSegments?.length
    );

    for (const clip of audioClips) {
        const localT = currentTime - clip.start;
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

    document.getElementById('scriptOverlayTitle').textContent = title || '';
    document.getElementById('scriptOverlayText').textContent = text || '';
    el.classList.add('visible');

    clearTimeout(el._hideTimer);
    el._hideTimer = setTimeout(() => el.classList.remove('visible'), 2500);
}


// ============================================================
// 🎯 نظام المزامنة والمعالجة والاستعراض
// ============================================================
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
};


// ============================================================
// 1️⃣ فتح/إغلاق نافذة المزامنة
// ============================================================
function openSyncProcessModal() {
    if (!VoiceoverState.pendingBlob && !SyncProcessState.rawAudioBlob) {
        return showToast('⚠️ سجّل صوتاً أو اختر ملفاً أولاً', 'warning');
    }

    SyncProcessState.rawAudioBlob = VoiceoverState.pendingBlob;
    SyncProcessState.rawAudioUrl = VoiceoverState.pendingUrl;

    const modal = document.getElementById('syncProcessModal');
    if (!modal) return;

    resetSyncProcessUI();
    renderRawAudioPreview();
    renderSegmentsForSync();

    modal.classList.remove('hidden');
}

function closeSyncProcessModal() {
    const modal = document.getElementById('syncProcessModal');
    if (modal) modal.classList.add('hidden');

    const player = document.getElementById('syncProcessPlayer');
    if (player) {
        player.pause();
        player.currentTime = 0;
    }
}

function resetSyncProcessUI() {
    SyncProcessState.processedBlob = null;
    SyncProcessState.processedUrl = null;
    SyncProcessState.isAligned = false;
    SyncProcessState.isProcessing = false;

    const section = document.getElementById('syncProcessedSection');
    if (section) section.style.display = 'none';

    const comparison = document.getElementById('syncComparisonSection');
    if (comparison) comparison.style.display = 'none';

    const progress = document.getElementById('syncProcessProgress');
    if (progress) progress.style.display = 'none';

    const alignStatus = document.getElementById('syncAlignStatus');
    if (alignStatus) alignStatus.innerHTML = '';

    const btnProcess = document.getElementById('btnProcessAudio');
    if (btnProcess) btnProcess.disabled = false;

    const btnAlign = document.getElementById('btnAlignScript');
    if (btnAlign) btnAlign.disabled = false;
}


// ============================================================
// 2️⃣ عرض الصوت الأصلي
// ============================================================
function renderRawAudioPreview() {
    const el = document.getElementById('syncRawAudio');
    if (!el) return;

    el.innerHTML = `
        <audio controls src="${SyncProcessState.rawAudioUrl}"
               style="width:100%;height:36px;" id="syncRawPlayer"></audio>
        <div class="sync-audio-meta">
            <span>📼 الأصلي</span>
            <span id="syncRawDuration">—</span>
            <span id="syncRawSize">—</span>
        </div>
    `;

    const audio = document.getElementById('syncRawPlayer');
    const size = SyncProcessState.rawAudioBlob?.size || 0;

    audio.addEventListener('loadedmetadata', () => {
        document.getElementById('syncRawDuration').textContent =
            `⏱️ ${formatTime(audio.duration || 0)}`;
    });

    document.getElementById('syncRawSize').textContent =
        `💾 ${(size / 1024).toFixed(1)} KB`;
}


// ============================================================
// 3️⃣ عرض المقاطع للمزامنة
// ============================================================
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
    document.getElementById('syncSegmentsTotal').textContent =
        `${segments.length} مقطع • ${total.toFixed(1)} ثانية`;
}

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
    const script = document.getElementById('voiceoverScript').value.trim();
    if (!script) return showToast('⚠️ اكتب النص أولاً', 'warning');

    VoiceoverState.scriptSegments = autoSegmentScript(script);
    renderSegmentsForSync();
    showToast(`✅ تم تقسيم النص إلى ${VoiceoverState.scriptSegments.length} مقطع`, 'success');
}


// ============================================================
// 4️⃣ المزامنة التلقائية
// ============================================================
async function alignScriptWithAudio() {
    if (!SyncProcessState.rawAudioBlob) {
        return showToast('⚠️ لا يوجد صوت', 'warning');
    }

    const script = document.getElementById('voiceoverScript').value.trim();
    if (!script) {
        return showToast('⚠️ اكتب النص أولاً', 'warning');
    }

    const btn = document.getElementById('btnAlignScript');
    const statusEl = document.getElementById('syncAlignStatus');

    btn.disabled = true;
    btn.innerHTML = '⏳ جاري المزامنة...';
    statusEl.innerHTML = '<span style="color:#fbbf24;">🔄 رفع الصوت للمعالجة...</span>';

    try {
        const formData = new FormData();
        formData.append('file', SyncProcessState.rawAudioBlob, 'audio.webm');
        formData.append('script', script);
        formData.append('language', 'ar');

        const res = await fetch('/api/media/align-script', {
            method: 'POST',
            body: formData,
        });

        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        if (!data.success) throw new Error(data.error || 'فشل المزامنة');

        if (data.segments && data.segments.length) {
            VoiceoverState.scriptSegments = data.segments.map((s) => ({
                text: s.text || '',
                start: parseFloat(s.start || 0),
                end: parseFloat(s.end || 0),
                speaker: 'المتحدث',
                confidence: s.confidence || null,
            }));

            SyncProcessState.alignedSegments = [...VoiceoverState.scriptSegments];
            SyncProcessState.isAligned = true;

            renderSegmentsForSync();

            statusEl.innerHTML = `
                <span style="color:#34d399;">
                    ✅ تمت المزامنة الدقيقة (${data.segments.length} مقطع)
                    ${data.method ? `— ${data.method}` : ''}
                </span>
            `;
            showToast('🎯 تمت مزامنة النص مع الصوت بنجاح', 'success');
        } else {
            throw new Error('لم تُرجع الخدمة أي مقاطع');
        }

    } catch (err) {
        console.error(err);
        statusEl.innerHTML = `<span style="color:#ef4444;">❌ فشل المزامنة: ${err.message}</span>`;
        showToast('❌ فشل المزامنة: ' + err.message, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '🎯 مزامنة تلقائية';
    }
}


// ============================================================
// 5️⃣ المزامنة اليدوية
// ============================================================
async function alignScriptManually() {
    if (!SyncProcessState.rawAudioBlob) {
        return showToast('⚠️ لا يوجد صوت', 'warning');
    }

    const segments = VoiceoverState.scriptSegments;
    if (!segments.length) {
        return showToast('⚠️ أضف مقاطع نصية أولاً', 'warning');
    }

    const audio = new Audio(SyncProcessState.rawAudioUrl);
    await new Promise(r => {
        audio.addEventListener('loadedmetadata', r, { once: true });
        audio.addEventListener('error', r, { once: true });
        setTimeout(r, 2000);
    });

    const audioDuration = audio.duration || 0;
    if (audioDuration <= 0) {
        return showToast('❌ لا يمكن قراءة مدة الصوت', 'error');
    }

    const totalChars = segments.reduce((sum, s) => sum + s.text.length, 0);
    let cursor = 0;

    segments.forEach((seg) => {
        const ratio = totalChars > 0 ? seg.text.length / totalChars : 1 / segments.length;
        const dur = audioDuration * ratio;
        seg.start = round2(cursor);
        seg.end = round2(Math.min(cursor + dur, audioDuration));
        cursor = seg.end;
    });

    if (segments.length > 0) {
        segments[segments.length - 1].end = round2(audioDuration);
    }

    SyncProcessState.isAligned = true;
    renderSegmentsForSync();
    document.getElementById('syncAlignStatus').innerHTML =
        '<span style="color:#34d399;">✅ تمت المزامنة اليدوية (متناسبة مع المدة)</span>';

    showToast('✅ تمت المزامنة اليدوية', 'success');
}


// ============================================================
// 6️⃣ معالجة الصوت
// ============================================================
async function processAudio() {
    if (!SyncProcessState.rawAudioBlob) {
        return showToast('⚠️ لا يوجد صوت', 'warning');
    }

    const btn = document.getElementById('btnProcessAudio');
    const progressEl = document.getElementById('syncProcessProgress');

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
        formData.append('file', SyncProcessState.rawAudioBlob, 'audio.webm');
        formData.append('options', JSON.stringify(opts));

        updateSyncProgress(20, '🎚️ معالجة الصوت...');

        const res = await fetch('/api/media/process-audio', {
            method: 'POST',
            body: formData,
        });

        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        updateSyncProgress(80, '📥 استلام الصوت المعالج...');

        const blob = await res.blob();
        const url = URL.createObjectURL(blob);

        SyncProcessState.processedBlob = blob;
        SyncProcessState.processedUrl = url;

        updateSyncProgress(100, '✅ اكتملت المعالجة');

        setTimeout(() => {
            progressEl.style.display = 'none';
        }, 800);

        renderProcessedAudio();
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
// 7️⃣ استعراض الصوت المعالج
// ============================================================
function renderProcessedAudio() {
    const section = document.getElementById('syncProcessedSection');
    if (!section) return;

    section.style.display = 'block';

    const audioEl = document.getElementById('syncProcessedAudio');
    audioEl.innerHTML = `
        <audio controls src="${SyncProcessState.processedUrl}"
               style="width:100%;height:36px;" id="syncProcessedPlayer"></audio>
        <div class="sync-audio-meta">
            <span>✨ المعالج</span>
            <span id="syncProcessedDuration">—</span>
            <span id="syncProcessedSize">—</span>
            <span class="sync-badge-green">✅ محسّن</span>
        </div>
    `;

    const player = document.getElementById('syncProcessedPlayer');
    const rawSize = SyncProcessState.rawAudioBlob?.size || 0;
    const procSize = SyncProcessState.processedBlob?.size || 0;

    player.addEventListener('loadedmetadata', () => {
        document.getElementById('syncProcessedDuration').textContent =
            `⏱️ ${formatTime(player.duration || 0)}`;
    });

    document.getElementById('syncProcessedSize').textContent =
        `💾 ${(procSize / 1024).toFixed(1)} KB`;

    player.addEventListener('timeupdate', () => {
        const t = player.currentTime;
        highlightSegmentAtTime(t, 'processed');
    });

    renderComparison(rawSize, procSize);
    renderAlignedSegmentsPreview();
}

function renderComparison(rawSize, procSize) {
    const section = document.getElementById('syncComparisonSection');
    if (!section) return;

    section.style.display = 'block';

    const diff = rawSize > 0 ? ((procSize - rawSize) / rawSize * 100) : 0;
    const diffText = diff > 0
        ? `+${diff.toFixed(1)}%`
        : `${diff.toFixed(1)}%`;

    section.innerHTML = `
        <div class="sync-comparison-grid">
            <div class="sync-comparison-item">
                <div class="sync-comparison-label">📼 الأصلي</div>
                <div class="sync-comparison-value">${(rawSize / 1024).toFixed(1)} KB</div>
            </div>
            <div class="sync-comparison-arrow">→</div>
            <div class="sync-comparison-item highlight">
                <div class="sync-comparison-label">✨ المعالج</div>
                <div class="sync-comparison-value">${(procSize / 1024).toFixed(1)} KB</div>
                <div class="sync-comparison-diff ${diff > 0 ? 'up' : 'down'}">${diffText}</div>
            </div>
        </div>
    `;
}


// ============================================================
// 8️⃣ عرض النص المُزامن مع الإبراز
// ============================================================
function renderAlignedSegmentsPreview() {
    const el = document.getElementById('syncAlignedPreview');
    if (!el) return;

    const segments = VoiceoverState.scriptSegments;
    if (!segments.length) {
        el.innerHTML = '<div class="sync-empty-small">لا توجد مقاطع</div>';
        return;
    }

    el.innerHTML = segments.map((seg, i) => `
        <div class="sync-aligned-seg" data-idx="${i}"
             onclick="seekToSegment(${i}, 'processed')"
             title="انقر للانتقال إلى ${formatTime(seg.start)}">
            <span class="sync-aligned-time">${formatTime(seg.start)}</span>
            <span class="sync-aligned-text">${escapeHtml(seg.text)}</span>
        </div>
    `).join('');
}

function highlightSegmentAtTime(time, playerType = 'processed') {
    const segments = VoiceoverState.scriptSegments;
    const el = document.getElementById('syncAlignedPreview');
    if (!el) return;

    const activeIdx = segments.findIndex(s => time >= s.start && time <= s.end);

    el.querySelectorAll('.sync-aligned-seg').forEach((node, i) => {
        node.classList.toggle('active', i === activeIdx);
    });

    if (activeIdx >= 0) {
        const activeNode = el.querySelector(`.sync-aligned-seg[data-idx="${activeIdx}"]`);
        if (activeNode) {
            activeNode.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
    }

    showSyncOverlayText(activeIdx >= 0 ? segments[activeIdx].text : '');
}

function showSyncOverlayText(text) {
    const el = document.getElementById('syncOverlayText');
    if (el) el.textContent = text || '';
}

function seekToSegment(idx, playerType = 'processed') {
    const seg = VoiceoverState.scriptSegments[idx];
    if (!seg) return;

    const playerId = playerType === 'processed' ? 'syncProcessedPlayer' : 'syncRawPlayer';
    const player = document.getElementById(playerId);
    if (player) {
        player.currentTime = seg.start;
        player.play();
    }
}


// ============================================================
// 9️⃣ حفظ الصوت المعالج
// ============================================================
async function saveProcessedVoiceover() {
    if (!SyncProcessState.processedBlob) {
        return showToast('⚠️ لا يوجد صوت معالج', 'warning');
    }

    const title = document.getElementById('voiceoverTitle').value.trim() || 'تعليق صوتي';
    const script = document.getElementById('voiceoverScript').value.trim();

    const formData = new FormData();
    formData.append('file', SyncProcessState.processedBlob, 'processed.webm');
    formData.append('project_id', state.projectId);
    formData.append('title', title);
    formData.append('script', script);
    formData.append('script_segments', JSON.stringify(VoiceoverState.scriptSegments));
    formData.append('source', VoiceoverState.source || 'recording');
    formData.append('start', String(getCurrentPlayheadTime()));
    formData.append('processed', 'true');
    formData.append('processing_options', JSON.stringify(SyncProcessState.processingOptions));

    try {
        const res = await fetch('/api/media/upload-voiceover', {
            method: 'POST',
            body: formData,
        });
        const data = await res.json();
        if (!data.success) throw new Error(data.error || 'فشل الحفظ');

        await addVoiceoverClip({
            type: 'audio',
            title: title,
            url: data.url,
            path: data.path,
            mediaId: data.media_id,
            script: script,
            script_segments: VoiceoverState.scriptSegments,
            duration: data.duration || 0,
            start: getCurrentPlayheadTime(),
            source: VoiceoverState.source || 'recording',
            processed: true,
            processingOptions: SyncProcessState.processingOptions,
        });

        showToast('✅ تم حفظ الصوت المعالج في المشروع', 'success');
        closeSyncProcessModal();
        closeVoiceoverStudio();
    } catch (err) {
        showToast('❌ فشل الحفظ: ' + err.message, 'error');
    }
}


// ============================================================
// 🔟 أدوات مساعدة
// ============================================================
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
// Toast helper (fallback إذا لم يكن موجوداً)
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
            animation: slideIn 0.3s ease-out;
        `;
        el.textContent = msg;
        document.body.appendChild(el);
        setTimeout(() => el.remove(), 3500);
    };
}


// ============================================================
// تصدير الدوال للنطاق العام
// ============================================================

// الاستوديو الأساسي
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

// زر المزامنة
window.showSyncButton = showSyncButton;
window.hideSyncButton = hideSyncButton;

// المزامنة والمعالجة
window.openSyncProcessModal = openSyncProcessModal;
window.closeSyncProcessModal = closeSyncProcessModal;
window.alignScriptWithAudio = alignScriptWithAudio;
window.alignScriptManually = alignScriptManually;
window.processAudio = processAudio;
window.saveProcessedVoiceover = saveProcessedVoiceover;
window.renderSegmentsForSync = renderSegmentsForSync;
window.updateSyncSegmentText = updateSyncSegmentText;
window.updateSyncSegmentTime = updateSyncSegmentTime;
window.deleteSyncSegment = deleteSyncSegment;
window.autoSegmentFromScript = autoSegmentFromScript;
window.seekToSegment = seekToSegment;
window.escapeHtml = escapeHtml;
