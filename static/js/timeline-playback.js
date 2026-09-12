// ============================================================
//  timeline-playback.js — التشغيل + الصوت + التسجيل + عرض الفيديو
// ============================================================

// ============================================================
//  🎬 VIDEO PREVIEW STATE
// ============================================================
let _currentVideoPreviewId = null;

// ============================================================
//  PLAYBACK CONTROLS
// ============================================================
function togglePlay() {
    if (isRecording) {
        showToast('⚠️ لا يمكن التشغيل أثناء التسجيل', 'warning');
        return;
    }
    if (isPlaying) pausePlay();
    else startPlay();
}

function startPlay() {
    if (isRecording) {
        showToast('⚠️ لا يمكن التشغيل أثناء التسجيل', 'warning');
        return;
    }
    if (currentTime >= projectData.totalDuration) currentTime = 0;

    isPlaying = true;
    lastAudioSyncTime = -1;
    document.getElementById('playBtn').textContent = '⏸';
    document.getElementById('playhead').classList.add('active');

    if (audioContext && audioContext.state === 'suspended') {
        audioContext.resume();
    }

    if (audioPlayer && audioPlayer.src) {
        audioPlayer.play().catch(() => {});
    }

    // ✅ ابدأ تشغيل الفيديو النشط في المعاينة
    syncVideoPreview(currentTime);

    Object.values(videoElements).forEach(v => {
        if (!v.paused) return;
        v.play().catch(() => {});
    });

    const intervalMs = 40;
    playInterval = setInterval(() => {
        if (isRecording) return;
        currentTime += (intervalMs / 1000) * playbackSpeed;

        if (currentTime >= projectData.totalDuration) {
            if (isLooping) {
                currentTime = 0;
                lastAudioSyncTime = -1;
                if (audioPlayer && audioPlayer.src) {
                    audioPlayer.currentTime = 0;
                    audioPlayer.play().catch(() => {});
                }
                Object.values(videoElements).forEach(v => {
                    v.currentTime = 0;
                    v.play().catch(() => {});
                });
                // ✅ أعد ضبط فيديو المعاينة عند التكرار
                _currentVideoPreviewId = null;
                syncVideoPreview(currentTime);
            } else {
                pausePlay();
                return;
            }
        }
        updatePlayhead();
        syncVideoPreview(currentTime);   // ✅ جديد
        renderPreview(currentTime);
    }, intervalMs);
}

function pausePlay() {
    isPlaying = false;
    document.getElementById('playBtn').textContent = '▶';
    document.getElementById('playhead').classList.remove('active');

    if (audioPlayer) audioPlayer.pause();
    Object.values(videoElements).forEach(v => { try { v.pause(); } catch(e) {} });

    // ✅ أوقف فيديو المعاينة
    const previewVideo = document.getElementById('previewVideo');
    if (previewVideo) previewVideo.pause();

    audioNodes.forEach(node => {
        try { node.source.stop(); } catch(e) {}
        node.isPlaying = false;
    });
    audioNodes = [];
    lastAudioSyncTime = -1;

    if (playInterval) {
        clearInterval(playInterval);
        playInterval = null;
    }
}

function stepForward() { seekTo(Math.min(currentTime + 0.5, projectData.totalDuration)); }
function stepBackward() { seekTo(Math.max(currentTime - 0.5, 0)); }

function changeSpeed() {
    playbackSpeed = parseFloat(document.getElementById('speedSelect').value);
    if (audioPlayer) audioPlayer.playbackRate = playbackSpeed;
    Object.values(videoElements).forEach(v => { v.playbackRate = playbackSpeed; });

    // ✅ طبّق السرعة على فيديو المعاينة
    const previewVideo = document.getElementById('previewVideo');
    if (previewVideo) previewVideo.playbackRate = playbackSpeed;
}

function toggleLoop() {
    isLooping = !isLooping;
    document.getElementById('loopBtn').textContent = isLooping ? '🔂' : '🔁';
}

function toggleMute() {
    isMuted = !isMuted;
    document.getElementById('muteBtn').textContent = isMuted ? '🔇' : '🔊';
    if (audioPlayer) audioPlayer.muted = isMuted;
    Object.values(videoElements).forEach(v => { v.muted = isMuted; });
    audioNodes.forEach(node => {
        if (node.gain) node.gain.gain.value = isMuted ? 0 : 0.8;
    });

    // ✅ طبّق الكتم على فيديو المعاينة
    const previewVideo = document.getElementById('previewVideo');
    if (previewVideo) previewVideo.muted = isMuted;
}

function toggleFullscreen() {
    const area = document.getElementById('previewArea');
    if (!document.fullscreenElement) {
        area.classList.add('fullscreen');
        area.requestFullscreen().catch(() => {
            area.classList.remove('fullscreen');
        });
    } else {
        document.exitFullscreen();
        area.classList.remove('fullscreen');
    }
}

function seekTo(time) {
    if (isRecording) {
        showToast('⚠️ لا يمكن التمرير أثناء التسجيل', 'warning');
        return;
    }
    currentTime = Math.max(0, Math.min(time, projectData.totalDuration));
    lastAudioSyncTime = -1;

    if (isPlaying) {
        pausePlay();
        setTimeout(() => startPlay(), 50);
    } else {
        updatePlayhead();
        syncVideoPreview(currentTime);   // ✅ جديد
        renderPreview(currentTime);
    }

    if (audioPlayer && audioPlayer.src) {
        const activeAudio = projectData.clips.find(c => {
            const layer = projectData.layers[c.layer];
            return layer && layer.visible &&
                   c.type === 'audio' &&
                   currentTime >= c.start &&
                   currentTime < c.start + c.duration;
        });
        if (activeAudio) {
            audioPlayer.currentTime = currentTime - activeAudio.start;
        }
    }
}

// ============================================================
//  🎬 SYNC VIDEO PREVIEW — عرض الفيديو في المعاينة
// ============================================================
function syncVideoPreview(time) {
    const videoEl = document.getElementById('previewVideo');
    if (!videoEl) return;
    if (!projectData || !projectData.clips) return;

    // ابحث عن clip فيديو نشط
    const activeClip = projectData.clips.find(c => {
        if (c.type !== 'video') return false;
        const layer = projectData.layers[c.layer];
        if (layer && !layer.visible) return false;

        const start = c.start || 0;
        const end = start + (c.duration || 3);
        return time >= start && time < end;
    });

    // ── لا يوجد فيديو نشط ──
    if (!activeClip) {
        if (_currentVideoPreviewId !== null) {
            videoEl.style.display = 'none';
            videoEl.pause();
            videoEl.removeAttribute('src');
            videoEl.load();
            _currentVideoPreviewId = null;

            const canvas = document.getElementById('previewCanvas');
            if (canvas) canvas.style.opacity = '1';

            // أعد رسم Canvas
            if (typeof renderPreview === 'function') renderPreview(currentTime);
        }
        return;
    }

    // ── فيديو جديد ──
    if (_currentVideoPreviewId !== activeClip.id) {
        console.log('🎬 Video preview →', activeClip.title || activeClip.id);

        _currentVideoPreviewId = activeClip.id;
        videoEl.src = activeClip.content || activeClip.url;
        videoEl.style.display = 'block';
        videoEl.muted = isMuted;
        videoEl.playbackRate = playbackSpeed;
        videoEl.load();

        const canvas = document.getElementById('previewCanvas');
        if (canvas) canvas.style.opacity = '0';

        const localStart = time - (activeClip.start || 0);
        videoEl.onloadedmetadata = () => {
            try {
                videoEl.currentTime = Math.max(0, Math.min(localStart, videoEl.duration || 9999));
            } catch (e) {}
            if (isPlaying) videoEl.play().catch(() => {});
        };
        return;
    }

    // ── نفس الفيديو — زامن الوقت ──
    const localTime = time - (activeClip.start || 0);
    const videoDuration = videoEl.duration || activeClip.duration || 3;

    if (videoEl.readyState >= 1 && Math.abs(videoEl.currentTime - localTime) > 0.3) {
        try {
            videoEl.currentTime = Math.max(0, Math.min(localTime, videoDuration));
        } catch (e) {}
    }

    // زامن التشغيل
    if (isPlaying && videoEl.paused) {
        videoEl.play().catch(() => {});
    } else if (!isPlaying && !videoEl.paused) {
        videoEl.pause();
    }
}

// ============================================================
//  SYNC AUDIO
// ============================================================
function syncAudio(time) {
    if (Math.abs(time - lastAudioSyncTime) < 0.03) return;
    lastAudioSyncTime = time;

    const activeRecordings = [];

    projectData.clips.forEach(clip => {
        if (!clip.metadata || !clip.metadata.audioRecordings) return;

        clip.metadata.audioRecordings.forEach((rec, idx) => {
            const recStart = rec.start;
            const recEnd = rec.start + rec.duration;
            if (time >= recStart && time < recEnd) {
                activeRecordings.push({
                    id: `${clip.id}-${idx}`,
                    url: rec.url,
                    start: recStart,
                    duration: rec.duration
                });
            }
        });
    });

    const activeIds = new Set(activeRecordings.map(r => r.id));

    audioNodes.forEach(node => {
        if (!activeIds.has(node.clipId)) {
            try { node.source.stop(); } catch(e) {}
            node.isPlaying = false;
        }
    });
    audioNodes = audioNodes.filter(n => n.isPlaying);

    if (activeRecordings.length === 0) {
        if (audioPlayer && !audioPlayer.paused) audioPlayer.pause();
        return;
    }

    if (!audioContext) {
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (audioContext.state === 'suspended' && isPlaying) {
        audioContext.resume();
    }

    activeRecordings.forEach(rec => {
        const src = rec.url;
        if (!src || src.startsWith('blob:')) return;

        const existing = audioNodes.find(n => n.clipId === rec.id && n.isPlaying);
        const localTime = time - rec.start;

        if (existing) {
            const drift = Math.abs(
                existing.startTime + (audioContext.currentTime - existing.ctxStart) - localTime
            );
            if (drift > 0.15) {
                try { existing.source.stop(); } catch(e) {}
                existing.isPlaying = false;
                audioNodes = audioNodes.filter(n => n !== existing);
                if (audioBuffers[src]) playAudioBuffer(src, audioBuffers[src], rec, time);
            }
            return;
        }

        if (!audioBuffers[src]) {
            fetch(src)
                .then(res => res.arrayBuffer())
                .then(buf => audioContext.decodeAudioData(buf))
                .then(decoded => {
                    audioBuffers[src] = decoded;
                    if (isPlaying && currentTime >= rec.start && currentTime < rec.start + rec.duration) {
                        playAudioBuffer(src, decoded, rec, currentTime);
                    }
                })
                .catch(err => console.warn('فشل تحميل الصوت:', err));
            return;
        }

        playAudioBuffer(src, audioBuffers[src], rec, time);
    });
}

function playAudioBuffer(src, buffer, rec, time) {
    if (!buffer || !audioContext) return;
    const localTime = time - rec.start;
    if (localTime < 0 || localTime > rec.duration) return;

    try {
        const source = audioContext.createBufferSource();
        source.buffer = buffer;

        const gain = audioContext.createGain();
        gain.gain.value = isMuted ? 0 : 0.8;

        source.connect(gain);
        gain.connect(audioContext.destination);

        source.start(0, localTime);

        const node = {
            clipId: rec.id,
            source: source,
            gain: gain,
            startTime: localTime,
            ctxStart: audioContext.currentTime,
            isPlaying: true
        };
        audioNodes.push(node);

        source.onended = () => { node.isPlaying = false; };
    } catch(e) {}
}

// ============================================================
//  RECORDING
// ============================================================
async function toggleRecording() {
    const btn = document.getElementById('recordBtn');
    const indicator = document.getElementById('recordingIndicator');

    if (isRecording) {
        if (mediaRecorder && mediaRecorder.state !== 'inactive') {
            mediaRecorder.stop();
        }
        if (recordingTimerInterval) {
            clearInterval(recordingTimerInterval);
            recordingTimerInterval = null;
        }
        isRecording = false;
        btn.textContent = '🎙️';
        btn.classList.remove('recording');
        indicator.classList.remove('active');
        document.getElementById('playhead').classList.remove('recording');
        updatePlayheadLock();
        showToast('⏹️ تم إيقاف التسجيل', 'info');
        return;
    }

    const bounds = getRecordingBounds(currentTime);

    if (!bounds) {
        showToast('⚠️ لا يمكن التسجيل: لا توجد شريحة (صورة/فيديو/نص) عند المؤشر', 'warning');
        const playhead = document.getElementById('playhead');
        playhead.style.animation = 'shake 0.4s';
        setTimeout(() => playhead.style.animation = '', 400);
        return;
    }

    if (bounds.maxDuration < 0.5) {
        showToast('⚠️ المساحة المتاحة للتسجيل أقل من 0.5 ثانية', 'warning');
        return;
    }

    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        recordingStream = stream;

        mediaRecorder = new MediaRecorder(stream);
        recordedChunks = [];

        recordingStartTime = currentTime;
        recordingBoundClipId = bounds.clip.id;
        recordingMaxEnd = bounds.end;
        recordingInitialMaxEnd = bounds.end;
        recordingLastEndCheck = 0;

        if (isPlaying) pausePlay();

        recordingWallStart = performance.now();

        mediaRecorder.ondataavailable = (event) => {
            if (event.data.size > 0) recordedChunks.push(event.data);
        };

        mediaRecorder.onstop = async () => {
            const wallElapsed = (performance.now() - recordingWallStart) / 1000;
            const duration = Math.max(0.3, Math.min(wallElapsed, recordingMaxEnd - recordingStartTime));

            if (recordedChunks.length === 0) {
                stream.getTracks().forEach(t => t.stop());
                recordingStream = null;
                updatePlayheadLock();
                return;
            }

            const blob = new Blob(recordedChunks, { type: 'audio/webm' });
            const fileName = `تسجيل ${new Date().toLocaleTimeString()}.webm`;
            const fileObj = new File([blob], fileName, { type: 'audio/webm' });

            showToast('⏳ جاري رفع التسجيل...', 'info');
            const supabaseUrl = await uploadFileToSupabase(fileObj, projectId);

            if (!supabaseUrl) {
                showToast('❌ فشل رفع التسجيل', 'error');
                stream.getTracks().forEach(t => t.stop());
                recordingStream = null;
                updatePlayheadLock();
                return;
            }

            projectData.mediaFiles.push({
                name: fileName,
                size: blob.size,
                type: 'audio/webm',
                url: supabaseUrl,
            });

            const parentClip = projectData.clips.find(c => c.id === recordingBoundClipId);
            if (parentClip) {
                if (!parentClip.metadata) parentClip.metadata = {};
                if (!parentClip.metadata.audioRecordings) {
                    parentClip.metadata.audioRecordings = [];
                }
                parentClip.metadata.audioRecordings.push({
                    url: supabaseUrl,
                    start: recordingStartTime,
                    duration: duration,
                    file: fileName,
                    createdAt: new Date().toISOString()
                });
            }

            updateTotalDuration();
            renderTimeline();
            renderMediaGallery();
            updateStatus();
            saveProjectData();

            showToast(`✅ تم حفظ التسجيل (${duration.toFixed(1)}ث) مرتبطاً بالمقطع`, 'success');
            stream.getTracks().forEach(t => t.stop());
            recordingStream = null;

            currentTime = recordingStartTime + duration;
            updatePlayhead();
            syncVideoPreview(currentTime);   // ✅ جديد
            renderPreview(currentTime);
        };

        mediaRecorder.start(100);
        isRecording = true;
        btn.textContent = '⏹️';
        btn.classList.add('recording');
        indicator.classList.add('active');
        document.getElementById('recordingStartLabel').textContent = formatTime(recordingStartTime);
        document.getElementById('playhead').classList.add('recording');
        updatePlayheadLock();

        const chainCount = countChainedClips(bounds.start, bounds.end);
        showToast(`🔴 التسجيل من ${formatTime(recordingStartTime)} — متاح ${bounds.maxDuration.toFixed(1)}ث عبر ${chainCount} شريحة متصلة`, 'info');

        recordingTimerInterval = setInterval(() => {
            if (!isRecording) return;
            const elapsed = (performance.now() - recordingWallStart) / 1000;
            let newTime = recordingStartTime + elapsed;

            if (elapsed - recordingLastEndCheck > 0.5) {
                recordingLastEndCheck = elapsed;
                const newEnd = getContinuousEndFrom(newTime);
                if (newEnd > recordingMaxEnd + 0.05) {
                    const oldEnd = recordingMaxEnd;
                    recordingMaxEnd = newEnd;
                    console.log(`🔊 تمديد التسجيل: ${oldEnd.toFixed(1)} → ${newEnd.toFixed(1)}`);
                }
            }

            if (newTime >= recordingMaxEnd) {
                newTime = recordingMaxEnd;
                currentTime = newTime;
                updatePlayhead();

                if (mediaRecorder && mediaRecorder.state !== 'inactive') {
                    mediaRecorder.stop();
                }
                if (recordingTimerInterval) {
                    clearInterval(recordingTimerInterval);
                    recordingTimerInterval = null;
                }
                isRecording = false;
                btn.textContent = '🎙️';
                btn.classList.remove('recording');
                indicator.classList.remove('active');
                document.getElementById('playhead').classList.remove('recording');
                updatePlayheadLock();
                showToast('⏹️ توقف التسجيل عند نهاية الشرائح المتصلة', 'info');
                return;
            }

            currentTime = newTime;
            updatePlayhead();

            const scroll = document.getElementById('timelineContainer');
            const pxPerSec = projectData.cellWidth / 2;
            const playheadX = currentTime * pxPerSec + 60;
            if (playheadX > scroll.scrollLeft + scroll.clientWidth - 120) {
                scroll.scrollLeft = playheadX - scroll.clientWidth + 120;
            }

            document.getElementById('currentTimeDisplay').textContent = formatTime(currentTime);
            const slider = document.getElementById('seekSlider');
            if (projectData.totalDuration > 0) {
                slider.value = Math.min(100, (currentTime / projectData.totalDuration) * 100);
            }

            const totalAvailable = recordingMaxEnd - recordingStartTime;
            const recordProgress = Math.min(100, (elapsed / totalAvailable) * 100);
            indicator.querySelector('span:last-child').textContent =
                `🔴 التسجيل من ${formatTime(recordingStartTime)} (${recordProgress.toFixed(0)}%)`;
        }, 50);

    } catch (err) {
        console.error(err);
        showToast('⚠️ تعذر الوصول للميكروفون', 'error');
    }
}
