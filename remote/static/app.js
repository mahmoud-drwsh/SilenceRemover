// Main Application

let allFiles = [];
let currentView = 'notready';
let saveTimeout;
let currentAudio = null;
let currentPlayingId = null;

// Initialize
async function init() {
  // Get view from URL
  const params = new URLSearchParams(location.search);
  currentView = params.get('view') || 'notready';
  
  // Load files
  await loadFiles();
  
  // Setup popstate for back button
  window.addEventListener('popstate', () => {
    const params = new URLSearchParams(location.search);
    currentView = params.get('view') || 'notready';
    window.CONFIG.lang = params.get('lang') || window.CONFIG.lang;
    render();
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
  renderFileList(allFiles, currentView); // Pass all for proper filtering
  renderBottomNav(currentView);
}

// Actions
async function onTitleInput(id, value) {
  // Update UI immediately
  document.getElementById(`title-${id}`).textContent = value || getText('untitled');
  
  // Debounced save
  clearTimeout(saveTimeout);
  saveTimeout = setTimeout(async () => {
    try {
      document.getElementById(`spinner-${id}`).style.display = 'inline';
      await API.updateTitle(id, value);
      // Update local cache
      const file = allFiles.find(f => f.id === id);
      if (file) file.title = value;
    } catch (err) {
      console.error('Failed to save:', err);
      alert(getText('save_error'));
    } finally {
      document.getElementById(`spinner-${id}`).style.display = 'none';
    }
  }, 500);
}

async function toggleReady(id, ready) {
  try {
    await API.toggleReady(id, ready);
    // Update local cache
    const file = allFiles.find(f => f.id === id);
    if (file) {
      file.ready = ready;
      // If in todo view and marking ready, remove from view
      if (currentView === 'notready' && ready) {
        document.getElementById(`file-${id}`)?.remove();
      } else {
        render(); // Re-render to update button state
      }
    }
  } catch (err) {
    console.error('Failed to toggle ready:', err);
  }
}

async function moveToTrash(id) {
  if (!confirm(getText('move_to_trash'))) return;
  try {
    await API.moveToTrash(id);
    document.getElementById(`file-${id}`)?.remove();
    // Update cache
    const file = allFiles.find(f => f.id === id);
    if (file) file.trashed = true;
  } catch (err) {
    console.error('Failed to trash:', err);
  }
}

async function restore(id) {
  try {
    await API.restore(id);
    document.getElementById(`file-${id}`)?.remove();
    const file = allFiles.find(f => f.id === id);
    if (file) file.trashed = false;
  } catch (err) {
    console.error('Failed to restore:', err);
  }
}

async function deletePermanent(id) {
  if (!confirm(getText('delete_forever'))) return;
  try {
    await API.deletePermanent(id);
    document.getElementById(`file-${id}`)?.remove();
    allFiles = allFiles.filter(f => f.id !== id);
  } catch (err) {
    console.error('Failed to delete:', err);
  }
}

// Audio Player
function playAudio(id, filename, event) {
  event.stopPropagation();
  
  const streamUrl = API.getStreamUrl(id);
  
  // If clicking the same playing audio, toggle pause
  if (currentPlayingId === id && currentAudio) {
    if (currentAudio.paused) {
      currentAudio.play();
    } else {
      currentAudio.pause();
    }
    return;
  }
  
  // Stop current if different
  if (currentAudio) {
    currentAudio.pause();
    currentAudio = null;
  }
  
  // Create new audio
  currentAudio = new Audio(streamUrl);
  currentPlayingId = id;
  
  // Setup progress tracking
  currentAudio.addEventListener('timeupdate', () => updateProgress(id));
  currentAudio.addEventListener('ended', () => {
    currentAudio = null;
    currentPlayingId = null;
  });
  
  currentAudio.play();
}

function updateProgress(id) {
  if (!currentAudio || currentPlayingId !== id) return;
  
  const percent = (currentAudio.currentTime / currentAudio.duration) * 100;
  const fill = document.getElementById(`progress-${id}`);
  const handle = document.getElementById(`handle-${id}`);
  
  if (fill) fill.style.width = `${percent}%`;
  if (handle) handle.style.left = `${percent}%`;
}

function seekAudio(event, id) {
  if (!currentAudio || currentPlayingId !== id) return;
  
  const bar = event.currentTarget;
  const rect = bar.getBoundingClientRect();
  const percent = (event.clientX - rect.left) / rect.width;
  
  currentAudio.currentTime = percent * currentAudio.duration;
}

// Start
init();
