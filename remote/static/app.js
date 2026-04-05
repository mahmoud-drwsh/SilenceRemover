// Main Application - 2-Row Layout with Native Audio Player

let allFiles = [];
let currentView = 'notready';
let saveTimeout;

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

// Start
init();
