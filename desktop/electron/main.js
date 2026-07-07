/**
 * desktop/electron/main.js
 *
 * Codeably Electron main process.
 * - Locates the frozen API binary (PyInstaller output) bundled as a resource
 * - Spawns it on 127.0.0.1:8765
 * - Polls until it responds, then opens the BrowserWindow
 * - Kills the child on quit
 *
 * Zero external dependencies at runtime — the frozen binary ships Python,
 * all pip packages, and the entire core/ + api/ tree inside it.
 */

const { app, BrowserWindow, shell, ipcMain } = require('electron');
const path  = require('path');
const http  = require('http');
const { spawn } = require('child_process');
const fs    = require('fs');

// ── Config ────────────────────────────────────────────────────────────────────
const API_HOST    = '127.0.0.1';
const API_PORT    = 8765;
const API_URL     = `http://${API_HOST}:${API_PORT}`;
const POLL_MS     = 250;
const TIMEOUT_MS  = 30_000;
const PROTOCOL    = 'codeably';   // codeably://auth?code=...

// Register as default handler for codeably:// deep links
// Must happen before app.whenReady() on Windows/Linux;
// on macOS the scheme is declared in Info.plist via electron-builder.yml
if (process.defaultApp) {
  // Dev mode: argv[1] is the app path
  app.setAsDefaultProtocolClient(PROTOCOL, process.execPath, [path.resolve(process.argv[1])]);
} else {
  app.setAsDefaultProtocolClient(PROTOCOL);
}

let apiProcess = null;
let mainWindow  = null;

// ── Locate bundled binary ─────────────────────────────────────────────────────
function apiBinaryPath() {
  // In a packaged app, extraResources land in process.resourcesPath/
  // In dev (npm run dev), fall back to the repo root so you can run
  //   the Python process manually with `python api/main.py`
  const binaryName = process.platform === 'win32' ? 'codeably-api.exe' : 'codeably-api';

  // Packaged
  const packed = path.join(process.resourcesPath || '', binaryName);
  if (fs.existsSync(packed)) return packed;

  // Dev fallback — return null so we skip spawning and let dev run it manually
  return null;
}

// ── Spawn API ─────────────────────────────────────────────────────────────────
function spawnApi() {
  const bin = apiBinaryPath();
  if (!bin) {
    console.log('[codeably] Dev mode — start API manually: python api/main.py');
    return;
  }

  console.log('[codeably] Spawning API binary:', bin);
  apiProcess = spawn(bin, [], {
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env },
  });

  apiProcess.stdout.on('data', d => process.stdout.write('[api] ' + d));
  apiProcess.stderr.on('data', d => process.stderr.write('[api] ' + d));

  apiProcess.on('exit', code => {
    console.log(`[codeably] API process exited with code ${code}`);
    apiProcess = null;
  });
}

// ── Poll until API is up ──────────────────────────────────────────────────────
function waitForApi(timeoutMs) {
  return new Promise((resolve, reject) => {
    const start    = Date.now();
    const interval = setInterval(() => {
      http.get(`${API_URL}/health`, res => {
        if (res.statusCode === 200) {
          clearInterval(interval);
          resolve();
        }
      }).on('error', () => {
        if (Date.now() - start > timeoutMs) {
          clearInterval(interval);
          reject(new Error('API did not start in time'));
        }
      });
    }, POLL_MS);
  });
}

// ── Create window ─────────────────────────────────────────────────────────────
function createWindow() {
  mainWindow = new BrowserWindow({
    width:          1280,
    height:         800,
    minWidth:       900,
    minHeight:      600,
    backgroundColor: '#0a0a0a',
    titleBarStyle:  'hiddenInset',  // macOS traffic lights inset
    frame:          process.platform !== 'darwin', // frameless on mac, native on win/linux
    show:           false, // show after ready-to-show to avoid flash
    webPreferences: {
      preload:            path.join(__dirname, 'preload.js'),
      contextIsolation:   true,
      nodeIntegration:    false,
      webSecurity:        true,
    },
    icon: path.join(__dirname, '..', 'icons', 'icon.png'),
  });

  mainWindow.loadFile(path.join(__dirname, '..', 'ui', 'index.html'));

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
  });

  // Open external links in the system browser, not in Electron
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  mainWindow.on('closed', () => { mainWindow = null; });
}

// ── IPC: open external link safely ───────────────────────────────────────────
ipcMain.on('open-external', (_, url) => {
  if (url && (url.startsWith('https://') || url.startsWith('http://'))) {
    shell.openExternal(url);
  }
});

// ── IPC: get API base URL ─────────────────────────────────────────────────────
ipcMain.handle('get-api-base', () => API_URL);

// ── Deep link handler — called when Google redirects to codeably://auth ───────
// macOS: open-url fires while app is running
// Windows/Linux: second instance is launched with the URL as an argv
async function handleDeepLink(url) {
  if (!url || !url.startsWith(`${PROTOCOL}://`)) return;

  // The backend already handled the callback at /auth/google/callback
  // (Google redirects to http://127.0.0.1:8765/auth/google/callback, not the
  //  deep link — so status polling in the UI is the primary path).
  // This handler fires only if you use codeably:// as the redirect URI instead.
  // Either way, we notify the renderer to check /auth/google/status.
  if (mainWindow) {
    mainWindow.focus();
    try {
      const res  = await fetch(`${API_URL}/auth/google/status`);
      const data = await res.json();
      if (data.user) {
        mainWindow.webContents.send('oauth-success', data.user);
      }
    } catch (_) {}
  }
}

// macOS
app.on('open-url', (event, url) => {
  event.preventDefault();
  handleDeepLink(url);
});

// Windows / Linux — second instance
app.on('second-instance', (_event, argv) => {
  const url = argv.find(a => a.startsWith(`${PROTOCOL}://`));
  if (url) handleDeepLink(url);
  if (mainWindow) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  }
});

// Single-instance lock (Windows/Linux deep links need this)
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) app.quit();

// ── App lifecycle ─────────────────────────────────────────────────────────────
app.whenReady().then(async () => {
  spawnApi();

  try {
    await waitForApi(TIMEOUT_MS);
    console.log('[codeably] API is ready.');
  } catch (err) {
    console.error('[codeably]', err.message);
    // Still open the window — the UI handles disconnected state gracefully
  }

  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('quit', () => {
  if (apiProcess) {
    console.log('[codeably] Killing API process…');
    apiProcess.kill();
    apiProcess = null;
  }
});

// Security: prevent new window creation
app.on('web-contents-created', (_, contents) => {
  contents.on('will-navigate', (event, url) => {
    // allow navigation within the local file and localhost API only
    if (!url.startsWith('file://') && !url.startsWith(API_URL)) {
      event.preventDefault();
      shell.openExternal(url);
    }
  });
});
