// ============================================
// main.js — نقطة الدخول الرئيسية (نسخة محسّنة)
// ============================================

import {
    state, initSession, checkConnection, addMessage,
    clearChat, addSuggestion, showToast, cancelProcessing
} from './app.js';

import {
    addVideoLink, uploadVideoFile, removeVideoLink,
    showPreviewWithInfo, hidePreview, cancelPreview,
    openOriginalUrl, downloadVideoFile,
    downloadSelectedQuality, cancelQualityPicker
} from './video.js';

import {
    handleYouTubeAuth, loadMyVideos, loadMySubscriptions,
    searchYouTube, confirmProject, setupEventListeners
} from './integrations.js';

// ============================================
// ⚠️ إتاحة الدوال للنطاق العام (لأن onclick في HTML)
// ============================================
window.clearChat = clearChat;
window.addSuggestion = addSuggestion;
window.cancelProcessing = cancelProcessing;
window.addVideoLink = addVideoLink;
window.uploadVideoFile = uploadVideoFile;
window.removeVideoLink = removeVideoLink;
window.cancelPreview = cancelPreview;
window.confirmProject = confirmProject;
window.openOriginalUrl = openOriginalUrl;
window.handleYouTubeAuth = handleYouTubeAuth;
window.loadMyVideos = loadMyVideos;
window.loadMySubscriptions = loadMySubscriptions;
window.searchYouTube = searchYouTube;
window.downloadSelectedQuality = downloadSelectedQuality;
window.cancelQualityPicker = cancelQualityPicker;

// ⚠️ للتصحيح
window.__state = state;

// ============================================
// ربط data-action (بديل onclick)
// ============================================
function bindDataActions() {
    document.addEventListener('click', (e) => {
        const target = e.target.closest('[data-action]');
        if (!target) return;

        const action = target.dataset.action;
        const actions = {
            // الدردشة والتحكم
            'clear-chat': clearChat,
            'confirm-project': confirmProject,
            'cancel-preview': cancelPreview,
            'open-original': openOriginalUrl,
            'cancel-processing': cancelProcessing,
            'focus-url': () => document.getElementById('url-input')?.focus(),
            'pick-file': () => document.getElementById('video-file')?.click(),

            // الروابط
            'add-link': addVideoLink,

            // يوتيوب
            'youtube-auth': handleYouTubeAuth,
            'load-my-videos': loadMyVideos,
            'load-subscriptions': loadMySubscriptions,
            'search-youtube': searchYouTube,

            // ⭐ الجودة والتنزيل (جديد)
            'download-selected': () => downloadSelectedQuality(),
            'cancel-quality': cancelQualityPicker
        };

        if (actions[action]) {
            e.preventDefault();
            try {
                actions[action]();
            } catch (err) {
                console.error(`❌ خطأ في action "${action}":`, err);
            }
        }
    });

    // اقتراحات
    document.addEventListener('click', (e) => {
        const target = e.target.closest('[data-suggestion]');
        if (!target) return;
        addSuggestion(target.dataset.suggestion);
    });

    // ملف الرفع
    const fileInput = document.getElementById('video-file');
    if (fileInput) {
        fileInput.addEventListener('change', uploadVideoFile);
    }
}

// ============================================
// التهيئة
// ============================================
function init() {
    console.log('🚀 بدء تهيئة التطبيق...');

    try {
        initSession();
        console.log('✅ initSession');

        bindDataActions();
        console.log('✅ bindDataActions');

        setupEventListeners();
        console.log('✅ setupEventListeners');

        checkConnection();
        setInterval(checkConnection, 30000);
        console.log('✅ checkConnection');

        console.log('🎬 AI Video Creator — جاهز');
    } catch (err) {
        console.error('❌ فشل التهيئة:', err);
        showToast('❌ فشل تهيئة التطبيق: ' + err.message, 'error');
    }
}

// ✅ ضمان التشغيل حتى لو تأخر التحميل
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

// ============================================
// معالجات الأخطاء العامة
// ============================================
window.addEventListener('error', (event) => {
    console.error('Global error:', event.error);
});

window.addEventListener('unhandledrejection', (event) => {
    console.error('Unhandled rejection:', event.reason);
});
