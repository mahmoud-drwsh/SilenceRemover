// Main Application - Compact 3-Row Layout

let allFiles = [];
let currentView = 'notready';
let saveTimeout;
let currentAudio = null;
let currentPlayingId = null;

// Initialize
async function init() {
  const params = new URLSearchParams(location.search);
  currentView = params.get('view') || 'notready';
  
  await loadFiles();
  
  window.addEventListener('popstate', () => {
    const params = new URLSearchParams(location.search);
    currentView = params.get('view') || 'notready';
    window.CONFIG.lang = params.get('lang') || window.CONFIG.lang;
    loadFiles(); // Reload to get fresh state
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
  
  // Update title display immediately
  const display = document.getElementById(`display-${id}`);
  if (display) {
    display.textContent = textarea.value || getText('untitled');
  }
  
  // Debounced save
  clearTimeout(saveTimeout);
  saveTimeout = setTimeout(async () => {
    try {
      showSpinner(id, true);
      await API.updateTitle(id, textarea.value);
      
      // Update local cache
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
    
    // Re-render to show updated icon and border
    render();
  } catch (err) {
    console.error('Failed to toggle ready:', err);
  }
}

// Move to trash
async function moveToTrash(id) {
  try {
    await API.moveToTrash(id);
    
    // Remove from local cache
    const file = allFiles.find(f => f.id === id);
    if (file) file.trashed = true;
    
    // Re-render
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

// Audio playback
function togglePlay(id, event) {
  event?.stopPropagation();
  
  // If clicking currently playing, toggle pause
  if (currentPlayingId === id && currentAudio) {
    if (currentAudio.paused) {
      currentAudio.play();
      updatePlayButton(id, true);
    } else {
      currentAudio.pause();
      updatePlayButton(id, false);
    }
    return;
  }
  
  // Stop previous audio
  if (currentAudio) {
    currentAudio.pause();
    currentAudio = null;
    updatePlayButton(currentPlayingId, false);
    resetProgress(currentPlayingId);
  }
  
  // Start new audio
  currentAudio = new Audio(API.getStreamUrl(id));
  currentPlayingId = id;
  
  currentAudio.addEventListener('timeupdate', () => updateProgress(id));
  currentAudio.addEventListener('ended', () => {
    updatePlayButton(id, false);
    resetProgress(id);
    currentAudio = null;
    currentPlayingId = null;
  });
  
  currentAudio.addEventListener('error', () => {
    console.error('Audio error');
    updatePlayButton(id, false);
  });
  
  currentAudio.play();
  updatePlayButton(id, true);
}

function updatePlayButton(id, isPlaying) {
  const btn = document.getElementById(`play-${id}`);
  if (btn) {
    btn.textContent = isPlaying ? '▮▮' : '▶';
    btn.classList.toggle('playing', isPlaying);
  }
}

function updateProgress(id) {
  if (!currentAudio || currentPlayingId !== id) return;
  
  const percent = (currentAudio.currentTime / currentAudio.duration) * 100;
  const fill = document.getElementById(`fill-${id}`);
  const handle = document.getElementById(`handle-${id}`);
  
  if (fill) fill.style.width = `${percent}%`;
  if (handle) handle.style.left = `${percent}%`;
}

function resetProgress(id) {
  const fill = document.getElementById(`fill-${id}`);
  const handle = document.getElementById(`handle-${id}`);
  if (fill) fill.style.width = '0%';
  if (handle) handle.style.left = '0%';
}

function seekAudio(event, id) {
  if (!currentAudio || currentPlayingId !== id) {
    // Start playing if not playing
    togglePlay(id, null);
    // Wait a moment for audio to load, then seek
    setTimeout(() => doSeek(event, id), 100);
    return;
  }
  
  doSeek(event, id);
}

function doSeek(event, id) {
  if (!currentAudio) return;
  
  const container = event.currentTarget;
  const rect = container.getBoundingClientRect();
  const percent = Math.max(0, Math.min(100, ((event.clientX - rect.left) / rect.width) * 100));
  
  currentAudio.currentTime = (percent / 100) * currentAudio.duration;
  updateProgress(id);
}

// Handle drag on progress bar
let isDragging = false;

document.addEventListener('mousedown', (e) => {
  if (e.target.classList.contains('progress-handle')) {
    isDragging = true;
    e.preventDefault();
  }
});

document.addEventListener('mousemove', (e) => {
  if (!isDragging || !currentAudio) return;
  
  const container = document.querySelector(`#file-${currentPlayingId} .progress-container`);
  if (!container) return;
  
  const rect = container.getBoundingClientRect();
  const percent = Math.max(0, Math.min(100, ((e.clientX - rect.left) / rect.width) * 100));
  
  currentAudio.currentTime = (percent / 100) * currentAudio.duration;
  updateProgress(currentPlayingId);
});

document.addEventListener('mouseup', () => {
  isDragging = false;
});

// Start
init();
