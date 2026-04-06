// Main Application - 2-Row Layout with Native Audio Player

let allFiles = [];
let currentView = 'notready';
let saveTimeout;
let modalCallback = null;

// Modal functions
function showModal(title, message, confirmText, cancelText, isDanger = false) {
  const t = (key) => getText(key, window.CONFIG.lang);
  
  document.getElementById('modal-title').textContent = title;
  document.getElementById('modal-message').textContent = message;
  document.getElementById('modal-confirm').textContent = confirmText || t('confirm');
  document.getElementById('modal-cancel').textContent = cancelText || t('cancel');
  
  const confirmBtn = document.getElementById('modal-confirm');
  if (isDanger) {
    confirmBtn.classList.add('danger');
  } else {
    confirmBtn.classList.remove('danger');
  }
  
  document.getElementById('modal-overlay').style.display = 'flex';
  
  return new Promise((resolve) => {
    modalCallback = resolve;
  });
}

function closeModal(confirmed) {
  document.getElementById('modal-overlay').style.display = 'none';
  if (modalCallback) {
    modalCallback(confirmed);
    modalCallback = null;
  }
}

// Initialize
async function init() {
  const params = new URLSearchParams(location.search);
  currentView = params.get('view') || 'notready';
  
  await loadFiles();
  
  window.addEventListener('popstate', () => {
    const params = new URLSearchParams(location.search);
    currentView = params.get('view') || 'notready';
    window.CONFIG.lang = params.get('lang') || window.CONFIG.lang;
    loadFiles();
  });
}

async function loadFiles() {
  try {
    allFiles = await API.getFiles();
    render();
  } catch (err) {
    console.error('Failed to load files:', err);
    document.getElementById('file-list').innerHTML = 
      '<div class="error">Failed to load files. Please refresh.</div>';
  }
}

function render() {
  const filtered = allFiles.filter(f => {
    if (currentView === 'notready') return !f.ready && !f.trashed;
    if (currentView === 'ready') return f.ready && !f.trashed;
    if (currentView === 'trash') return f.trashed;
    return !f.trashed;
  });
  
  renderHeader(filtered.length, currentView);
  renderFileList(allFiles, currentView);
  renderBottomNav(currentView);
}

// Auto-resize textarea as user types
function onTitleInput(id, textarea) {
  autoResizeTextarea(textarea);
  
  // Debounced save
  clearTimeout(saveTimeout);
  saveTimeout = setTimeout(async () => {
    try {
      showSpinner(id, true);
      await API.updateTitle(id, textarea.value);
      
      const file = allFiles.find(f => f.id === id);
      if (file) file.title = textarea.value;
      
      showSaved(id);
    } catch (err) {
      console.error('Failed to save:', err);
      alert(getText('save_error'));
    } finally {
      showSpinner(id, false);
    }
  }, 500);
}

function showSpinner(id, show) {
  const spinner = document.getElementById(`spinner-${id}`);
  if (spinner) spinner.style.display = show ? 'inline' : 'none';
}

function showSaved(id) {
  const saved = document.getElementById(`saved-${id}`);
  if (saved) {
    saved.style.display = 'inline';
    setTimeout(() => { saved.style.display = 'none'; }, 1000);
  }
}

// Toggle ready status
async function toggleReady(id) {
  const file = allFiles.find(f => f.id === id);
  if (!file) return;
  
  const newReady = !file.ready;
  const t = (key) => getText(key, window.CONFIG.lang);
  
  // Confirm when marking as ready (green checkmark), allow instant unmark
  if (newReady) {
    const title = file.title || t('untitled');
    const confirmed = await showModal(
      t('confirm_ready'),
      title,
      t('confirm'),
      t('cancel'),
      false
    );
    if (!confirmed) return;
  }
  
  try {
    await API.toggleReady(id, newReady);
    file.ready = newReady;
    render();
  } catch (err) {
    console.error('Failed to toggle ready:', err);
  }
}

// Move to trash
async function moveToTrash(id) {
  try {
    await API.moveToTrash(id);
    const file = allFiles.find(f => f.id === id);
    if (file) file.trashed = true;
    render();
  } catch (err) {
    console.error('Failed to trash:', err);
  }
}

// Restore from trash
async function restore(id) {
  try {
    await API.restore(id);
    const file = allFiles.find(f => f.id === id);
    if (file) file.trashed = false;
    render();
  } catch (err) {
    console.error('Failed to restore:', err);
  }
}

// Delete permanently
async function deletePermanent(id) {
  try {
    await API.deletePermanent(id);
    allFiles = allFiles.filter(f => f.id !== id);
    render();
  } catch (err) {
    console.error('Failed to delete:', err);
  }
}

// Context menu functions
function toggleMenu(id) {
  const menu = document.getElementById(`menu-${id}`);
  if (!menu) return;
  
  // Close all other menus first
  document.querySelectorAll('.context-menu').forEach(m => {
    if (m.id !== `menu-${id}`) m.style.display = 'none';
  });
  
  // Toggle this menu
  menu.style.display = menu.style.display === 'none' ? 'block' : 'none';
}

function hideMenu(id) {
  const menu = document.getElementById(`menu-${id}`);
  if (menu) menu.style.display = 'none';
}

// Close menus when clicking outside
document.addEventListener('click', function(e) {
  if (!e.target.closest('.context-menu-container')) {
    document.querySelectorAll('.context-menu').forEach(m => {
      m.style.display = 'none';
    });
  }
});

// Start
init();

// Global audio coordination: pause others when one plays
document.addEventListener('play', function(e) {
  if (e.target.tagName === 'AUDIO') {
    // Pause all other audio elements
    document.querySelectorAll('audio').forEach(audio => {
      if (audio !== e.target && !audio.paused) {
        audio.pause();
      }
    });
  }
}, true);
