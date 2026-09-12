// ============================================================
//  timeline-timeline.js — التايم لاين + الكليبس + السحب
// ============================================================

// ============================================================
//  RENDER PREVIEW (Canvas)
// ============================================================
function renderPreview(time) {
    if (!isCanvasReady || !ctx) return;

    const w = canvas.width;
    const h = canvas.height;

    ctx.fillStyle = '#000000';
    ctx.fillRect(0, 0, w, h);

    const activeClips = projectData.clips.filter(c => {
        const layer = projectData.layers[c.layer];
        return layer && layer.visible &&
               time >= c.start &&
               time < c.start + c.duration;
    });

    activeClips.sort((a, b) => a.layer - b.layer);

    // ✅ شغّل/أوقف الصوت دائماً أثناء التشغيل
    if (isPlaying) syncAudio(time);

    if (activeClips.length > 0) {
        activeClips.forEach((clip) => {
            const x = w / 2;
            const y = h / 2;

            if (clip.type === 'image' && clip.content) {
                drawImageOnly(ctx, clip.content, x, y, w, h);
            } else if (clip.type === 'video' && clip.content) {
                drawVideoFrame(ctx, clip, x, y, w, h, time);
            } else if (clip.type === 'audio') {
                drawAudioIndicator(ctx, x, y);
            } else if (clip.type === 'text' && clip.content) {
                drawTextOnly(ctx, clip.content, x, y, w, h);
            }
        });

        currentClipAtTime = activeClips[0];
        document.getElementById('playbackInfo').style.display = 'block';
        document.getElementById('playbackTime').textContent = formatTime(time);
        document.getElementById('statusCurrentClip').textContent = '▶️';
    } else {
        ctx.fillStyle = 'rgba(255,255,255,0.03)';
        ctx.font = '48px sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText('🎬', w/2, h/2 - 10);
        ctx.font = '14px sans-serif';
        ctx.fillStyle = 'rgba(255,255,255,0.08)';
        ctx.fillText('أضف محتوى إلى التايم لاين', w/2, h/2 + 50);

        document.getElementById('playbackInfo').style.display = 'none';
        document.getElementById('statusCurrentClip').textContent = '⏸️';
        currentClipAtTime = null;
    }

    ctx.fillStyle = 'rgba(0,0,0,0.5)';
    ctx.fillRect(10, 10, 130, 24);
    ctx.fillStyle = 'rgba(255,255,255,0.3)';
    ctx.font = '11px monospace';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    ctx.fillText(`${formatTime(time)} / ${formatTime(projectData.totalDuration)}`, 16, 23);

    document.getElementById('currentTimeDisplay').textContent = formatTime(time);
    document.getElementById('totalTimeDisplay').textContent = formatTime(projectData.totalDuration);
    const slider = document.getElementById('seekSlider');
    if (projectData.totalDuration > 0) {
        slider.value = (time / projectData.totalDuration) * 100;
    }
}

// ====== دوال الرسم ======
function drawImageOnly(ctx, src, x, y, w, h) {
    if (!imageCache[src]) {
        const img = new Image();
        img.crossOrigin = 'anonymous';
        img.onload = function() {
            imageCache[src] = img;
            renderPreview(currentTime);
        };
        img.onerror = function() {
            imageCache[src] = 'error';
        };
        img.src = src;
        return;
    }

    const img = imageCache[src];
    if (img === 'error' || !img) {
        ctx.fillStyle = 'rgba(255,255,255,0.05)';
        ctx.font = '30px sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText('⚠️', x, y);
        return;
    }

    const ratio = Math.min(w / img.width, h / img.height);
    const drawW = img.width * ratio;
    const drawH = img.height * ratio;

    ctx.save();
    ctx.shadowColor = 'rgba(0,0,0,0.3)';
    ctx.shadowBlur = 10;
    ctx.drawImage(img, x - drawW/2, y - drawH/2, drawW, drawH);
    ctx.restore();
}

function drawVideoFrame(ctx, clip, x, y, w, h, time) {
    const src = clip.content;

    if (!videoElements[src]) {
        const video = document.createElement('video');
        video.src = src;
        video.muted = true;
        video.crossOrigin = 'anonymous';
        video.preload = 'auto';
        videoElements[src] = video;
        video.load();
    }

    const video = videoElements[src];
    const localTime = Math.max(0, time - clip.start);

    if (video.readyState >= 2) {
        try {
            const targetTime = Math.min(localTime, clip.duration);
            if (Math.abs(video.currentTime - targetTime) > 0.05) {
                video.currentTime = targetTime;
            }

            const ratio = Math.min(w / video.videoWidth, h / video.videoHeight);
            const drawW = video.videoWidth * ratio;
            const drawH = video.videoHeight * ratio;

            ctx.save();
            ctx.shadowColor = 'rgba(0,0,0,0.3)';
            ctx.shadowBlur = 10;
            ctx.drawImage(video, x - drawW/2, y - drawH/2, drawW, drawH);
            ctx.restore();

            if (isPlaying && video.paused) video.play().catch(() => {});
            else if (!isPlaying && !video.paused) video.pause();

            video.muted = isMuted;
            video.playbackRate = playbackSpeed;

            return;
        } catch(e) {}
    }

    ctx.fillStyle = 'rgba(0,0,0,0.7)';
    ctx.fillRect(x - w/4, y - h/4, w/2, h/2);
    ctx.fillStyle = 'rgba(255,255,255,0.1)';
    ctx.font = '40px sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('🎬', x, y - 5);
    ctx.font = '12px sans-serif';
    ctx.fillStyle = 'rgba(255,255,255,0.2)';
    ctx.fillText('جاري التحميل...', x, y + 30);
}

function drawAudioIndicator(ctx, x, y) {
    const size = 20;
    const time = Date.now() / 1000;
    const pulse = 0.5 + 0.5 * Math.sin(time * 4);

    ctx.fillStyle = `rgba(5,150,105,${0.05 + 0.1 * pulse})`;
    ctx.strokeStyle = `rgba(5,150,105,${0.1 + 0.1 * pulse})`;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(x, y, size + 4 * pulse, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();

    ctx.fillStyle = `rgba(5,150,105,${0.2 + 0.3 * pulse})`;
    ctx.font = '16px sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('♪', x, y + 1);
}

function drawTextOnly(ctx, text, x, y, w, h) {
    ctx.save();

    const fontSize = Math.min(42, w / 12);
    ctx.font = `bold ${fontSize}px sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';

    ctx.shadowColor = 'rgba(0,0,0,0.9)';
    ctx.shadowBlur = 20;
    ctx.fillStyle = 'rgba(255,255,255,0.95)';

    const words = text.split(' ');
    let lines = [];
    let currentLine = '';

    for (let word of words) {
        const testLine = currentLine + (currentLine ? ' ' : '') + word;
        const metrics = ctx.measureText(testLine);
        if (metrics.width > w - 60 && currentLine) {
            lines.push(currentLine);
            currentLine = word;
        } else {
            currentLine = testLine;
        }
    }
    if (currentLine) lines.push(currentLine);

    const lineHeight = fontSize * 1.3;
    const totalHeight = lines.length * lineHeight;
    const startY = y - totalHeight / 2 + lineHeight / 2;

    if (lines.length > 1) {
        ctx.shadowBlur = 0;
        ctx.fillStyle = 'rgba(0,0,0,0.3)';
        const textW = Math.min(w * 0.8, ctx.measureText(lines.join(' ')).width + 40);
        const textH = lines.length * lineHeight + 20;
        ctx.beginPath();
        ctx.roundRect(x - textW/2, y - totalHeight/2 - 10, textW, textH, 8);
        ctx.fill();
        ctx.shadowBlur = 20;
        ctx.shadowColor = 'rgba(0,0,0,0.9)';
    }

    lines.forEach((line, i) => {
        ctx.fillText(line, x, startY + i * lineHeight);
    });

    ctx.restore();
}

// ============================================================
//  RECORDING BOUNDS
// ============================================================
function getActiveClipAt(time) {
    const activeClips = projectData.clips.filter(c => {
        const layer = projectData.layers[c.layer];
        if (!layer || !layer.visible) return false;
        if (c.type === 'audio') return false;
        return time >= c.start && time < c.start + c.duration;
    });

    if (activeClips.length === 0) return null;
    activeClips.sort((a, b) => b.layer - a.layer);
    return activeClips[0];
}

function getContinuousEndFrom(time) {
    const TOLERANCE = 0.05;
    let cursor = time;
    let changed = true;
    let safetyCounter = 0;
    const maxIterations = 500;

    const relevantClips = projectData.clips.filter(c => {
        const layer = projectData.layers[c.layer];
        if (!layer || !layer.visible) return false;
        if (c.type === 'audio') return false;
        return true;
    });

    while (changed && safetyCounter < maxIterations) {
        changed = false;
        safetyCounter++;

        for (const clip of relevantClips) {
            const clipStart = clip.start;
            const clipEnd = clip.start + clip.duration;

            if (clipStart <= cursor + TOLERANCE && clipEnd > cursor + TOLERANCE) {
                cursor = clipEnd;
                changed = true;
            }
        }
    }

    return cursor;
}

function getRecordingBounds(startTime) {
    const activeClip = getActiveClipAt(startTime);
    if (!activeClip) return null;

    const continuousEnd = getContinuousEndFrom(startTime);

    return {
        start: startTime,
        end: continuousEnd,
        clip: activeClip,
        maxDuration: continuousEnd - startTime
    };
}

function countChainedClips(startTime, endTime) {
    return projectData.clips.filter(c => {
        const layer = projectData.layers[c.layer];
        if (!layer || !layer.visible) return false;
        if (c.type === 'audio') return false;
        const clipEnd = c.start + c.duration;
        const clipStart = c.start;
        return clipEnd > startTime - 0.05 && clipStart < endTime + 0.05;
    }).length;
}

function updateRecordZoneHighlight() {
    const highlight = document.getElementById('recordZoneHighlight');
    if (!highlight) return;

    const bounds = getRecordingBounds(currentTime);
    if (!bounds || bounds.maxDuration < 0.1) {
        highlight.classList.remove('active');
        return;
    }

    const pxPerSec = projectData.cellWidth / 2;
    const left = bounds.start * pxPerSec + 60;
    const width = bounds.maxDuration * pxPerSec;

    highlight.style.left = left + 'px';
    highlight.style.width = width + 'px';
    highlight.classList.add('active');
}

function updatePlayheadLock() {
    const playhead = document.getElementById('playhead');
    if (!playhead) return;

    if (isRecording) {
        playhead.classList.add('locked');
        playhead.classList.add('recording');
        return;
    }

    playhead.classList.remove('recording');

    const bounds = getRecordingBounds(currentTime);
    if (!bounds) {
        playhead.classList.add('locked');
    } else {
        playhead.classList.remove('locked');
    }

    const recordBtn = document.getElementById('recordBtn');
    if (recordBtn && !isRecording) {
        if (!bounds || bounds.maxDuration < 0.5) {
            recordBtn.disabled = true;
            recordBtn.title = 'لا توجد شريحة نشطة عند المؤشر';
        } else {
            recordBtn.disabled = false;
            const chainCount = countChainedClips(bounds.start, bounds.end);
            recordBtn.title = `تسجيل من ${formatTime(currentTime)} (متاح ${bounds.maxDuration.toFixed(1)}ث عبر ${chainCount} شريحة متصلة)`;
        }
    }
}

// ============================================================
//  INSERT POINT HELPERS
// ============================================================
function findNextInsertPoint(layerIndex, preferredStart = null) {
    const layerClips = projectData.clips
        .filter(c => c.layer === layerIndex)
        .sort((a, b) => a.start - b.start);

    if (layerClips.length === 0) {
        return preferredStart !== null ? Math.max(0, preferredStart) : 0;
    }

    let start = preferredStart !== null ? Math.max(0, preferredStart) : 0;

    for (const clip of layerClips) {
        const clipEnd = clip.start + clip.duration;

        if (start + 0.01 < clip.start) {
            return start;
        }

        if (start < clipEnd - 0.001) {
            start = clipEnd;
        }
    }

    return start;
}

function findExactEndOfLayer(layerIndex) {
    const layerClips = projectData.clips.filter(c => c.layer === layerIndex);
    if (layerClips.length === 0) return 0;
    return Math.max(...layerClips.map(c => c.start + c.duration));
}

function normalizeLayer(layerIndex) {
    const layerClips = projectData.clips
        .filter(c => c.layer === layerIndex)
        .sort((a, b) => a.start - b.start);

    if (layerClips.length === 0) return;

    let cursor = 0;
    layerClips.forEach(clip => {
        if (cursor === 0 && clip.start < 0.1) {
            clip.start = 0;
        } else {
            clip.start = cursor;
        }
        cursor = clip.start + clip.duration;
    });
}

// ============================================================
//  TIMELINE RENDERING
// ============================================================
function renderTimeline() {
    const container = document.getElementById('tracksContainer');
    const pxPerSec = projectData.cellWidth / 2;
    const totalWidth = projectData.totalDuration * pxPerSec + 120;

    const rulerMarks = document.getElementById('rulerMarks');
    rulerMarks.innerHTML = '';
    rulerMarks.style.display = 'flex';
    rulerMarks.style.direction = 'ltr';

    let step = 1;
    if (pxPerSec < 30) step = 5;
    else if (pxPerSec < 60) step = 2;
    else step = 1;

    for (let t = 0; t <= projectData.totalDuration; t += step) {
        const mark = document.createElement('div');
        const isMajor = t % (step * 5) === 0;
        mark.className = `ruler-mark${isMajor ? ' major' : ''}`;
        mark.style.width = (pxPerSec * step) + 'px';
        mark.style.flexShrink = '0';

        if (isMajor || step >= 2) {
            const m = Math.floor(t / 60);
            const s = Math.floor(t % 60);
            mark.innerHTML = `<span class="label">${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}</span>`;
        }
        rulerMarks.appendChild(mark);
    }

    container.innerHTML = '';
    projectData.layers.forEach((layer, layerIdx) => {
        if (!layer.visible) return;

        const row = document.createElement('div');
        row.className = 'track-row';
        row.dataset.layer = layerIdx;

        const label = document.createElement('div');
        label.className = 'track-label';
        label.innerHTML = `
            <span class="track-icon">📺</span>
            <span>${layer.name}</span>
        `;
        row.appendChild(label);

        const body = document.createElement('div');
        body.className = 'track-body';
        body.style.width = totalWidth + 'px';
        body.style.setProperty('--cell-w', projectData.cellWidth + 'px');
        body.dataset.layer = layerIdx;

        const layerClips = projectData.clips.filter(c => c.layer === layerIdx);
        layerClips.sort((a, b) => a.start - b.start);

        layerClips.forEach((clip) => {
            const left = clip.start * pxPerSec;
            const width = Math.max(clip.duration * pxPerSec - 2, 20);

            const block = document.createElement('div');
            block.className = `clip-block clip-type-${clip.type}${selectedClipId === clip.id ? ' selected' : ''}`;
            block.style.cssText = `left:${left}px;width:${width}px;`;
            block.dataset.clipId = clip.id;

            const durationStr = formatTime(clip.duration);

            let thumbContent = '';
            if (clip.type === 'image' && clip.content) {
                thumbContent = `<img src="${clip.content}" alt="${clip.title}" loading="lazy">`;
            } else if (clip.type === 'video' && clip.content) {
                thumbContent = `<video src="${clip.content}" muted preload="metadata"></video>`;
            } else {
                thumbContent = clip.icon || '📄';
            }

            block.innerHTML = `
                <div class="clip-thumb">${thumbContent}</div>
                <span class="clip-label">${clip.title || 'مقطع'}</span>
                <span class="clip-duration">${durationStr}</span>
                <button class="clip-delete-btn" onclick="event.stopPropagation();deleteClip(${clip.id})">✕</button>
            `;

            if (clip.metadata && clip.metadata.audioRecordings && clip.metadata.audioRecordings.length > 0) {
                const audioTrack = document.createElement('div');
                audioTrack.className = 'clip-audio-track';
                audioTrack.title = `${clip.metadata.audioRecordings.length} تسجيل صوتي مرتبط`;
                block.appendChild(audioTrack);
            }

            block.onclick = (e) => {
                e.stopPropagation();
                selectClip(clip.id);
                seekTo(clip.start);
            };

            block.ondblclick = () => editClipProperties(clip.id);

            const resizeHandle = document.createElement('div');
            resizeHandle.style.cssText = 'position:absolute;right:-8px;top:0;width:16px;height:100%;cursor:ew-resize;z-index:5;touch-action:none;';
            resizeHandle.onmousedown = (e) => {
                e.stopPropagation();
                startResizeClip(e, clip.id, 'right');
            };
            resizeHandle.ontouchstart = (e) => {
                e.stopPropagation();
                startResizeClip(e, clip.id, 'right');
            };
            block.appendChild(resizeHandle);

            const resizeHandleLeft = document.createElement('div');
            resizeHandleLeft.style.cssText = 'position:absolute;left:-8px;top:0;width:16px;height:100%;cursor:ew-resize;z-index:5;touch-action:none;';
            resizeHandleLeft.onmousedown = (e) => {
                e.stopPropagation();
                startResizeClip(e, clip.id, 'left');
            };
            resizeHandleLeft.ontouchstart = (e) => {
                e.stopPropagation();
                startResizeClip(e, clip.id, 'left');
            };
            block.appendChild(resizeHandleLeft);

            block.draggable = true;
            block.ondragstart = (e) => {
                e.dataTransfer.setData('text/plain', JSON.stringify({
                    type: 'clip',
                    clipId: clip.id,
                    layer: layerIdx,
                    start: clip.start
                }));
                block.classList.add('dragging');
                document.getElementById('trashZone').classList.add('active');
            };
            block.ondragend = () => {
                block.classList.remove('dragging');
                document.getElementById('trashZone').classList.remove('active');
            };

            body.appendChild(block);
        });

        body.ondragover = (e) => e.preventDefault();
        body.ondrop = (e) => {
            e.preventDefault();
            const data = JSON.parse(e.dataTransfer.getData('text/plain'));
            if (data.type === 'clip') {
                const rect = body.getBoundingClientRect();
                const x = e.clientX - rect.left + body.scrollLeft;
                const newStart = x / pxPerSec;
                moveClip(data.clipId, layerIdx, Math.max(0, newStart));
            }
        };

        row.appendChild(body);
        container.appendChild(row);
    });

    updatePlayhead();
    updateStatus();
}

// ============================================================
//  RESIZE CLIP
// ============================================================
let resizeClipData = null;

function startResizeClip(e, clipId, side) {
    const clip = projectData.clips.find(c => c.id === clipId);
    if (!clip) return;

    const clientX = e.clientX !== undefined ? e.clientX : (e.touches && e.touches[0] ? e.touches[0].clientX : 0);

    resizeClipData = {
        clipId: clipId,
        side: side,
        startX: clientX,
        originalStart: clip.start,
        originalDuration: clip.duration,
        pxPerSec: projectData.cellWidth / 2
    };

    document.addEventListener('mousemove', onResizeMove);
    document.addEventListener('touchmove', onResizeMove, { passive: false });
    document.addEventListener('mouseup', onResizeEnd);
    document.addEventListener('touchend', onResizeEnd);
    document.addEventListener('touchcancel', onResizeEnd);

    if (e.preventDefault) e.preventDefault();
    if (e.stopPropagation) e.stopPropagation();
}

function onResizeMove(e) {
    if (!resizeClipData) return;

    const clip = projectData.clips.find(c => c.id === resizeClipData.clipId);
    if (!clip) return;

    const clientX = e.clientX !== undefined ? e.clientX : (e.touches && e.touches[0] ? e.touches[0].clientX : 0);
    const dx = (clientX - resizeClipData.startX) / resizeClipData.pxPerSec;

    if (resizeClipData.side === 'right') {
        const newDuration = Math.max(0.3, resizeClipData.originalDuration + dx);
        clip.duration = newDuration;
    } else {
        const newStart = Math.max(0, resizeClipData.originalStart + dx);
        const newDuration = Math.max(0.3, resizeClipData.originalDuration - dx);
        clip.start = newStart;
        clip.duration = newDuration;
    }

    updateTotalDuration();
    renderTimeline();

    if (e.cancelable) e.preventDefault();
}

function onResizeEnd() {
    resizeClipData = null;
    document.removeEventListener('mousemove', onResizeMove);
    document.removeEventListener('touchmove', onResizeMove);
    document.removeEventListener('mouseup', onResizeEnd);
    document.removeEventListener('touchend', onResizeEnd);
    document.removeEventListener('touchcancel', onResizeEnd);
    saveProjectData();
}

// ============================================================
//  PLAYHEAD
// ============================================================
function updatePlayhead() {
    const playhead = document.getElementById('playhead');
    const pxPerSec = projectData.cellWidth / 2;
    const pos = currentTime * pxPerSec + 60;
    playhead.style.left = pos + 'px';

    updateRecordZoneHighlight();
    updatePlayheadLock();
}

function updateStatus() {
    document.getElementById('statusClips').textContent = projectData.clips.length;
    document.getElementById('statusDuration').textContent = formatTime(projectData.totalDuration);
    document.getElementById('statusLayers').textContent = projectData.layers.length;
}

// ============================================================
//  CLIP OPERATIONS
// ============================================================
function deleteClip(id) {
    const clip = projectData.clips.find(c => c.id === id);
    const recCount = (clip && clip.metadata && clip.metadata.audioRecordings)
        ? clip.metadata.audioRecordings.length
        : 0;
    const msg = recCount > 0
        ? `حذف المقطع و${recCount} تسجيل صوتي مرتبط؟`
        : 'حذف المقطع؟';
    if (!confirm(msg)) return;

    projectData.clips = projectData.clips.filter(c => c.id !== id);
    if (selectedClipId === id) selectedClipId = null;
    updateTotalDuration();
    renderTimeline();
    updateStatus();
    saveProjectData();
}

function selectClip(id) {
    selectedClipId = id;
    renderTimeline();
}

function addClip(type) {
    if (type === 'image' || type === 'video' || type === 'audio') {
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = type === 'image' ? 'image/*' :
                       type === 'video' ? 'video/*' : 'audio/*';
        input.multiple = true;
        input.onchange = (e) => {
            if (e.target.files.length > 0) handleFiles(e.target.files);
        };
        input.click();
        return;
    }

    if (type === 'text') {
        const text = prompt('نص المقطع:');
        if (!text) return;

        const startTime = findNextInsertPoint(selectedLayerIndex, currentTime);

        const clip = {
            id: clipIdCounter++,
            type: 'text',
            layer: selectedLayerIndex,
            start: startTime,
            duration: 2,
            title: text.slice(0, 18),
            content: text,
            color: COLORS.text,
            icon: '📝',
            metadata: {}
        };
        projectData.clips.push(clip);
        updateTotalDuration();
        renderTimeline();
        updateStatus();

        currentTime = clip.start + clip.duration;
        updatePlayhead();
        renderPreview(currentTime);

        const scroll = document.getElementById('timelineContainer');
        if (scroll) {
            const pxPerSec = projectData.cellWidth / 2;
            const playheadX = currentTime * pxPerSec + 60;
            if (playheadX > scroll.scrollLeft + scroll.clientWidth - 120) {
                scroll.scrollLeft = playheadX - scroll.clientWidth + 120;
            }
        }

        saveProjectData();
        showToast(`✅ تم إضافة النص — المؤشر عند ${formatTime(currentTime)}`, 'success');
    }
}

function splitClip() {
    if (selectedClipId === null) {
        showToast('⚠️ اختر مقطعاً', 'warning');
        return;
    }
    const clip = projectData.clips.find(c => c.id === selectedClipId);
    if (!clip) return;

    const splitTime = currentTime - clip.start;
    if (splitTime <= 0.1 || splitTime >= clip.duration - 0.1) {
        showToast('⚠️ اختر نقطة داخل المقطع', 'warning');
        return;
    }

    const newClip = {
        ...clip,
        id: clipIdCounter++,
        start: clip.start + splitTime,
        duration: clip.duration - splitTime,
        title: `${clip.title} (2)`,
        metadata: JSON.parse(JSON.stringify(clip.metadata || {}))
    };
    if (newClip.metadata.audioRecordings) {
        delete newClip.metadata.audioRecordings;
    }

    clip.duration = splitTime;
    clip.title = `${clip.title} (1)`;

    projectData.clips.push(newClip);
    updateTotalDuration();
    renderTimeline();
    saveProjectData();
}

function duplicateClip() {
    if (selectedClipId === null) {
        showToast('⚠️ اختر مقطعاً', 'warning');
        return;
    }
    const clip = projectData.clips.find(c => c.id === selectedClipId);
    if (!clip) return;

    let startTime = clip.start + clip.duration + 0.5;

    const newClip = {
        ...clip,
        id: clipIdCounter++,
        start: startTime,
        title: `${clip.title} (نسخة)`,
        metadata: JSON.parse(JSON.stringify(clip.metadata || {}))
    };
    projectData.clips.push(newClip);
    updateTotalDuration();
    renderTimeline();
    selectClip(newClip.id);
    saveProjectData();
}

function deleteSelected() {
    if (selectedClipId === null) {
        showToast('⚠️ اختر مقطعاً', 'warning');
        return;
    }
    deleteClip(selectedClipId);
}

function moveClip(id, newLayer, newStart) {
    const clip = projectData.clips.find(c => c.id === id);
    if (!clip) return;
    clip.layer = newLayer;
    clip.start = Math.max(0, newStart);
    updateTotalDuration();
    renderTimeline();
    saveProjectData();
}

// ============================================================
//  CLIP PROPERTIES
// ============================================================
function editClipProperties(id) {
    const clip = projectData.clips.find(c => c.id === id);
    if (!clip) return;

    document.getElementById('clipPropTitle').value = clip.title || '';
    document.getElementById('clipPropStart').value = clip.start;
    document.getElementById('clipPropDuration').value = clip.duration;
    document.getElementById('clipPropType').value = clip.type;

    const layerSelect = document.getElementById('clipPropLayer');
    layerSelect.innerHTML = '';
    projectData.layers.forEach((layer, i) => {
        const opt = document.createElement('option');
        opt.value = i;
        opt.textContent = layer.name;
        if (i === clip.layer) opt.selected = true;
        layerSelect.appendChild(opt);
    });

    document.getElementById('clipPropertiesModal').classList.remove('hidden');
    document.getElementById('clipPropertiesModal').dataset.clipId = id;
}

function closeClipProperties() {
    document.getElementById('clipPropertiesModal').classList.add('hidden');
}

function saveClipProperties() {
    const id = parseInt(document.getElementById('clipPropertiesModal').dataset.clipId);
    const clip = projectData.clips.find(c => c.id === id);
    if (!clip) return;

    clip.title = document.getElementById('clipPropTitle').value || 'مقطع';
    clip.start = parseFloat(document.getElementById('clipPropStart').value) || 0;
    clip.duration = Math.max(0.3, parseFloat(document.getElementById('clipPropDuration').value) || 1);
    clip.layer = parseInt(document.getElementById('clipPropLayer').value);
    clip.type = document.getElementById('clipPropType').value;
    clip.icon = TYPE_ICONS[clip.type] || '📄';
    clip.color = COLORS[clip.type] || '#666';

    updateTotalDuration();
    closeClipProperties();
    renderTimeline();
    saveProjectData();
    showToast('✅ تم التحديث', 'success');
}

// ============================================================
//  PLAYHEAD DRAGGING
// ============================================================
function setupPlayheadDragging() {
    const playhead = document.getElementById('playhead');
    const timelineScroll = document.getElementById('timelineContainer');
    let isDragging = false;
    let dragPointerId = null;
    let dragTouchId = null;

    function getTimeFromClientX(clientX) {
        const inner = document.getElementById('timeline-inner');
        const rect = inner.getBoundingClientRect();
        const pxPerSec = projectData.cellWidth / 2;
        const x = clientX - rect.left - 60;
        return Math.max(0, Math.min(x / pxPerSec, projectData.totalDuration));
    }

    if (window.PointerEvent) {
        playhead.addEventListener('pointerdown', (e) => {
            if (isRecording) {
                showToast('⚠️ لا يمكن تحريك المؤشر أثناء التسجيل', 'warning');
                return;
            }
            isDragging = true;
            dragPointerId = e.pointerId;
            playhead.classList.add('dragging');
            try { playhead.setPointerCapture(e.pointerId); } catch(err) {}
            e.preventDefault();
            e.stopPropagation();
        });

        playhead.addEventListener('pointermove', (e) => {
            if (!isDragging || e.pointerId !== dragPointerId) return;
            const time = getTimeFromClientX(e.clientX);
            currentTime = time;
            updatePlayhead();
            renderPreview(currentTime);
            autoScrollDuringDrag(e.clientX, timelineScroll);
            e.preventDefault();
        });

        function endPointerDrag(e) {
            if (!isDragging || (e && e.pointerId !== dragPointerId)) return;
            isDragging = false;
            dragPointerId = null;
            playhead.classList.remove('dragging');
            try { playhead.releasePointerCapture(e.pointerId); } catch(err) {}
        }

        playhead.addEventListener('pointerup', endPointerDrag);
        playhead.addEventListener('pointercancel', endPointerDrag);
        playhead.addEventListener('lostpointercapture', endPointerDrag);
    }

    playhead.addEventListener('touchstart', (e) => {
        if (window.PointerEvent) return;
        if (isRecording) {
            showToast('⚠️ لا يمكن تحريك المؤشر أثناء التسجيل', 'warning');
            return;
        }
        const touch = e.touches[0];
        if (!touch) return;
        isDragging = true;
        dragTouchId = touch.identifier;
        playhead.classList.add('dragging');
        e.preventDefault();
        e.stopPropagation();
    }, { passive: false });

    playhead.addEventListener('touchmove', (e) => {
        if (window.PointerEvent) return;
        if (!isDragging) return;
        const touch = Array.from(e.touches).find(t => t.identifier === dragTouchId);
        if (!touch) return;
        const time = getTimeFromClientX(touch.clientX);
        currentTime = time;
        updatePlayhead();
        renderPreview(currentTime);
        autoScrollDuringDrag(touch.clientX, timelineScroll);
        e.preventDefault();
    }, { passive: false });

    playhead.addEventListener('touchend', () => {
        if (window.PointerEvent) return;
        isDragging = false;
        dragTouchId = null;
        playhead.classList.remove('dragging');
    });

    playhead.addEventListener('touchcancel', () => {
        if (window.PointerEvent) return;
        isDragging = false;
        dragTouchId = null;
        playhead.classList.remove('dragging');
    });

    playhead.addEventListener('mousedown', (e) => {
        if (window.PointerEvent) return;
        if (isRecording) {
            showToast('⚠️ لا يمكن تحريك المؤشر أثناء التسجيل', 'warning');
            return;
        }
        isDragging = true;
        playhead.classList.add('dragging');
        e.preventDefault();
        e.stopPropagation();
    });

    document.addEventListener('mousemove', (e) => {
        if (window.PointerEvent) return;
        if (!isDragging) return;
        const time = getTimeFromClientX(e.clientX);
        currentTime = time;
        updatePlayhead();
        renderPreview(currentTime);
        autoScrollDuringDrag(e.clientX, timelineScroll);
    });

    document.addEventListener('mouseup', () => {
        if (window.PointerEvent) return;
        if (isDragging) {
            isDragging = false;
            playhead.classList.remove('dragging');
        }
    });

    // الرولر
    const rulerMarks = document.getElementById('rulerMarks');
    if (rulerMarks) {
        rulerMarks.style.cursor = 'ew-resize';
        let rulerDragging = false;
        let rulerPointerId = null;

        if (window.PointerEvent) {
            rulerMarks.addEventListener('pointerdown', (e) => {
                if (isRecording) return;
                rulerDragging = true;
                rulerPointerId = e.pointerId;
                try { rulerMarks.setPointerCapture(e.pointerId); } catch(err) {}
                const time = getTimeFromClientX(e.clientX);
                seekTo(time);
                e.preventDefault();
            });

            rulerMarks.addEventListener('pointermove', (e) => {
                if (!rulerDragging || e.pointerId !== rulerPointerId) return;
                const time = getTimeFromClientX(e.clientX);
                currentTime = time;
                updatePlayhead();
                renderPreview(currentTime);
                e.preventDefault();
            });

            rulerMarks.addEventListener('pointerup', (e) => {
                rulerDragging = false;
                rulerPointerId = null;
                try { rulerMarks.releasePointerCapture(e.pointerId); } catch(err) {}
            });

            rulerMarks.addEventListener('pointercancel', () => { rulerDragging = false; });
        } else {
            rulerMarks.addEventListener('touchstart', (e) => {
                if (isRecording) return;
                const touch = e.touches[0];
                if (!touch) return;
                rulerDragging = true;
                const time = getTimeFromClientX(touch.clientX);
                seekTo(time);
                e.preventDefault();
            }, { passive: false });

            rulerMarks.addEventListener('touchmove', (e) => {
                if (!rulerDragging) return;
                const touch = e.touches[0];
                if (!touch) return;
                const time = getTimeFromClientX(touch.clientX);
                currentTime = time;
                updatePlayhead();
                renderPreview(currentTime);
                e.preventDefault();
            }, { passive: false });

            rulerMarks.addEventListener('touchend', () => { rulerDragging = false; });
            rulerMarks.addEventListener('touchcancel', () => { rulerDragging = false; });

            rulerMarks.addEventListener('mousedown', (e) => {
                if (isRecording) return;
                const time = getTimeFromClientX(e.clientX);
                seekTo(time);
            });
        }
    }

    // الخلفية
    document.addEventListener('pointerdown', (e) => {
        if (isRecording) return;
        if (e.target.classList.contains('track-body')) {
            const time = getTimeFromClientX(e.clientX);
            seekTo(time);
        }
    });

    document.addEventListener('touchstart', (e) => {
        if (window.PointerEvent) return;
        if (isRecording) return;
        if (e.target.classList.contains('track-body')) {
            const touch = e.touches[0];
            if (!touch) return;
            const time = getTimeFromClientX(touch.clientX);
            seekTo(time);
        }
    }, { passive: true });
}

function autoScrollDuringDrag(clientX, timelineScroll) {
    if (!timelineScroll) return;
    const scrollRect = timelineScroll.getBoundingClientRect();
    const margin = 40;
    if (clientX < scrollRect.left + margin) {
        timelineScroll.scrollLeft -= 8;
    } else if (clientX > scrollRect.right - margin) {
        timelineScroll.scrollLeft += 8;
    }
}

// ============================================================
//  TOUCH DRAG FOR CLIPS
// ============================================================
function setupTouchClipDragging() {
    let touchDragData = null;

    document.addEventListener('touchstart', (e) => {
        if (isRecording) return;
        const block = e.target.closest('.clip-block');
        if (!block) return;
        if (e.target.style.cursor === 'ew-resize') return;

        const clipId = parseInt(block.dataset.clipId);
        const clip = projectData.clips.find(c => c.id === clipId);
        if (!clip) return;

        const touch = e.touches[0];
        if (!touch) return;

        touchDragData = {
            clipId: clipId,
            startX: touch.clientX,
            startY: touch.clientY,
            originalLayer: clip.layer,
            originalStart: clip.start,
            blockEl: block,
            moved: false,
            clip: clip
        };

        setTimeout(() => {
            if (touchDragData && touchDragData.moved) {
                block.classList.add('dragging');
            }
        }, 150);

    }, { passive: true });

    document.addEventListener('touchmove', (e) => {
        if (!touchDragData) return;
        const touch = e.touches[0];
        if (!touch) return;

        const dx = touch.clientX - touchDragData.startX;
        const dy = touch.clientY - touchDragData.startY;

        if (!touchDragData.moved && Math.hypot(dx, dy) > 10) {
            touchDragData.moved = true;
            touchDragData.blockEl.classList.add('dragging');
            document.getElementById('trashZone').classList.add('active');
        }

        if (!touchDragData.moved) return;

        const pxPerSec = projectData.cellWidth / 2;
        const newStart = Math.max(0, touchDragData.originalStart + dx / pxPerSec);

        const elementUnder = document.elementFromPoint(touch.clientX, touch.clientY);
        const trackBody = elementUnder ? elementUnder.closest('.track-body') : null;
        let newLayer = touchDragData.originalLayer;
        if (trackBody) {
            newLayer = parseInt(trackBody.dataset.layer);
        }

        touchDragData.clip.start = newStart;
        touchDragData.clip.layer = newLayer;

        renderTimeline();
        e.preventDefault();
    }, { passive: false });

    document.addEventListener('touchend', () => {
        if (!touchDragData) return;

        const { blockEl, moved, clipId } = touchDragData;

        blockEl.classList.remove('dragging');
        document.getElementById('trashZone').classList.remove('active');

        if (!moved) {
            selectClip(clipId);
            const clip = projectData.clips.find(c => c.id === clipId);
            if (clip) seekTo(clip.start);
        } else {
            updateTotalDuration();
            renderTimeline();
            saveProjectData();
        }

        touchDragData = null;
    });

    document.addEventListener('touchcancel', () => {
        if (touchDragData) {
            touchDragData.blockEl.classList.remove('dragging');
            document.getElementById('trashZone').classList.remove('active');
            touchDragData = null;
        }
    });
}
