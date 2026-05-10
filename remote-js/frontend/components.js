// UI Components - 2-Row Layout with Native Media Player

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function formatDuration(seconds) {
  if (!seconds || seconds === 0) return '0:00';
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

// Auto-resize textarea to fit content
function autoResizeTextarea(textarea) {
  textarea.style.height = 'auto';
  const newHeight = Math.min(Math.max(textarea.scrollHeight, 24), 96);
  textarea.style.height = newHeight + 'px';
}

// Get media player HTML (audio or video)
function getMediaPlayer(file) {
  const streamUrl = API.getStreamUrl(file.id);
  const isVideo = file.file_type === 'video';
  
  if (isVideo) {
    return `
      <video controls preload="none" class="native-player" style="max-height: 200px;">
        <source src="${streamUrl}" type="video/mp4">
      </video>
      <div style="font-size: 11px; color: #666; margin-top: 4px;">🎬 ${file.duration ? formatDuration(file.duration) : ''}</div>
    `;
  }
  
  return `
    <audio controls preload="none" class="native-player">
      <source src="${streamUrl}" type="audio/mpeg">
    </audio>
  `;
}

// Render single card - 2-row layout with native media player
function renderCard(file) {
  const t = (key) => getText(key, window.CONFIG.lang);
  const isReady = file.ready;
  const isVideo = file.file_type === 'video';
  
  // Ready toggle: Green "Ready" when NOT ready, Red "Cancel" when ready
  const readyLabel = isReady 
    ? `<span class="checkmark-done" onclick="toggleReady('${file.id}')" title="${t('cancel')}">${t('cancel')}</span>`
    : `<span class="checkmark-ready" onclick="toggleReady('${file.id}')" title="${t('mark_ready')}">${t('ready')}</span>`;
  
  // Media type badge
  const typeBadge = isVideo 
    ? `<span style="font-size: 10px; background: #e3f2fd; color: #1976d2; padding: 2px 6px; border-radius: 4px; margin-right: 6px;">${t('video')}</span>`
    : `<span style="font-size: 10px; background: #f3e5f5; color: #7b1fa2; padding: 2px 6px; border-radius: 4px; margin-right: 6px;">${t('audio')}</span>`;
  
  return `
    <div id="file-${file.id}" class="card ${isReady ? 'ready' : ''} ${isVideo ? 'video' : 'audio'}" data-id="${file.id}">
      
      <!-- Row 1: Native Media Player + Action Buttons -->
      <div class="row-player-actions">
        <div style="flex: 1; min-width: 0;">
          ${getMediaPlayer(file)}
        </div>
        
        <div class="action-buttons">
          ${readyLabel}
          <div class="context-menu-container">
            <button class="icon-btn menu-btn" onclick="toggleMenu('${file.id}')" title="${t('more_actions')}">⋮</button>
            <div id="menu-${file.id}" class="context-menu" style="display: none;">
              <button class="menu-item trash" onclick="confirmTrash('${file.id}', '${escapeHtml(file.title || t('untitled'))}'); hideMenu('${file.id}');">
                <span class="menu-icon">🗑</span> ${t('move_to_trash')}
              </button>
            </div>
          </div>
        </div>
      </div>
      
      <!-- Row 2: Title Textarea + Type Badge -->
      <div class="row-title-only">
        ${typeBadge}
        <textarea 
          id="textarea-${file.id}"
          class="title-textarea"
          placeholder="${t('edit_title')}"
          oninput="onTitleInput('${file.id}', this)"
          onfocus="autoResizeTextarea(this)"
          rows="1"
          dir="auto"
        >${escapeHtml(file.title || '')}</textarea>
        <span id="spinner-${file.id}" class="save-indicator" style="display: none;">⏳</span>
        <span id="saved-${file.id}" class="save-indicator" style="display: none;">✓</span>
      </div>
      
    </div>
  `;
}

// Render card for trashed items
function renderTrashedCard(file) {
  const t = (key) => getText(key, window.CONFIG.lang);
  const isVideo = file.file_type === 'video';
  const typeIcon = isVideo ? '🎬' : '🎵';
  
  return `
    <div id="file-${file.id}" class="card trashed" data-id="${file.id}">
      
      <div class="row-player-actions trashed">
        <div class="trashed-label">${typeIcon} ${t('trash')} • ${formatDuration(file.duration)}</div>
        
        <div class="action-buttons">
          <div class="context-menu-container">
            <button class="icon-btn menu-btn" onclick="toggleMenu('${file.id}')" title="${t('more_actions')}">⋮</button>
            <div id="menu-${file.id}" class="context-menu" style="display: none;">
              <button class="menu-item restore" onclick="restore('${file.id}'); hideMenu('${file.id}');">
                <span class="menu-icon">♻️</span> ${t('restore')}
              </button>
              <button class="menu-item delete" onclick="confirmDelete('${file.id}', '${escapeHtml(file.title || t('untitled'))}'); hideMenu('${file.id}');">
                <span class="menu-icon">🗑</span> ${t('delete_forever')}
              </button>
            </div>
          </div>
        </div>
      </div>
      
      <div class="row-title-only">
        <span class="trashed-title" dir="auto">${escapeHtml(file.title || t('untitled'))}</span>
      </div>
      
    </div>
  `;
}

function renderFileList(files, view) {
  const container = document.getElementById('file-list');
  
  const filtered = files.filter(f => {
    if (view === 'notready') return !f.ready && !f.trashed;
    if (view === 'ready') return f.ready && !f.trashed;
    if (view === 'trash') return f.trashed;
    return !f.trashed;
  });
  
  // Sort by ID ascending (default)
  filtered.sort((a, b) => a.id.localeCompare(b.id));
  
  if (filtered.length === 0) {
    const t = (key) => getText(key, window.CONFIG.lang);
    container.innerHTML = `<div class="empty-state">${t('no_files') || 'No files'}</div>`;
    return;
  }
  
  container.innerHTML = filtered.map(f => {
    if (view === 'trash' || f.trashed) {
      return renderTrashedCard(f);
    }
    return renderCard(f);
  }).join('');
  
  // Auto-resize all textareas after render
  setTimeout(() => {
    document.querySelectorAll('.title-textarea').forEach(ta => autoResizeTextarea(ta));
  }, 0);
}

function renderHeader(fileCount, view) {
  const t = (key) => getText(key, window.CONFIG.lang);
  
  const viewNames = {
    notready: t('todo'),
    ready: t('ready'),
    all: t('all'),
    trash: t('trash')
  };
  
  const countText = ` · ${fileCount} ${t('files')}`;
  
  document.getElementById('header').innerHTML = `
    <div style="display: grid; grid-template-columns: 1fr auto; align-items: center; gap: 12px; width: 100%; height: 100%; overflow: hidden; padding: 4px 0;">
      <div style="display: flex; align-items: center; gap: 8px; min-width: 0; overflow: hidden;">
        <span style="font-weight: 600; color: #495057; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; font-size: 14px;">${viewNames[view] || viewNames.notready}</span>
        <span class="header-count" style="color: #6c757d; font-size: 12px; white-space: nowrap; background: rgba(255,255,255,0.6); padding: 2px 8px; border-radius: 12px;">${countText}</span>
      </div>
      <div style="display: flex; flex-shrink: 0; background: #fff; border: 1px solid #dee2e6; border-radius: 6px; overflow: hidden;">
        <a href="?lang=en&view=${view}" style="text-decoration: none; font-size: 10px; padding: 3px 6px; color: ${window.CONFIG.lang === 'en' ? '#fff' : '#495057'}; font-weight: 600; white-space: nowrap; display: block; background: ${window.CONFIG.lang === 'en' ? '#2196F3' : 'transparent'}; border-right: 1px solid #dee2e6;">EN</a>
        <a href="?lang=ar&view=${view}" style="text-decoration: none; font-size: 10px; padding: 3px 6px; color: ${window.CONFIG.lang === 'ar' ? '#fff' : '#495057'}; font-weight: 600; white-space: nowrap; display: block; background: ${window.CONFIG.lang === 'ar' ? '#2196F3' : 'transparent'};">AR</a>
      </div>
    </div>
  `;
}

function renderBottomNav(view) {
  const t = (key) => getText(key, window.CONFIG.lang);
  const views = [
    { id: 'notready', label: t('todo') },
    { id: 'ready', label: t('ready') },
    { id: 'all', label: t('all') },
    { id: 'trash', label: t('trash') }
  ];
  
  document.getElementById('bottom-nav').innerHTML = views.map(v => `
    <a href="?view=${v.id}&lang=${window.CONFIG.lang}" class="${view === v.id ? 'active' : ''}">
      <span>${v.label}</span>
    </a>
  `).join('');
}

// Confirmation dialogs
function confirmTrash(id, title) {
  const t = (key) => getText(key, window.CONFIG.lang);
  if (confirm(`${t('move_to_trash')}\n\n"${title}"`)) {
    moveToTrash(id);
  }
}

function confirmDelete(id, title) {
  const t = (key) => getText(key, window.CONFIG.lang);
  if (confirm(`${t('delete_forever')}\n\n"${title}"`)) {
    deletePermanent(id);
  }
}
