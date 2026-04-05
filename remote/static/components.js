// UI Components

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function formatDuration(seconds) {
  if (!seconds) return '0:00';
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

function renderCard(file) {
  const t = (key) => getText(key, window.CONFIG.lang);
  const statusIcon = file.ready ? '✓' : '⏳';
  const readyBtnText = file.ready ? t('mark_not_ready') : t('mark_ready');
  const readyClass = file.ready ? 'ready' : '';
  const readyBtnClass = file.ready ? 'btn-unready' : 'btn-ready';
  
  return `
    <div id="file-${file.id}" class="card ${readyClass}" data-id="${file.id}">
      <div class="card-header" onclick="toggleExpand('${file.id}')">
        <button class="play-btn" onclick="playAudio('${file.id}', '${escapeHtml(file.filename)}', event)">▶</button>
        <div id="title-${file.id}" class="card-title">${escapeHtml(file.title || t('untitled'))}</div>
        <div class="card-meta">
          <div>${formatDuration(file.duration)}</div>
          <div class="status">${statusIcon}</div>
        </div>
      </div>
      
      <div class="card-details" id="details-${file.id}">
        <div class="progress-bar" data-file-id="${file.id}" onclick="seekAudio(event, '${file.id}')">
          <div class="progress-fill" id="progress-${file.id}"></div>
          <div class="progress-handle" id="handle-${file.id}"></div>
        </div>
        
        <div class="file-id">${file.id}</div>
        
        <input type="text" 
               id="input-${file.id}"
               class="title-input"
               value="${escapeHtml(file.title || '')}" 
               placeholder="${t('edit_title')}"
               oninput="onTitleInput('${file.id}', this.value)"
               onclick="event.stopPropagation()">
        
        <span id="spinner-${file.id}" class="spinner" style="display: none;">⏳</span>
        
        <div class="actions" onclick="event.stopPropagation()">
          ${file.trashed ? renderTrashedButtons(file.id, t) : renderActiveButtons(file.id, file.ready, readyBtnText, readyBtnClass, t)}
        </div>
      </div>
    </div>
  `;
}

function renderActiveButtons(id, ready, readyBtnText, readyBtnClass, t) {
  return `
    <button class="${readyBtnClass}" onclick="toggleReady('${id}', ${!ready})">
      ${readyBtnText}
    </button>
    <button class="btn-icon btn-trash" onclick="moveToTrash('${id}')" title="${t('move_to_trash')}">
      🗑
    </button>
  `;
}

function renderTrashedButtons(id, t) {
  return `
    <button class="btn-restore" style="flex: 3;" onclick="restore('${id}')">
      ♻️ ${t('restore')}
    </button>
    <button class="btn-icon btn-delete" onclick="deletePermanent('${id}')" title="${t('delete_forever')}">
      🗑
    </button>
  `;
}

function renderHeader(fileCount, view) {
  const t = (key) => getText(key, window.CONFIG.lang);
  const viewNames = {
    notready: '⏳ ' + t('todo'),
    ready: '✓ ' + t('ready'),
    all: '📁 ' + t('all'),
    trash: '🗑 ' + t('trash')
  };
  
  document.getElementById('header').innerHTML = `
    <div class="header-info">
      <span class="header-view">${viewNames[view] || viewNames.notready}</span>
      <span class="header-count">· ${fileCount}</span>
    </div>
    <div class="lang-switch">
      <a href="?lang=en&view=${view}" class="${window.CONFIG.lang === 'en' ? 'active' : ''}">EN</a>
      <a href="?lang=ar&view=${view}" class="${window.CONFIG.lang === 'ar' ? 'active' : ''}">AR</a>
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

function renderFileList(files, view) {
  const container = document.getElementById('file-list');
  
  // Filter based on view
  const filtered = files.filter(f => {
    if (view === 'notready') return !f.ready && !f.trashed;
    if (view === 'ready') return f.ready && !f.trashed;
    if (view === 'trash') return f.trashed;
    return !f.trashed; // 'all' - exclude trashed
  });
  
  if (filtered.length === 0) {
    container.innerHTML = '<div class="empty-state">No files</div>';
    return;
  }
  
  container.innerHTML = filtered.map(renderCard).join('');
}

function toggleExpand(id) {
  const card = document.getElementById(`file-${id}`);
  card.classList.toggle('expanded');
}
