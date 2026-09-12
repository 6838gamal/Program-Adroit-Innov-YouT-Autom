/**
 * timeline-video.js — عرض الفيديو في المعاينة
 * يعمل تلقائياً مع التشغيل والتحريك
 */

// ============================================================
// حالة عرض الفيديو
// ============================================================
const VideoPreviewState = {
    currentVideoId: null,
    currentVideoUrl: null,
    videoElement: null,
    isReady: false,
    lastUpdateTime: 0,
};


// ============================================================
// تهيئة عنصر الفيديو
// ============================================================
function initVideoPreview() {
    const videoEl = document.getElementById('previewVideo');
    if (!videoEl) {
        console.warn('⚠️ previewVideo element not found');
        return;
    }

    VideoPreviewState.videoElement = videoEl;

    videoEl.addEventListener('loadeddata', () => {
        VideoPreviewState.isReady = true;
        console.log('✅ Video loaded:', VideoPreviewState.currentVideoUrl?.substring(0, 80));
    });

    videoEl.addEventListener('error', (e) => {
        console.error('❌ Video error:', e);
    });

    videoEl.addEventListener('ended', () => {
        if (VideoPreviewState.videoElement) {
            VideoPreviewState.videoElement.currentTime = 0;
        }
    });

    // ✅ مراقبة تلقائية لتغير currentTime (بدلاً من تعديل playback)
    setInterval(monitorAndUpdateVideo, 100);

    console.log('✅ Video preview initialized');
}


// ============================================================
// مراقبة تلقائية — بسيطة وفعالة
// ============================================================
function monitorAndUpdateVideo() {
    if (typeof state === 'undefined') return;
    if (state.currentTime == null) return;

    // إذا تغير الوقت
    if (Math.abs(state.currentTime - VideoPreviewState.lastUpdateTime) > 0.05) {
        VideoPreviewState.lastUpdateTime = state.currentTime;
        updateVideoPreview(state.currentTime);
    }

    // تحقق من حالة التشغيل
    const videoEl = VideoPreviewState.videoElement;
    if (!videoEl) return;

    const isPlaying = state.isPlaying || false;

    if (isPlaying && videoEl.style.display !== 'none' && videoEl.src && videoEl.paused) {
        videoEl.play().catch(() => {});
    } else if (!isPlaying && !videoEl.paused) {
        videoEl.pause();
    }
}


// ============================================================
// تحديث الفيديو حسب موضع Playhead
// ============================================================
function updateVideoPreview(currentTime) {
    const videoEl = VideoPreviewState.videoElement;
    if (!videoEl) return;
    if (typeof state === 'undefined' || !state.clips) return;

    // ابحث عن clip فيديو نشط
    const activeVideoClip = state.clips.find(c => {
        if (c.type !== 'video') return false;
        const start = c.start || 0;
        const end = start + (c.duration || 3);
        return currentTime >= start && currentTime < end;
    });

    // ── لا يوجد فيديو نشط ──
    if (!activeVideoClip) {
        if (VideoPreviewState.currentVideoId !== null) {
            videoEl.style.display = 'none';
            videoEl.pause();
            videoEl.removeAttribute('src');
            videoEl.load();
            VideoPreviewState.currentVideoId = null;
            VideoPreviewState.currentVideoUrl = null;
            VideoPreviewState.isReady = false;

            // أعد إظهار الـ canvas
            const canvas = document.getElementById('previewCanvas');
            if (canvas) canvas.style.opacity = '1';
        }
        return;
    }

    // ── فيديو جديد ──
    if (VideoPreviewState.currentVideoId !== activeVideoClip.id) {
        console.log('🎬 Switching to video:', activeVideoClip.title || activeVideoClip.id);

        VideoPreviewState.currentVideoId = activeVideoClip.id;
        VideoPreviewState.currentVideoUrl = activeVideoClip.url;
        VideoPreviewState.isReady = false;

        videoEl.src = activeVideoClip.url;
        videoEl.load();
        videoEl.style.display = 'block';

        // أخفِ الـ canvas
        const canvas = document.getElementById('previewCanvas');
        if (canvas) canvas.style.opacity = '0';
    }

    // ── مزامنة الوقت ──
    if (VideoPreviewState.isReady && activeVideoClip) {
        const localTime = currentTime - (activeVideoClip.start || 0);
        const videoDuration = videoEl.duration || activeVideoClip.duration || 3;

        if (Math.abs(videoEl.currentTime - localTime) > 0.3) {
            videoEl.currentTime = Math.max(0, Math.min(localTime, videoDuration));
        }
    }
}


// ============================================================
// عند تغيير موضع Playhead
// ============================================================
function onPlayheadSeek(newTime) {
    VideoPreviewState.lastUpdateTime = -999; // للتحديث الفوري
    updateVideoPreview(newTime);
}


// ============================================================
// التهيئة عند التحميل
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
    setTimeout(initVideoPreview, 300);
});


// تصدير
window.initVideoPreview = initVideoPreview;
window.updateVideoPreview = updateVideoPreview;
window.onPlayheadSeek = onPlayheadSeek;
