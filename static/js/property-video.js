// ============================================================
//  property-video.js — مولّد فيديو العقارات
//  يندمج مع الـ timeline الموجود + يستخدم addGeneratedClip
// ============================================================

(function () {
    'use strict';

    // ────────────────────────────────────────────────────────
    //  State
    // ────────────────────────────────────────────────────────
    let uploadedImages = [];   // [{ url, path, motion, name }]
    let currentJobId = null;
    let pollTimer = null;
    let isGenerating = false;

    const MAX_IMAGES = 20;
    const MAX_IMAGE_SIZE_MB = 10;

    // ────────────────────────────────────────────────────────
    //  Helpers
    // ────────────────────────────────────────────────────────
    function getProjectId() {
        const el = document.getElementById('timeline-config');
        if (!el) return null;
        try {
            const config = JSON.parse(el.textContent);
            return config.projectId || null;
        } catch (e) {
            console.warn('Failed to parse timeline-config:', e);
            return null;
        }
    }

    function safeToast(msg, type) {
        if (typeof showToast === 'function') {
            showToast(msg, type || 'info');
        } else {
            console.log(`[${type || 'info'}]`, msg);
        }
    }

    function $id(id) {
        return document.getElementById(id);
    }

    function escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // ────────────────────────────────────────────────────────
    //  فتح / إغلاق النافذة
    // ────────────────────────────────────────────────────────
    window.openPropertyVideoStudio = function () {
        const modal = $id('propertyVideoModal');
        if (!modal) {
            console.error('propertyVideoModal not found in DOM');
            safeToast('❌ نافذة مولّد العقارات غير موجودة', 'error');
            return;
        }
        modal.classList.remove('hidden');
        document.body.style.overflow = 'hidden';
    };

    window.closePropertyVideoStudio = function () {
        const modal = $id('propertyVideoModal');
        if (modal) {
            modal.classList.add('hidden');
        }
        document.body.style.overflow = '';

        // أوقف polling إذا كان شغّالاً
        if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
        }

        // لا نُفرّغ الصور — قد يريد المستخدم متابعة لاحقاً
        // uploadedImages = [];  // ← اختياري: علّق عليه إذا أردت الإبقاء
    };

    // ────────────────────────────────────────────────────────
    //  رفع الصور
    // ────────────────────────────────────────────────────────
    window.handlePropertyImages = async function (event) {
        const files = Array.from(event.target.files || []);
        if (files.length === 0) return;

        await addPropertyImages(files);

        // اسمح بإعادة اختيار نفس الملف
        if (event.target) event.target.value = '';
    };

    async function addPropertyImages(files) {
        const projectId = getProjectId();
        if (!projectId) {
            safeToast('❌ لم يتم التعرف على المشروع', 'error');
            return;
        }

        const remaining = MAX_IMAGES - uploadedImages.length;
        if (remaining <= 0) {
            safeToast(`⚠️ الحد الأقصى ${MAX_IMAGES} صورة`, 'warning');
            return;
        }

        const toProcess = files.slice(0, remaining);

        for (const file of toProcess) {
            if (!file.type.startsWith('image/')) {
                safeToast(`⚠️ ${file.name} ليس صورة`, 'warning');
                continue;
            }

            const sizeMB = file.size / 1024 / 1024;
            if (sizeMB > MAX_IMAGE_SIZE_MB) {
                safeToast(
                    `⚠️ ${file.name} كبير (${sizeMB.toFixed(1)}MB > ${MAX_IMAGE_SIZE_MB}MB)`,
                    'warning'
                );
                continue;
            }

            // أضف placeholder فوري
            const tempIndex = uploadedImages.length;
            uploadedImages.push({
                url: URL.createObjectURL(file),
                path: null,
                motion: 'auto',
                name: file.name,
                uploading: true,
                _file: file,
            });
            renderPropertyImagesPreview();

            // ارفع
            try {
                const fd = new FormData();
                fd.append('file', file);
                fd.append('project_id', projectId);

                const r = await fetch('/api/property/upload-image', {
                    method: 'POST',
                    body: fd,
                });

                const data = await r.json();

                if (data.success) {
                    uploadedImages[tempIndex].path = data.path || data.url;
                    uploadedImages[tempIndex].serverUrl = data.url;
                    uploadedImages[tempIndex].uploading = false;
                } else {
                    throw new Error(data.error || 'Upload failed');
                }
            } catch (e) {
                console.error('Upload failed:', e);
                safeToast(`❌ فشل رفع ${file.name}`, 'error');

                // احذف placeholder
                URL.revokeObjectURL(uploadedImages[tempIndex].url);
                uploadedImages.splice(tempIndex, 1);
            }

            renderPropertyImagesPreview();
        }

        updateImagesCounter();
    }

    // ────────────────────────────────────────────────────────
    //  معاينة الصور
    // ────────────────────────────────────────────────────────
    function renderPropertyImagesPreview() {
        const container = $id('propertyImagesPreview');
        if (!container) return;

        container.innerHTML = '';

        uploadedImages.forEach((img, idx) => {
            const div = document.createElement('div');
            div.className = 'relative group';

            const imgUrl = img.serverUrl || img.url;
            const isUploading = img.uploading;

            div.innerHTML = `
                <img src="${imgUrl}"
                     class="w-full h-20 object-cover rounded border border-slate-600 ${isUploading ? 'opacity-50' : ''}">
                ${isUploading ? `
                    <div class="absolute inset-0 flex items-center justify-center bg-black/50 rounded">
                        <span class="text-white text-xs">⏳</span>
                    </div>
                ` : ''}
                <button type="button"
                        onclick="removePropertyImage(${idx})"
                        class="absolute top-1 right-1 bg-red-600 hover:bg-red-700 text-white rounded-full w-5 h-5 text-xs opacity-0 group-hover:opacity-100 transition z-10"
                        title="حذف">×</button>
                <select onchange="setImageMotion(${idx}, this.value)"
                        class="absolute bottom-1 left-1 right-1 text-xs bg-black/70 text-white rounded px-1 py-0.5 border-0 cursor-pointer"
                        title="الحركة">
                    <option value="auto" ${img.motion === 'auto' ? 'selected' : ''}>تلقائي</option>
                    <option value="zoom_in" ${img.motion === 'zoom_in' ? 'selected' : ''}>زووم +</option>
                    <option value="zoom_out" ${img.motion === 'zoom_out' ? 'selected' : ''}>زووم −</option>
                    <option value="pan_left" ${img.motion === 'pan_left' ? 'selected' : ''}>يسار</option>
                    <option value="pan_right" ${img.motion === 'pan_right' ? 'selected' : ''}>يمين</option>
                    <option value="pan_up" ${img.motion === 'pan_up' ? 'selected' : ''}>أعلى</option>
                    <option value="pan_down" ${img.motion === 'pan_down' ? 'selected' : ''}>أسفل</option>
                    <option value="diagonal" ${img.motion === 'diagonal' ? 'selected' : ''}>قطري</option>
                    <option value="cinematic" ${img.motion === 'cinematic' ? 'selected' : ''}>سينمائي</option>
                </select>
            `;

            container.appendChild(div);
        });

        updateImagesCounter();
    }

    function updateImagesCounter() {
        const counter = $id('propertyImagesCount');
        if (!counter) return;

        const ready = uploadedImages.filter(i => !i.uploading).length;
        const uploading = uploadedImages.filter(i => i.uploading).length;

        let text = `${ready} / ${MAX_IMAGES} صورة`;
        if (uploading > 0) {
            text += ` (⏳ ${uploading} جاري الرفع)`;
        }
        counter.textContent = text;
    }

    window.removePropertyImage = function (idx) {
        const img = uploadedImages[idx];
        if (!img) return;

        // نظّف blob URL
        if (img.url && img.url.startsWith('blob:')) {
            URL.revokeObjectURL(img.url);
        }

        uploadedImages.splice(idx, 1);
        renderPropertyImagesPreview();
    };

    window.setImageMotion = function (idx, motion) {
        if (uploadedImages[idx]) {
            uploadedImages[idx].motion = motion;
        }
    };

    window.clearAllPropertyImages = function () {
        if (uploadedImages.length === 0) return;
        if (!confirm(`حذف كل الصور (${uploadedImages.length})؟`)) return;

        uploadedImages.forEach(img => {
            if (img.url && img.url.startsWith('blob:')) {
                URL.revokeObjectURL(img.url);
            }
        });

        uploadedImages = [];
        renderPropertyImagesPreview();
    };

    // ────────────────────────────────────────────────────────
    //  Drag & Drop
    // ────────────────────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', () => {
        const dz = $id('propertyImagesDropZone');
        if (!dz) return;

        ['dragenter', 'dragover'].forEach(evt => {
            dz.addEventListener(evt, (e) => {
                e.preventDefault();
                e.stopPropagation();
                dz.classList.add('border-blue-500', 'bg-blue-500/10');
            });
        });

        ['dragleave', 'drop'].forEach(evt => {
            dz.addEventListener(evt, (e) => {
                e.preventDefault();
                e.stopPropagation();
                dz.classList.remove('border-blue-500', 'bg-blue-500/10');
            });
        });

        dz.addEventListener('drop', async (e) => {
            const files = Array.from(e.dataTransfer.files || []);
            await addPropertyImages(files);
        });
    });

    // ────────────────────────────────────────────────────────
    //  التوليد
    // ────────────────────────────────────────────────────────
    window.generatePropertyVideo = async function () {
        if (isGenerating) {
            safeToast('⏳ التوليد شغّال بالفعل...', 'warning');
            return;
        }

        // ── تحقق من الصور ──
        const readyImages = uploadedImages.filter(i => !i.uploading && i.path);
        if (readyImages.length === 0) {
            safeToast('⚠️ أضف صورة واحدة على الأقل (بانتظار اكتمال الرفع)', 'warning');
            return;
        }

        if (uploadedImages.some(i => i.uploading)) {
            safeToast('⏳ انتظر حتى ينتهي رفع الصور', 'warning');
            return;
        }

        const projectId = getProjectId();
        if (!projectId) {
            safeToast('❌ لم يتم التعرف على المشروع', 'error');
            return;
        }

        // ── اجمع البيانات ──
        const propTypeEl = document.querySelector('input[name="propType"]:checked');
        const featuresRaw = ($id('propFeatures')?.value || '').trim();
        const features = featuresRaw
            .split(/[,،]/)
            .map(s => s.trim())
            .filter(Boolean);

        const payload = {
            project_id: projectId,
            title: ($id('propTitle')?.value || '').trim(),
            property_type: propTypeEl ? propTypeEl.value : 'apartment',
            price: parseFloat($id('propPrice')?.value) || null,
            currency: $id('propCurrency')?.value || 'SAR',
            city: ($id('propCity')?.value || '').trim(),
            district: ($id('propDistrict')?.value || '').trim(),
            area_sqm: parseFloat($id('propArea')?.value) || null,
            bedrooms: parseInt($id('propBedrooms')?.value) || null,
            bathrooms: parseInt($id('propBathrooms')?.value) || null,
            features: features,
            whatsapp: ($id('propWhatsapp')?.value || '').trim(),
            images: readyImages.map(i => ({
                url: i.serverUrl || i.url,
                path: i.path,
                motion: i.motion || 'auto',
            })),
            duration_per_image: parseFloat($id('propDurationPerImage')?.value) || 4.5,
            voiceover_voice: $id('propVoice')?.value || 'ar-SA-HamedNeural',
            show_price: $id('propShowPrice')?.checked !== false,
            show_location: $id('propShowLocation')?.checked !== false,
            show_area: $id('propShowArea')?.checked !== false,
            show_contact: $id('propShowContact')?.checked !== false,
        };

        // ── UI: حالة الانتظار ──
        isGenerating = true;
        const btn = $id('btnGeneratePropertyVideo');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '⏳ جاري التوليد...';
        }

        const progressWrap = $id('propertyVideoProgress');
        if (progressWrap) progressWrap.style.display = 'block';

        updateProgressUI(0.02, 'queued', '⏳ جاري الإرسال...');

        // ── أرسل الطلب ──
        try {
            const r = await fetch('/api/property/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });

            const data = await r.json();

            if (!data.success) {
                throw new Error(data.error || `HTTP ${r.status}`);
            }

            currentJobId = data.job_id;
            safeToast('🎬 بدأ التوليد — جاري المعالجة...', 'info');

            startPollingPropertyJob();

        } catch (e) {
            console.error('Generate failed:', e);
            safeToast('❌ ' + e.message, 'error');
            setStatus('❌ فشل: ' + e.message);
            resetGenerateButton();
        }
    };

    // ────────────────────────────────────────────────────────
    //  متابعة الحالة
    // ────────────────────────────────────────────────────────
    function startPollingPropertyJob() {
        if (pollTimer) clearInterval(pollTimer);

        let errorCount = 0;

        pollTimer = setInterval(async () => {
            try {
                const r = await fetch(`/api/property/status/${currentJobId}`);
                const data = await r.json();

                errorCount = 0;

                if (!data.success) {
                    throw new Error(data.error || 'Status fetch failed');
                }

                updateProgressUI(
                    data.progress || 0,
                    data.stage || '',
                    getStageLabel(data.stage)
                );

                if (data.status === 'done') {
                    clearInterval(pollTimer);
                    pollTimer = null;

                    await handleJobCompleted(data);

                } else if (data.status === 'failed') {
                    clearInterval(pollTimer);
                    pollTimer = null;

                    safeToast('❌ فشل التوليد: ' + (data.error || 'خطأ غير معروف'), 'error');
                    setStatus('❌ ' + (data.error || 'فشل'));
                    resetGenerateButton();
                }

            } catch (e) {
                errorCount++;
                console.warn('Poll error:', e);

                if (errorCount > 5) {
                    clearInterval(pollTimer);
                    pollTimer = null;
                    safeToast('❌ فشل الاتصال بالخادم', 'error');
                    setStatus('❌ فشل الاتصال');
                    resetGenerateButton();
                }
            }
        }, 1500);
    }

    async function handleJobCompleted(data) {
        const projectId = getProjectId();

        // ── 1. احفظ الـ clip في المشروع (backend) ──
        try {
            await fetch(`/api/property/save/${projectId}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    video_url: data.video_url,
                    path: data.path,
                    duration: data.duration,
                    title: data.property_meta?.title || 'فيديو عقاري',
                    property_meta: data.property_meta || {},
                }),
            });
        } catch (e) {
            console.warn('Backend save failed:', e);
        }

        // ── 2. أضف إلى الـ timeline مباشرة ──
        if (typeof addGeneratedClip === 'function') {
            addGeneratedClip(data.video_url, {
                type: 'video',
                title: data.property_meta?.title || 'فيديو عقاري',
                duration: data.duration || 30,
                metadata: {
                    source: 'property_video',
                    job_id: currentJobId,
                    property_meta: data.property_meta || {},
                },
            });
        } else {
            console.warn('addGeneratedClip not found — trying addClipFromUrl');
            if (typeof addClipFromUrl === 'function') {
                addClipFromUrl(data.video_url, {
                    type: 'video',
                    title: data.property_meta?.title || 'فيديو عقاري',
                    duration: data.duration || 30,
                });
            } else {
                safeToast('⚠️ لم يتمكن من إضافة الفيديو للـ timeline', 'warning');
            }
        }

        // ── 3. UI النجاح ──
        const duration = data.duration ? `${data.duration.toFixed(1)}s` : '—';
        setStatus(
            `✅ تم التوليد بنجاح! (${duration}) ` +
            `<a href="${data.video_url}" target="_blank" class="text-blue-400 underline ml-2">فتح الفيديو</a>`
        );

        safeToast('✅ تم توليد الفيديو العقاري وإضافته للمشروع', 'success');

        resetGenerateButton();
    }

    function getStageLabel(stage) {
        const labels = {
            queued: '⏳ في الانتظار',
            motion: '🎬 توليد حركة الصور',
            concat: '🔗 دمج المقاطع',
            voiceover: '🎙️ توليد التعليق الصوتي',
            text: '📝 إضافة النصوص',
            audio: '🎵 دمج الصوت',
            upload: '📤 رفع الفيديو',
            done: '✅ اكتمل',
        };
        return labels[stage] || stage || '';
    }

    function updateProgressUI(progress, stage, label) {
        const fill = $id('propertyVideoProgressFill');
        if (fill) {
            fill.style.width = `${Math.min(100, Math.max(0, progress * 100))}%`;
        }

        const stageEl = $id('propertyVideoStage');
        if (stageEl) {
            stageEl.textContent = label || getStageLabel(stage);
        }
    }

    function setStatus(html) {
        const el = $id('propertyVideoStatus');
        if (el) el.innerHTML = html;
    }

    function resetGenerateButton() {
        isGenerating = false;
        const btn = $id('btnGeneratePropertyVideo');
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '🎬 توليد الفيديو العقاري';
        }
    }

    // ────────────────────────────────────────────────────────
    //  تنظيف عند إغلاق الصفحة
    // ────────────────────────────────────────────────────────
    window.addEventListener('beforeunload', () => {
        if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
        }

        // نظّف blob URLs
        uploadedImages.forEach(img => {
            if (img.url && img.url.startsWith('blob:')) {
                URL.revokeObjectURL(img.url);
            }
        });
    });

    // ────────────────────────────────────────────────────────
    //  Expose for debugging
    // ────────────────────────────────────────────────────────
    window.__propertyVideoDebug = {
        getState: () => ({
            uploadedImages: uploadedImages.map(i => ({
                name: i.name,
                motion: i.motion,
                uploading: i.uploading,
                hasPath: !!i.path,
            })),
            currentJobId,
            isGenerating,
        }),
        getImages: () => uploadedImages,
        addTestImage: (url) => {
            uploadedImages.push({
                url: url,
                path: url,
                serverUrl: url,
                motion: 'auto',
                name: 'test.jpg',
                uploading: false,
            });
            renderPropertyImagesPreview();
        },
    };

    console.log('🏠 property-video.js loaded');

})();
