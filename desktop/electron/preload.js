/**
 * desktop/electron/preload.js
 *
 * Runs in the renderer context with Node access.
 * Exposes a minimal, safe API to the UI via contextBridge.
 */

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  /** Open a URL in the system browser */
  openExternal: (url) => ipcRenderer.send('open-external', url),

  /** Get the API base URL from the main process */
  getApiBase: () => ipcRenderer.invoke('get-api-base'),

  /** Register a callback for when Google OAuth completes */
  onOAuthSuccess: (cb) => ipcRenderer.on('oauth-success', cb),

  /** Are we running inside Electron? */
  isElectron: true,
});
