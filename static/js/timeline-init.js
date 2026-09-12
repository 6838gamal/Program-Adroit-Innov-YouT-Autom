// ============================================================
//  timeline-init.js — التهيئة + ربط الأحداث العامة
// ============================================================

// ============================================================
//  TOOLS
// ============================================================
function selectTool(tool) {
    document.querySelectorAll('.tool-btn').forEach(b => b.classList.remove('active'));
    const btn = document.getElementById('tool' + tool.charAt(0).toUpperCase() + tool.slice(1));
    if (btn) btn.classList.add('active');
}

// ============================================================
//  KEYBOARD SHORTCUTS
// ============================================================
function setupKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

        switch(e.key) {
            case ' ':
                e.preventDefault();
                togglePlay();
                break;
            case 'ArrowLeft':
                e.preventDefault();
                stepBackward();
                break;
            case 'ArrowRight':
                e.preventDefault();
                stepForward();
                break;
            case 'Delete':
            case 'Backspace':
                deleteSelected();
                break;
            case 's':
            case 'S':
                splitClip();
                break;
            case 'd':
            case 'D':
                duplicateClip();
                break;
            case 'f':
            case 'F':
                toggleFullscreen();
                break;
            case 'r':
            case 'R':
                toggleRecording();
                break;
        }
    });
}

// ============================================================
//  ZOOM SLIDER
// ============================================================
function setupZoomSlider() {
    document.getElementById('zoom-slider').addEventListener('input', function() {
        projectData.cellWidth = parseInt(this.value);
        document.getElementById('zoom-val').textContent = projectData.cellWidth;
        document.getElementById('statusZoom').textContent = projectData.cellWidth + '%';
        renderTimeline();
    });
}

// ============================================================
//  SEEK SLIDER
// ============================================================
function setupSeekSlider() {
    document.getElementById('seekSlider').addEventListener('input', function() {
        const time = (this.value / 100) * projectData.totalDuration;
        seekTo(time);
    });
}

// ============================================================
//  FULLSCREEN CHANGE
// ============================================================
function setupFullscreenListener() {
    document.addEventListener('fullscreenchange', () => {
        const area = document.getElementById('previewArea');
        if (!document.fullscreenElement) {
            area.classList.remove('fullscreen');
            setTimeout(resizeCanvas, 100);
        }
    });
}

// ============================================================
//  RESIZE CANVAS
// ============================================================
function resizeCanvas() {
    const container = document.getElementById('previewArea');
    if (!container || !canvas) return;
    const rect = container.getBoundingClientRect();
    const w = rect.width || 800;
    const h = Math.min(rect.height || 400, w * 9 / 16);
    canvas.width = w;
    canvas.height = h;
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';
    isCanvasReady = true;
    renderPreview(currentTime);
}

// ============================================================
//  CLEANUP
// ============================================================
function setupCleanup() {
    window.addEventListener('beforeunload', function() {
        if (isRecording && mediaRecorder) {
            try { mediaRecorder.stop(); } catch(e) {}
        }
        if (recordingTimerInterval) {
            clearInterval(recordingTimerInterval);
        }
        if (recordingStream) {
            try { recordingStream.getTracks().forEach(t => t.stop()); } catch(e) {}
        }
        if (playInterval) clearInterval(playInterval);
        if (renderPollInterval) clearInterval(renderPollInterval);

        if (audioContext) {
            try { audioContext.close(); } catch(e) {}
        }

        projectData.mediaFiles.forEach(f => {
            if (f.url && f.url.startsWith('blob:')) {
                try { URL.revokeObjectURL(f.url); } catch(e) {}
            }
        });

        Object.values(videoElements).forEach(v => {
            try {
                v.pause();
                v.src = '';
                v.load();
            } catch(e) {}
        });
    });
}

// ============================================================
//  INIT
// ============================================================
document.addEventListener('DOMContentLoaded', function() {
    canvas = document.getElementById('previewCanvas');
    ctx = canvas.getContext('2d');
    audioPlayer = document.getElementById('audioPlayer');

    resizeCanvas();
    window.addEventListener('resize', resizeCanvas);

    if (projectData.layers.length === 0) {
        projectData.layers.push({ name: 'طبقة 1', visible: true, locked: false });
    }

    setupDragDrop();
    setupKeyboardShortcuts();
    setupPlayheadDragging();
    setupTouchClipDragging();
    setupZoomSlider();
    setupSeekSlider();
    setupFullscreenListener();
    setupCleanup();

    loadProjectData();
});

console.log('🎬 محرر التايم لاين جاهز - مقسّم إلى ملفات منظمة ✅');
