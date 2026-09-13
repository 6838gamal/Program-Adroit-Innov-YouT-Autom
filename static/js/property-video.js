// ============================================================
//  property-video.js — مولّد فيديو العقارات
//  يندمج مع الـ timeline الموجود + يستخدم addGeneratedClip
//
//  ✅ UPDATED:
//     - إضافة صور عبر روابط URL
//     - معاينة الفيديو بعد الرندر
//     - خيارات: تنزيل / إضافة للتايم لاين / فيديو جديد
//     - إزالة الإضافة التلقائية للتايم لاين
// ============================================================

(function () {
    'use strict';

    // ────────────────────────────────────────────────────────
    //  State
    // ────────────────────────────────────────────────────────
    let uploadedImages = [];   // [{ url, path, motion, name, uploading, serverUrl, isExternalUrl }]
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

        if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
        }
    };

    // ────────────────────────────────────────────────────────
    //  رفع الصور من الجهاز
    // ────────────────────────────────────────────────────────
    window.handlePropertyImages = async function (event) {
        const files = Array.from(event.target.files || []);
        if (files.length === 0) return;

        await addPropertyImages(files);

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

            const tempIndex = uploadedImages.length;
            uploadedImages.push({
                url: URL.createObjectURL(file),
                path: null,
                motion: 'auto',
                name: file.name,
                uploading: true,
                _file: file,
                isExternalUrl: false,
            });
            renderPropertyImagesPreview();

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

                URL.revokeObjectURL(uploadedImages[tempIndex].url);
                uploadedImages.splice(tempIndex, 1);
            }

            renderPropertyImagesPreview();
        }

        updateImagesCounter();
    }

    // ────────────────────────────────────────────────────────
    //  ✅ NEW: إضافة صور عبر روابط URL
    // ────────────────────────────────────────────────────────
    window.addPropertyImagesFromUrls = function () {
        const input = $id('propertyImageUrlsInput');
        if (!input) return;

        const raw = (input.value || '').trim();
        if (!raw) {
            safeToast('⚠️ أدخل رابطاً واحداً على الأقل', 'warning');
            return;
        }

        // ✅ افصل بالأسطر، أو الفواصل، أو الفواصل المنقوطة، أو المسافات
        const urls = raw
            .split(/[\n,;،]+/)
            .map(u => u.trim())
            .filter(u => u.length > 0);

        if (urls.length === 0) {
            safeToast('⚠️ لم يتم العثور على روابط صالحة', 'warning');
            return;
        }

        let added = 0;
        let failed = 0;
        let skipped = 0;

        for (const url of urls) {
            if (uploadedImages.length >= MAX_IMAGES) {
                safeToast(`⚠️ وصلت للحد الأقصى (${MAX_IMAGES})`, 'warning');
                break;
            }

            // ✅ تحقق من الرابط
            if (!/^https?:\/\/.+\.(jpg|jpeg|png|webp|gif|bmp)(\?.*)?$/i.test(url)) {
                safeToast(`⚠️ رابط غير صالح: ${url.slice(0, 40)}...`, 'warning');
                failed++;
                continue;
            }

            // ✅ تحقق أنه ليس موجوداً مسبقاً
            if (uploadedImages.some(img =>
                (img.serverUrl && img.serverUrl === url) ||
                (img.path && img.path === url)
            )) {
                skipped++;
                continue;
            }

            uploadedImages.push({
                url: url,
                serverUrl: url,
                path: url,          // ✅ نستخدم URL كـ path مباشرة
                motion: 'auto',
                name: url.split('/').pop().split('?')[0] || 'image.jpg',
                uploading: false,
                isExternalUrl: true,
            });
            added++;
        }

        if (added > 0) {
            renderPropertyImagesPreview();
            updateImagesCounter();
            input.value = '';

            let msg = `✅ تم إضافة ${added} صورة`;
            if (failed > 0) msg += ` (فشل ${failed})`;
            if (skipped > 0) msg += ` (تخطي ${skipped} مكررة)`;

            safeToast(msg, 'success');
        } else {
            if (skipped > 0) {
                safeToast(`⚠️ كل الروابط موجودة مسبقاً (${skipped})`, 'warning');
            } else if (failed > 0) {
                safeToast(`❌ فشل إضافة ${failed} رابط`, 'error');
            }
        }
    };

    // ✅ امسح حقل الروابط
    window.clearPropertyUrlsInput = function () {
        const input = $id('propertyImageUrlsInput');
        if (input) input.value = '';
    };

    // ✅ امسح كل الصور
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
            const isExternal = img.isExternalUrl;

            div.innerHTML = `
                <img src="${imgUrl}"
                     class="w-full h-20 object-cover rounded border border-slate-600 ${isUploading ? 'opacity-50' : ''}"
                     onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%22100%22 height=%2280%22><rect width=%22100%22 height=%2280%22 fill=%22%23334155%22/><text x=%2250%22 y=%2245%22 text-anchor=%22middle%22 fill=%22%23ef4444%22 font-size=%2220%22>⚠️</text></svg>'">
                ${isUploading ? `
                    <div class="absolute inset-0 flex items-center justify-center bg-black/50 rounded">
                        <span class="text-white text-xs">⏳</span>
                    </div>
                ` : ''}
                ${isExternal ? `
                    <div class="absolute top-1 left-1 bg-blue-600 text-white rounded px-1.5 py-0.5 text-[9px] z-10 font-bold">
                        🔗 URL
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
        const external = uploadedImages.filter(i => i.isExternalUrl).length;

        let text = `${ready} / ${MAX_IMAGES} صورة`;
        if (uploading > 0) {
            text += ` (⏳ ${uploading} جاري الرفع)`;
        }
        if (external > 0) {
            text += ` — 🔗 ${external} من روابط`;
        }
        counter.textContent = text;
    }

    window.removePropertyImage = function (idx) {
        const img = uploadedImages[idx];
        if (!img) return;

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

        // ✅ امسح أي معاينة سابقة
        resetPropertyVideoPreview();

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

    // ────────────────────────────────────────────────────────
    //  ✅ UPDATED: عند اكتمال الـ job — معاينة بدل الإضافة التلقائية
    // ────────────────────────────────────────────────────────
    async function handleJobCompleted(data) {
        // ✅ احفظ بيانات الفيديو في متغير عام للمعاينة
        window._lastPropertyVideo = {
            url: data.video_url,
            path: data.path,
            duration: data.duration,
            title: data.property_meta?.title || 'فيديو عقاري',
            property_meta: data.property_meta || {},
            job_id: currentJobId,
        };

        // ✅ اعرض المعاينة (بدل إضافة تلقائية للتايم لاين)
        showPropertyVideoPreview(data);

        const duration = data.duration ? `${data.duration.toFixed(1)}s` : '—';
        safeToast(`✅ تم التوليد بنجاح! (${duration})`, 'success');

        resetGenerateButton();
    }

    // ────────────────────────────────────────────────────────
    //  ✅ NEW: معاينة الفيديو بعد الرندر
    // ────────────────────────────────────────────────────────
    function showPropertyVideoPreview(data) {
        const container = $id('propertyVideoResult');
        if (!container) {
            console.warn('propertyVideoResult container not found');
            return;
        }

        const duration = data.duration ? `${data.duration.toFixed(1)}s` : '—';

        container.innerHTML = `
            <div class="bg-slate-900/60 border border-slate-700 rounded-lg p-3 mt-3">
                <div class="flex items-center justify-between mb-3">
                    <div class="flex items-center gap-2">
                        <span class="text-green-400 text-lg">✅</span>
                        <span class="text-white text-sm font-semibold">تم التوليد بنجاح</span>
                    </div>
                    <div class="flex gap-2 text-xs">
                        <span class="bg-slate-700 text-slate-300 px-2 py-1 rounded">
                            ⏱️ ${duration}
                        </span>
                    </div>
                </div>

                <!-- ✅ مشغّل الفيديو -->
                <div class="rounded-lg overflow-hidden bg-black mb-3" style="aspect-ratio: 9/16; max-height: 400px;">
                    <video
                        id="propertyVideoPreviewPlayer"
                        src="${data.video_url}"
                        controls
                        playsinline
                        preload="metadata"
                        style="width: 100%; height: 100%; object-fit: contain; background: #000;"
                    ></video>
                </div>

                <!-- ✅ خيارات -->
                <div class="grid grid-cols-3 gap-2">
                    <button type="button" onclick="downloadPropertyVideo()"
                            class="btn-secondary btn-sm"
                            title="تنزيل الفيديو">
                        ⬇️ تنزيل
                    </button>
                    <button type="button" onclick="addPropertyVideoToTimeline()"
                            class="btn-primary btn-sm"
                            title="إضافة إلى التايم لاين">
                        ➕ إضافة للتايم لاين
                    </button>
                    <button type="button" onclick="resetPropertyVideoPreview()"
                            class="btn-secondary btn-sm"
                            title="توليد فيديو جديد">
                        🔄 فيديو جديد
                    </button>
                </div>
            </div>
        `;

        container.style.display = 'block';

        // ✅ اسحب الشاشة للمعاينة
        setTimeout(() => {
            container.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }, 100);
    }

    // ✅ تنزيل الفيديو
    window.downloadPropertyVideo = async function () {
        const info = window._lastPropertyVideo;
        if (!info || !info.url) {
            safeToast('⚠️ لا يوجد فيديو للتنزيل', 'warning');
            return;
        }

        try {
            safeToast('⏳ جاري التنزيل...', 'info');

            const r = await fetch(info.url);
            if (!r.ok) throw new Error('فشل التنزيل');

            const blob = await r.blob();
            const url = URL.createObjectURL(blob);

            const a = document.createElement('a');
            a.href = url;
            a.download = `property_${Date.now()}.mp4`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);

            setTimeout(() => URL.revokeObjectURL(url), 1000);

            safeToast('✅ تم التنزيل', 'success');
        } catch (e) {
            console.error('Download failed:', e);
            safeToast('❌ فشل التنزيل — سيُفتح في نافذة جديدة', 'error');
            window.open(info.url, '_blank');
        }
    };

    // ✅ إضافة الفيديو للتايم لاين يدوياً
    window.addPropertyVideoToTimeline = async function () {
        const info = window._lastPropertyVideo;
        if (!info || !info.url) {
            safeToast('⚠️ لا يوجد فيديو', 'warning');
            return;
        }

        const projectId = getProjectId();

        // احفظ في backend (project.data.clips)
        try {
            await fetch(`/api/property/save/${projectId}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    video_url: info.url,
                    path: info.path,
                    duration: info.duration,
                    title: info.title,
                    property_meta: info.property_meta,
                }),
            });
        } catch (e) {
            console.warn('Backend save failed:', e);
        }

        // أضف للتايم لاين
        if (typeof addGeneratedClip === 'function') {
            addGeneratedClip(info.url, {
                type: 'video',
                title: info.title,
                duration: info.duration || 30,
                metadata: {
                    source: 'property_video',
                    job_id: info.job_id,
                    property_meta: info.property_meta,
                },
            });
            safeToast('✅ تم إضافة الفيديو للتايم لاين', 'success');
        } else if (typeof addClipFromUrl === 'function') {
            addClipFromUrl(info.url, {
                type: 'video',
                title: info.title,
                duration: info.duration || 30,
            });
            safeToast('✅ تم إضافة الفيديو للتايم لاين', 'success');
        } else {
            safeToast('⚠️ لم يتمكن من إضافة الفيديو للتايم لاين', 'warning');
        }
    };

    // ✅ إعادة تعيين المعاينة (لتوليد جديد)
    window.resetPropertyVideoPreview = function () {
        const container = $id('propertyVideoResult');
        if (container) {
            container.innerHTML = '';
            container.style.display = 'none';
        }

        const progress = $id('propertyVideoProgress');
        if (progress) progress.style.display = 'none';

        const status = $id('propertyVideoStatus');
        if (status) status.innerHTML = '';

        window._lastPropertyVideo = null;
    };

    // ────────────────────────────────────────────────────────
    //  Helpers للـ UI
    // ────────────────────────────────────────────────────────
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
                isExternal: !!i.isExternalUrl,
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
                isExternalUrl: true,
            });
            renderPropertyImagesPreview();
        },
    };

    console.log('🏠 property-video.js loaded');

})();
