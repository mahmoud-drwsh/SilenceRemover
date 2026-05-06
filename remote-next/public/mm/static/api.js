// API client for MP3 Manager
const API = {
  base() {
    return `/${window.CONFIG.token}/${window.CONFIG.project}`;
  },
  
  async getFiles() {
    const res = await fetch(`${this.base()}/api/files`);
    if (!res.ok) throw new Error('Failed to fetch files');
    return res.json();
  },
  
  async updateTitle(id, title) {
    const form = new FormData();
    form.append('title', title);
    const res = await fetch(`${this.base()}/api/update/${id}`, {
      method: 'POST',
      body: form
    });
    if (!res.ok) throw new Error('Failed to update title');
    return res.json();
  },
  
  async toggleReady(id, ready) {
    const res = await fetch(`${this.base()}/api/toggle-ready/${id}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ready })
    });
    if (!res.ok) throw new Error('Failed to toggle ready');
    return res.json();
  },
  
  async moveToTrash(id) {
    const res = await fetch(`${this.base()}/api/trash/${id}`, {
      method: 'POST'
    });
    if (!res.ok) throw new Error('Failed to move to trash');
    return res.json();
  },
  
  async restore(id) {
    const res = await fetch(`${this.base()}/api/restore/${id}`, {
      method: 'POST'
    });
    if (!res.ok) throw new Error('Failed to restore');
    return res.json();
  },
  
  async deletePermanent(id) {
    const res = await fetch(`${this.base()}/api/delete/${id}`, {
      method: 'POST'
    });
    if (!res.ok) throw new Error('Failed to delete');
    return res.json();
  },
  
  getStreamUrl(id) {
    return `${this.base()}/stream/${id}`;
  }
};
