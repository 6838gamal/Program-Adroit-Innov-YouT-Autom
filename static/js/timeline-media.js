// ============================================================
//  timeline-media.js — معرض الوسائط + الرفع + الطبقات
// ============================================================

// ============================================================
//  MEDIA GALLERY
// ============================================================
function renderMediaGallery() {
    const gallery = document.getElementById('mediaGallery');
    const empty = document.getElementById('mediaGalleryEmpty');

    const items = gallery.querySelectorAll('.media-item');
    items.forEach(item => item.remove());

    if (projectData.mediaFiles.length === 0) {
        if (!empty) {
            const newEmpty = document.createElement('span');
            newEmpty.id = 'mediaGalleryEmpty';
            newEmpty.style.cssText = 'color:var(--text-muted);font-size:9px;opacity:0.4;';
            newEmpty.textContent = 'اسحب أو استورد';
            gallery.appendChild(newEmpty);
        } else {
            empty.style.display = 'inline';
        }
        return;
    }

    if (empty) empty.style.display = 'none';

    projectData.mediaFiles.forEach((file, index) => {
        const item = document.createElement('div');
        item.className = 'media-item';
        item.dataset.index = index;

        const isVideo = file.type && file.type.startsWith('video/');
        const isImage = file.type && file.type.startsWith('image/');

        let thumbContent = '';
        if (isImage && file.url) {
            thumbContent = `<img src="${file.url}" alt="${file.name}" loading="lazy">`;
        } else if (isVideo && file.url) {
            thumbContent = `<video src="${file.url}" muted preload="metadata"></video>`;
        } else {
            thumbContent = '📄';
        }

        const clipExists = projectData.clips.some(c =>
            c.metadata && c.metadata.file === file.name
        );

        item.innerHTML = `
            <div class="media-thumb">${thumbContent}</div>
            <span class="media-name">${file.name.slice(0, 15)}</span>
            ${clipExists ? '<span class="media-badge">✓</span>' : ''}
            <button class="media-remove" onclick="event.stopPropagation();removeMediaFile(${index})" title="حذف">✕</button>
        `;

        item.onclick = () => addMediaToTimeline(index);
        gallery.appendChild(item);
    });
}

function addMediaToTimeline(index) {
    const file = projectData.mediaFiles[index];
    if (!file) return;

    const startTime = findNextInsertPoint(selectedLayerIndex, currentTime);

    const type = file.type.split('/')[0];
    const duration = type === 'image' ? 3 : (type === 'video' ? 3 : 2);

    const mediaFile = projectData.mediaFiles.find(f => f.name === file.name);
    const contentUrl = mediaFile ? mediaFile.url : null;

    const clip = {
        id: clipIdCounter++,
        type: type === 'video' ? 'video' : (type === 'audio' ? 'audio' : 'image'),
        layer: selectedLayerIndex,
        start: startTime,
        duration: duration,
        title: file.name.split('.')[0].slice(0, 18),
        content: contentUrl,
        color: COLORS[type] || '#666',
        icon: TYPE_ICONS[type] || '📄',
        metadata: {
            file: file.name,
            size: file.size,
            index: index,
            type: file.type
        }
    };

    projectData.clips.push(clip);
    updateTotalDuration();
    renderTimeline();
    renderMediaGallery();
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
    showToast(`✅ تم إضافة ${file.name} — المؤشر عند ${formatTime(currentTime)}`, 'success');
}

function getLayerEndTime(layerIndex) {
    const layerClips = projectData.clips.filter(c => c.layer === layerIndex);
    if (layerClips.length === 0) return 0;
    const lastClip = layerClips.reduce((max, c) =>
        c.start + c.duration > max.start + max.duration ? c : max
    );
    return lastClip.start + lastClip.duration;
}

function updateTotalDuration() {
    if (projectData.clips.length === 0) {
        projectData.totalDuration = 10;
        return;
    }
    const maxEnd = projectData.clips.reduce((max, c) =>
        Math.max(max, c.start + c.duration), 0
    );
    projectData.totalDuration = Math.max(maxEnd + 2, 10);
}

function removeMediaFile(index) {
    const file = projectData.mediaFiles[index];
    if (file.url && file.url.startsWith('blob:')) {
        URL.revokeObjectURL(file.url);
    }
    projectData.mediaFiles.splice(index, 1);
    renderMediaGallery();
    updateStatus();
    saveProjectData();
}

// ============================================================
//  ADD MEDIA FILE (رفع إلى Supabase)
// ============================================================
async function addMediaFile(file) {
    const fileSizeMB = (file.size / 1024 / 1024).toFixed(2);
    showToast(`⏳ جاري رفع ${file.name} (${fileSizeMB} MB)...`, 'info');

    const supabaseUrl = await uploadFileToSupabase(file, projectId);

    if (!supabaseUrl) {
        showToast(`❌ فشل رفع ${file.name}`, 'error');
        return null;
    }

    const mediaFile = {
        name: file.name,
        size: file.size,
        type: file.type,
        url: supabaseUrl,
    };

    projectData.mediaFiles.push(mediaFile);
    renderMediaGallery();

    showToast(`✅ تم رفع ${file.name}`, 'success');
    return mediaFile;
}

async function handleFiles(files) {
    const previewContainer = document.getElementById('importPreview');
    previewContainer.innerHTML = '';

    const fileArray = Array.from(files);

    for (const file of fileArray) {
        const type = file.type.split('/')[0];
        if (['video', 'audio', 'image'].includes(type)) {
            const preview = document.createElement('span');
            preview.className = 'text-xs bg-slate-700 text-slate-300 px-2 py-1 rounded';
            preview.textContent = `⏳ ${file.name.slice(0, 12)}`;
            previewContainer.appendChild(preview);

            await addMediaFile(file);

            preview.textContent = `${TYPE_ICONS[type] || '📄'} ${file.name.slice(0, 12)}`;
        }
    }

    renderMediaGallery();
    updateStatus();
    closeImportModal();
    showToast(`✅ تم استيراد ${fileArray.length} ملف`, 'success');
}

function openImportModal() {
    document.getElementById('importModal').classList.remove('hidden');
    document.getElementById('importPreview').innerHTML = '';
}

function importFiles() {
    document.getElementById('fileInput').click();
}

function closeImportModal() {
    document.getElementById('importModal').classList.add('hidden');
}

function setupDragDrop() {
    const dropZone = document.getElementById('dropZone');
    const fileInput = document.getElementById('fileInput');

    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.classList.add('dragover');
    });

    dropZone.addEventListener('dragleave', () => {
        dropZone.classList.remove('dragover');
    });

    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('dragover');
        handleFiles(e.dataTransfer.files);
    });

    dropZone.addEventListener('click', () => {
        fileInput.click();
    });

    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) handleFiles(e.target.files);
        fileInput.value = '';
    });

    document.getElementById('trashZone').addEventListener('dragover', (e) => {
        e.preventDefault();
    });

    document.getElementById('trashZone').addEventListener('drop', (e) => {
        e.preventDefault();
        const data = JSON.parse(e.dataTransfer.getData('text/plain'));
        if (data.type === 'clip') {
            deleteClip(data.clipId);
            document.getElementById('trashZone').classList.remove('active');
        }
    });
}

// ============================================================
//  LAYERS
// ============================================================
function renderLayers() {
    const container = document.getElementById('layersList');
    container.innerHTML = '';

    projectData.layers.forEach((layer, index) => {
        const div = document.createElement('div');
        div.className = `layer-item${index === selectedLayerIndex ? ' active' : ''}`;
        div.dataset.index = index;

        const clipCount = projectData.clips.filter(c => c.layer === index).length;

        div.innerHTML = `
            <span class="layer-drag-handle">⠿</span>
            <span class="layer-vis ${layer.visible ? '' : 'hidden'}" onclick="event.stopPropagation();toggleLayerVisibility(${index})">
                ${layer.visible ? '👁️' : '🚫'}
            </span>
            <span class="layer-label">${layer.name}</span>
            <span class="layer-count">${clipCount}</span>
            <div class="layer-actions">
                <button onclick="event.stopPropagation();renameLayer(${index})">✏️</button>
                <button class="danger" onclick="event.stopPropagation();deleteLayer(${index})">🗑️</button>
            </div>
        `;

        div.onclick = () => selectLayer(index);
        container.appendChild(div);
    });

    document.getElementById('layerCount').textContent = projectData.layers.length;
    document.getElementById('statusLayers').textContent = projectData.layers.length;
}

function addLayer() {
    const name = prompt('اسم الطبقة الجديدة:', `طبقة ${projectData.layers.length + 1}`);
    if (name && name.trim()) {
        projectData.layers.push({ name: name.trim(), visible: true, locked: false });
        renderLayers();
        selectLayer(projectData.layers.length - 1);
        saveProjectData();
    }
}

function deleteLayer(index) {
    if (projectData.layers.length <= 1) {
        showToast('⚠️ لا يمكن حذف الطبقة الأخيرة', 'warning');
        return;
    }

    if (!confirm(`حذف الطبقة "${projectData.layers[index].name}"؟`)) return;

    projectData.clips = projectData.clips.filter(c => c.layer !== index);
    projectData.clips.forEach(c => {
        if (c.layer > index) c.layer--;
    });

    projectData.layers.splice(index, 1);
    if (selectedLayerIndex >= projectData.layers.length) selectedLayerIndex = projectData.layers.length - 1;

    updateTotalDuration();
    renderLayers();
    renderTimeline();
    updateStatus();
    saveProjectData();
}

function deleteSelectedLayer() {
    if (selectedLayerIndex !== null) deleteLayer(selectedLayerIndex);
}

function selectLayer(index) {
    selectedLayerIndex = index;
    renderLayers();
}

function toggleLayerVisibility(index) {
    projectData.layers[index].visible = !projectData.layers[index].visible;
    renderLayers();
    renderTimeline();
}

function renameLayer(index) {
    const newName = prompt('اسم الطبقة:', projectData.layers[index].name);
    if (newName && newName.trim()) {
        projectData.layers[index].name = newName.trim();
        renderLayers();
        saveProjectData();
    }
}

function moveLayer(direction) {
    const index = selectedLayerIndex;
    const newIndex = direction === 'up' ? index - 1 : index + 1;
    if (newIndex < 0 || newIndex >= projectData.layers.length) return;

    [projectData.layers[index], projectData.layers[newIndex]] =
    [projectData.layers[newIndex], projectData.layers[index]];

    projectData.clips.forEach(c => {
        if (c.layer === index) c.layer = newIndex;
        else if (c.layer === newIndex) c.layer = index;
    });

    selectedLayerIndex = newIndex;
    renderLayers();
    renderTimeline();
    saveProjectData();
}
