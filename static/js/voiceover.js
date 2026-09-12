/**
 * voiceover.js — نظام تسجيل/توليد/اختيار الصوت مع النص المخصص
 * يعتمد على: timeline-core.js (state, API)
 *
 * يدعم 3 أوضاع:
 *   1) TTS — صوت جاهز من Web Speech API
 *   2) Record — تسجيل مباشر من الميكروفون مع STT
 *   3) File — اختيار ملف صوتي موجود + استخراج النص (Whisper)
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
        // نستخدم الاسم كلغة قيمة للبحث لاحقاً
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

    showToast('✅ تم التسجيل، اضغط "حفظ" لإضافته للخط الزمني', 'success');
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

    showToast('✅ تم تحميل الملف. يمكنك استخراج النص أو كتابته يدوياً', 'success');
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
