// ============================================
// main.js — نقطة الدخول الرئيسية
// ============================================

import {
    state, initSession, checkConnection, addMessage,
    clearChat, addSuggestion, showToast,
    cancelProcessing
} from './app.js';

import {
    addVideoLink, uploadVideoFile, removeVideoLink,
    showPreviewWithInfo, hidePreview, cancelPreview,
    openOriginalUrl, downloadVideoFile
} from './video.js';

import {
    handleYouTubeAuth, loadMyVideos, loadMySubscriptions,
    searchYouTube, confirmProject, setupEventListeners
} from './integrations.js';

// ============================================
// ربط الأزرار بـ data-action (بديل onclick)
// ============================================
function bindDataActions() {
    document.addEventListener('click', (e) => {
        const target = e.target.closest('[data-action]');
        if (!target) return;

        const action = target.dataset.action;

        const actions = {
            'clear-chat': clearChat,
            'confirm-project': confirmProject,
            'cancel-preview': cancelPreview,
            'open-original': openOriginalUrl,
            'cancel-processing': cancelProcessing,
            'add-link': addVideoLink,
            'youtube-auth': handleYouTubeAuth,
            'load-my-videos': loadMyVideos,
            'load-subscriptions': loadMySubscriptions,
            'search-youtube': searchYouTube,
            'focus-url': () => document.getElementById('url-input').focus(),
            'pick-file': () => document.getElementById('video-file').click()
        };

        if (actions[action]) {
            e.preventDefault();
            actions[action]();
        }
    });

    // ربط أزرار الاقتراحات (data-suggestion)
    document.addEventListener('click', (e) => {
        const target = e.target.closest('[data-suggestion]');
        if (!target) return;
        addSuggestion(target.dataset.suggestion);
    });

    // ربط حقل رفع الملف
    const fileInput = document.getElementById('video-file');
    if (fileInput) {
        fileInput.addEventListener('change', uploadVideoFile);
    }
}

// ============================================
// التهيئة
// ============================================
window.addEventListener('error', (event) => {
    console.error('Global error:', event.error);
});

window.addEventListener('unhandledrejection', (event) => {
    console.error('Unhandled rejection:', event.reason);
});

document.addEventListener('DOMContentLoaded', () => {
    initSession();
    bindDataActions();
    setupEventListeners();
    checkConnection();
    setInterval(checkConnection, 30000);

    console.log('🎬 AI Video Creator - Create Page initialized');
    console.log('📡 YouTube API + OAuth 2.0 enabled');
    console.log('✅ Modular architecture: app.js + video.js + integrations.js');
});
