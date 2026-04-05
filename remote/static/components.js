// UI Components - Compact 3-Row Layout (No Accordion)

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
  const newHeight = Math.min(Math.max(textarea.scrollHeight, 24), 96); // 1-4 lines
  textarea.style.height = newHeight + 'px';
}

// Render single card - 3-row compact layout
function renderCard(file) {
  const t = (key) => getText(key, window.CONFIG.lang);
  const isReady = file.ready;
  const isTrashed = file.trashed;
  
  // Red X logic: Green ✓ when NOT ready, Red ✗ when ready
  const readyIcon = isReady 
    ? `<span class="checkmark-done" onclick="toggleReady('${file.id}')" title="${t('mark_not_ready')}">✗</span>`
    : `<span class="checkmark-ready" onclick="toggleReady('${file.id}')" title="${t('mark_ready')}">✓</span>`;
  
  return `
    <div id="file-${file.id}" class="card ${isReady ? 'ready' : ''} ${isTrashed ? 'trashed' : ''}" data-id="${file.id}">
      
      <!-- Row 1: Info + Actions -->
      <div class="row-info">
        <button class="play-btn" id="play-${file.id}" onclick="togglePlay('${file.id}', event)">
          ▶
        </button>
        
        <div class="title-display" id="display-${file.id}">${escapeHtml(file.title || t('untitled'))}</div>
        
        <div class="meta">
          <span class="duration">${formatDuration(file.duration)}</span>
  ${readyIcon}
          <button class="icon-btn trash-btn" onclick="confirmTrash('${file.id}', '${escapeHtml(file.title || t('untitled'))}')" title="${t('move_to_trash')}">
            🗑
          </button>
        </div>
      </div>
      
      <!-- Row 2: Progress Bar (Always Visible) -->
      <div class="row-progress">
        <div class="progress-container" onclick="seekAudio(event, '${file.id}')">
          <div class="progress-bar">
            <div class="progress-fill" id="fill-${file.id}" style="width: 0%"></div>
          </div>
          <div class="progress-handle" id="handle-${file.id}" style="left: 0%"></div>
        </div>
      </div>
      
      <!-- Row 3: Auto-resizing Title Textarea -->
      <div class="row-title">
        <textarea 
          id="textarea-${file.id}"
          class="title-textarea"
          placeholder="${t('edit_title')}"
          oninput="onTitleInput('${file.id}', this)"
          onfocus="autoResizeTextarea(this)"
          rows="1"
        >${escapeHtml(file.title || '')}</textarea>
        <span id="spinner-${file.id}" class="save-indicator" style="display: none;">⏳</span>
        <span id="saved-${file.id}" class="save-indicator" style="display: none;">✓</span>
      </div>
      
    </div>
  `;
}

// Render card for trashed items (simpler - no progress, restore instead of trash)
function renderTrashedCard(file) {
  const t = (key) => getText(key, window.CONFIG.lang);
  
  return `
    <div id="file-${file.id}" class="card trashed" data-id="${file.id}">
      
      <div class="row-info">
        <div class="play-btn disabled">▶</div>
        <div class="title-display trashed">${escapeHtml(file.title || t('untitled'))}</div>
        
        <div class="meta">
          <span class="duration">${formatDuration(file.duration)}</span>
          <button class="icon-btn restore-btn" onclick="restore('${file.id}')" title="${t('restore')}">
            ♻️
          </button>
          <button class="icon-btn delete-btn" onclick="confirmDelete('${file.id}', '${escapeHtml(file.title || t('untitled'))}')" title="${t('delete_forever')}">
            🗑
          </button>
        </div>
      </div>
      
      <!-- Simple row for trashed items -->
      <div class="row-title trashed-info">
        <span class="trashed-label">${t('trash')} • ${file.id}</span>
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
    return !f.trashed; // 'all'
  });
  
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
  
  // Short view names without emojis for space
  const viewNames = {
    notready: t('todo'),
    ready: t('ready'), 
    all: t('all'),
    trash: t('trash')
  };
  
  // Always show count: "3 files"
  const countText = ` · ${fileCount} ${t('files')}`;
  
  document.getElementById('header').innerHTML = `
    <div style="display: grid; grid-template-columns: 1fr auto; align-items: center; gap: 8px; width: 100%; height: 100%; overflow: hidden;">
      <div style="display: flex; align-items: center; gap: 6px; min-width: 0; overflow: hidden;">
        <span style="font-weight: 500; color: #333; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0;">${viewNames[view] || viewNames.notready}</span>
        <span class="header-count" style="color: #666; font-size: 12px; white-space: nowrap;">${countText}</span>
      </div>
      <div style="display: flex; gap: 4px; flex-shrink: 0;">
        <a href="?lang=en&view=${view}" style="text-decoration: none; font-size: 11px; padding: 3px 6px; border-radius: 3px; color: #666; font-weight: 500; border: 1px solid transparent; white-space: nowrap; display: block; ${window.CONFIG.lang === 'en' ? 'background: #2196F3; color: white; border-color: #2196F3;' : ''}">EN</a>
        <a href="?lang=ar&view=${view}" style="text-decoration: none; font-size: 11px; padding: 3px 6px; border-radius: 3px; color: #666; font-weight: 500; border: 1px solid transparent; white-space: nowrap; display: block; ${window.CONFIG.lang === 'ar' ? 'background: #2196F3; color: white; border-color: #2196F3;' : ''}">AR</a>
      </div>
    </div>
  `;
}

function renderBottomNav(view) {
  const t = (key) => getText(key, window.CONFIG.lang);
  const views = [
    { id: 'notready', icon: '⏳', label: t('todo') },
    { id: 'ready', icon: '✓', label: t('ready') },
    { id: 'all', icon: '📁', label: t('all') },
    { id: 'trash', icon: '🗑', label: t('trash') }
  ];
  
  document.getElementById('bottom-nav').innerHTML = views.map(v => `
    <a href="?view=${v.id}&lang=${window.CONFIG.lang}" class="${view === v.id ? 'active' : ''}">
      <span class="icon">${v.icon}</span>
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
