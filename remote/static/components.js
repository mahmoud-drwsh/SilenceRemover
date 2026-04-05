// UI Components - 2-Row Layout with Native Audio Player

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

// Render single card - 2-row layout with native audio player
function renderCard(file) {
  const t = (key) => getText(key, window.CONFIG.lang);
  const isReady = file.ready;
  
  // Ready toggle: Green ✓ when NOT ready, Red ✗ when ready
  const readyIcon = isReady 
    ? `<span class="checkmark-done" onclick="toggleReady('${file.id}')" title="${t('mark_not_ready')}">✗</span>`
    : `<span class="checkmark-ready" onclick="toggleReady('${file.id}')" title="${t('mark_ready')}">✓</span>`;
  
  return `
    <div id="file-${file.id}" class="card ${isReady ? 'ready' : ''}" data-id="${file.id}">
      
      <!-- Row 1: Native Audio Player + Action Buttons -->
      <div class="row-player-actions">
        <audio controls preload="metadata" class="native-player">
          <source src="${API.getStreamUrl(file.id)}" type="audio/mpeg">
        </audio>
        
        <div class="action-buttons">
          ${readyIcon}
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
      
      <!-- Row 2: Title Textarea Only -->
      <div class="row-title-only">
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
  
  return `
    <div id="file-${file.id}" class="card trashed" data-id="${file.id}">
      
      <div class="row-player-actions trashed">
        <div class="trashed-label">${t('trash')} • ${formatDuration(file.duration)}</div>
        
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
