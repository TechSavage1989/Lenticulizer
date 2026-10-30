(() => {
  'use strict';
  const webview = window.chrome && window.chrome.webview;
  if (!webview) return;
  const pending = new Map();
  const listeners = new Map();
  let serial = 0;
  let projectPath = '';
  let bufferedProject = null;
  const assetUrl = (path, revision = '') => path ? `https://lenticulizer.app/local-image?path=${encodeURIComponent(path)}&v=${encodeURIComponent(revision)}` : '';

  function invoke(method, args = {}, files = null) {
    const id = ++serial;
    return new Promise((resolve, reject) => {
      // Dialogs can remain open while the user chooses a file. Do not time them out.
      pending.set(id, { resolve, reject });
      try {
        const message = { id, method, args, projectPath };
        if (files) {
          if (!webview.postMessageWithAdditionalObjects) throw new Error('Update Microsoft Edge WebView2 Runtime to enable file dropping. Add source images remains available.');
          webview.postMessageWithAdditionalObjects(message, files);
        } else webview.postMessage(message);
      } catch (error) { pending.delete(id); reject(error); }
    });
  }
  webview.addEventListener('message', event => {
    const message = event.data;
    if (!message || typeof message !== 'object') return;
    if (message.event) {
      if (message.event === 'project-updated' && message.data.active_project_path) projectPath = message.data.active_project_path;
      if (message.event === 'project-updated' && !(listeners.get(message.event) || new Set()).size) bufferedProject = message.data;
      for (const callback of listeners.get(message.event) || []) callback(message.data);
      return;
    }
    const request = pending.get(message.id);
    if (!request) return;
    pending.delete(message.id);
    if (message.error) request.reject(new Error(message.error));
    else request.resolve(message.result);
  });
  function on(name, callback) {
    if (!listeners.has(name)) listeners.set(name, new Set());
    listeners.get(name).add(callback);
    if (name === 'project-updated' && bufferedProject) {
      const value = bufferedProject; bufferedProject = null;
      queueMicrotask(() => callback(value));
    }
    return () => listeners.get(name).delete(callback);
  }
  window.addEventListener('pagehide', () => {
    for (const request of pending.values()) request.reject(new Error('The interface was closed.'));
    pending.clear();
  });
  window.lenticulizer = Object.freeze({
    bootstrap: async () => { const result = await invoke('bootstrap'); projectPath = result.projectPath; return result; },
    startBackend: () => invoke('processing:status'),
    backendStatus: () => invoke('processing:status'),
    runtimeNotices: () => invoke('runtime:notices'),
    updateStatus: () => invoke('update:status'),
    checkForUpdates: () => invoke('update:check'),
    downloadUpdate: () => invoke('update:download'),
    installUpdate: () => invoke('update:install'),
    openUpdateRelease: () => invoke('update:open-release'),
    solveSettings: patch => invoke('settings:solve', { patch }),
    patchProject: (patch, priority) => invoke('project:patch', { patch, priority }),
    readProject: () => invoke('project:read'),
    addImages: () => invoke('images:add'),
    importInterlaced: () => invoke('images:import'),
    importHeightmap: () => invoke('heightmap:import'),
    analyzeHeightmap: () => invoke('heightmap:analyze'),
    getDroppedImages: files => invoke('images:dropped', {}, files),
    importDroppedFiles: (files, target = 'auto') => invoke('files:import', { target }, files),
    assetUrl,
    showPath: path => invoke('path:show', { path }),
    openPath: path => invoke('path:open', { path }),
    exportAsset: kind => invoke('asset:export', { kind }),
    exportBothAssets: () => invoke('asset:export-both'),
    onProjectUpdated: callback => on('project-updated', callback),
    onBackendStatus: callback => on('processing-status', callback),
    onUpdateStatus: callback => on('update-status', callback)
  });
})();
