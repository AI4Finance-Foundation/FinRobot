import { app, BrowserWindow, dialog } from 'electron'
import { ChildProcess, execFileSync, spawn } from 'child_process'
import * as fs from 'fs'
import * as path from 'path'
import * as http from 'http'

const SERVER_PORT = 8000
const SERVER_URL = `http://127.0.0.1:${SERVER_PORT}`
const HEALTH_URL = `${SERVER_URL}/health`

let serverProcess: ChildProcess | null = null

const LOADING_HTML = `data:text/html;charset=utf-8,${encodeURIComponent(`<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;background:#0f1117;color:#c9d1d9;display:flex;align-items:center;justify-content:center;height:100vh;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif">
  <div style="text-align:center">
    <h2 style="margin-bottom:8px">Starting FinAgent...</h2>
    <p style="color:#8b949e">Installing dependencies and starting server. This may take a moment on first launch.</p>
    <div style="margin-top:24px;width:200px;height:4px;background:#21262d;border-radius:2px;overflow:hidden;display:inline-block">
      <div style="width:30%;height:100%;background:#1f6feb;border-radius:2px;animation:loading 1.5s ease-in-out infinite"></div>
    </div>
  </div>
  <style>@keyframes loading{0%{transform:translateX(-100%)}50%{transform:translateX(200%)}100%{transform:translateX(-100%)}}</style>
</body>
</html>`)}`

function getUvPath(): string {
  if (app.isPackaged) {
    // Production: uv binary is in extraResources
    const name = process.platform === 'win32' ? 'uv.exe' : 'uv'
    return path.join(process.resourcesPath, name)
  }
  // Dev mode: use system uv
  return 'uv'
}

function getProjectRoot(): string {
  if (app.isPackaged) {
    // Production: pyproject.toml + finagent/ are in extraResources
    return process.resourcesPath
  }
  // Dev mode: the FinAgent project root (desktop/ is a subdirectory)
  return path.join(__dirname, '..', '..', '..')
}

function ensureDepsInstalled(uvBin: string, cwd: string): void {
  // In production, run `uv sync` on first launch to create the venv.
  // Subsequent launches skip this if .venv already exists.
  if (!app.isPackaged) return

  const venvPath = path.join(cwd, '.venv')
  if (fs.existsSync(venvPath)) return

  console.log('[main] First launch — installing Python dependencies...')
  try {
    execFileSync(uvBin, ['sync', '--frozen'], {
      cwd,
      stdio: 'inherit',
      timeout: 120_000,
    })
    console.log('[main] Dependencies installed')
  } catch (err) {
    console.error('[main] Failed to install dependencies:', (err as Error).message)
  }
}

function startServer(): ChildProcess {
  const uvBin = getUvPath()
  const cwd = getProjectRoot()

  ensureDepsInstalled(uvBin, cwd)

  const proc = spawn(uvBin, ['run', 'finagent', 'serve', '--port', SERVER_PORT.toString()], {
    cwd,
    stdio: ['ignore', 'pipe', 'pipe'],
  })

  proc.stdout?.on('data', (data: Buffer) => {
    console.log(`[server] ${data.toString().trimEnd()}`)
  })

  proc.stderr?.on('data', (data: Buffer) => {
    console.error(`[server] ${data.toString().trimEnd()}`)
  })

  proc.on('error', (err) => {
    console.error('[server] Failed to start:', err.message)
  })

  proc.on('exit', (code) => {
    console.log(`[server] Exited with code ${code}`)
    serverProcess = null
  })

  return proc
}

function waitForServer(timeoutMs = 120_000): Promise<void> {
  const start = Date.now()
  return new Promise((resolve, reject) => {
    const check = (): void => {
      if (Date.now() - start > timeoutMs) {
        reject(new Error(`Server did not start within ${timeoutMs / 1000}s`))
        return
      }
      http
        .get(HEALTH_URL, (res) => {
          if (res.statusCode === 200) {
            resolve()
          } else {
            setTimeout(check, 500)
          }
        })
        .on('error', () => {
          setTimeout(check, 500)
        })
    }
    check()
  })
}

function createWindow(): BrowserWindow {
  const win = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 800,
    minHeight: 600,
    title: 'FinAgent',
    webPreferences: {
      preload: path.join(__dirname, '..', 'preload', 'index.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  return win
}

function loadApp(win: BrowserWindow): void {
  if (process.env.ELECTRON_RENDERER_URL) {
    // Dev mode: electron-vite dev server
    win.loadURL(process.env.ELECTRON_RENDERER_URL)
  } else {
    // Production: built files
    win.loadFile(path.join(__dirname, '..', 'renderer', 'index.html'))
  }
}

app.whenReady().then(async () => {
  serverProcess = startServer()

  const win = createWindow()

  // Show loading screen immediately so user doesn't see a white screen
  win.loadURL(LOADING_HTML)

  try {
    await waitForServer()
    console.log('[main] Server is ready')
    loadApp(win)
  } catch (err) {
    console.error('[main]', (err as Error).message)
    dialog.showErrorBox(
      'FinAgent',
      'Failed to start the FinAgent server.\n\n'
        + 'Please check that Python and uv are installed correctly.\n'
        + `Error: ${(err as Error).message}`,
    )
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      const newWin = createWindow()
      loadApp(newWin)
    }
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('will-quit', () => {
  if (serverProcess) {
    serverProcess.kill()
    serverProcess = null
  }
})
