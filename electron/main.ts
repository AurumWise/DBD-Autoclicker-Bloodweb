import { app, BrowserWindow, ipcMain, shell } from "electron";
import { execFile, spawn, ChildProcessWithoutNullStreams } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";
import * as readline from "node:readline";

const SOCIAL_TG_URL = "https://t.me/AurumWise";
const SOCIAL_VK_URL = "https://vk.com/aurumwise";
const SOCIAL_YT_URL = "https://www.youtube.com/@AurumWise";
const ALLOWED_EXTERNAL_URLS = new Set([SOCIAL_TG_URL, SOCIAL_VK_URL, SOCIAL_YT_URL]);

type PendingRequest = {
  resolve: (value: unknown) => void;
  reject: (reason?: unknown) => void;
};

let mainWindow: BrowserWindow | null = null;
let backend: ChildProcessWithoutNullStreams | null = null;
let nextRequestId = 1;
const pending = new Map<number, PendingRequest>();
let latestState: Record<string, unknown> | null = null;
let stoppingBackend = false;
let quitting = false;
let zOrderInterval: NodeJS.Timeout | null = null;

function projectRoot(): string {
  return path.resolve(__dirname, "..", "..");
}

function pythonExecutable(): string {
  const root = projectRoot();
  if (process.platform === "win32") {
    return path.join(root, ".venv", "Scripts", "python.exe");
  }
  return path.join(root, ".venv", "bin", "python");
}

function packagedBackendExecutable(): string {
  return process.platform === "win32"
    ? path.join(projectRoot(), "backend", "electron_backend.exe")
    : path.join(projectRoot(), "backend", "electron_backend");
}

function backendCommand(): { command: string; args: string[] } {
  const packagedBackend = packagedBackendExecutable();
  if (fs.existsSync(packagedBackend)) {
    return { command: packagedBackend, args: [] };
  }
  return { command: pythonExecutable(), args: ["-u", "-m", "app.electron_backend"] };
}

function startBackend(): void {
  if (backend) {
    return;
  }

  const backendLaunch = backendCommand();
  backend = spawn(backendLaunch.command, backendLaunch.args, {
    cwd: projectRoot(),
    stdio: ["pipe", "pipe", "pipe"],
    windowsHide: true
  });

  const stdout = readline.createInterface({ input: backend.stdout });
  stdout.on("line", (line) => {
    try {
      const message = JSON.parse(line);
      if (message.type === "response") {
        const request = pending.get(message.id);
        if (request) {
          pending.delete(message.id);
          if (message.ok) {
            if (message.result && typeof message.result === "object") {
              latestState = message.result;
              mainWindow?.webContents.send("backend:state", latestState);
              applyWindowZOrder(latestState);
            }
            request.resolve(message.result);
          } else {
            if (message.state) {
              latestState = message.state;
              mainWindow?.webContents.send("backend:state", latestState);
              applyWindowZOrder(latestState);
            }
            request.reject(new Error(message.error || "Python backend error"));
          }
        }
        return;
      }
      if (message.type === "state") {
        latestState = message.state;
        mainWindow?.webContents.send("backend:state", latestState);
        applyWindowZOrder(latestState);
      }
      if (message.type === "error") {
        mainWindow?.webContents.send("backend:error", message.error);
      }
    } catch (error) {
      mainWindow?.webContents.send("backend:error", `Bad backend message: ${String(error)}`);
    }
  });

  backend.stderr.on("data", (chunk) => {
    console.error(chunk.toString("utf8"));
  });

  backend.on("exit", (code) => {
    backend = null;
    if (stoppingBackend) {
      stoppingBackend = false;
      return;
    }
    for (const request of pending.values()) {
      request.reject(new Error(`Python backend exited with code ${code}`));
    }
    pending.clear();
    mainWindow?.webContents.send("backend:error", `Python backend exited with code ${code}`);
  });
}

function shouldForceTopmost(state: Record<string, unknown> | null): boolean {
  if (!state) {
    return false;
  }
  const center = state.center as Record<string, unknown> | undefined;
  return Boolean(
    state.always_on_top ||
    state.grid_visible ||
    state.adding_capture ||
    state.is_running ||
    center?.setup_active
  );
}

function applyWindowZOrder(state: Record<string, unknown> | null = latestState): void {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }
  const forceTopmost = shouldForceTopmost(state);
  mainWindow.setAlwaysOnTop(forceTopmost, "screen-saver");
  if (forceTopmost && !mainWindow.isMinimized()) {
    mainWindow.moveTop();
  }
}

function startZOrderWatchdog(): void {
  if (zOrderInterval) {
    return;
  }
  zOrderInterval = setInterval(() => {
    if (shouldForceTopmost(latestState)) {
      applyWindowZOrder(latestState);
    }
  }, 1200);
}

function forceKillBackend(processToKill: ChildProcessWithoutNullStreams): void {
  const pid = processToKill.pid;
  if (process.platform === "win32" && pid) {
    execFile("taskkill", ["/PID", String(pid), "/T", "/F"], { windowsHide: true }, () => undefined);
    return;
  }
  processToKill.kill();
}

function stopBackend(): Promise<void> {
  if (!backend) {
    return Promise.resolve();
  }
  stoppingBackend = true;
  const processToStop = backend;

  return new Promise((resolve) => {
    let finished = false;
    let timeout: NodeJS.Timeout | undefined;
    const finish = (): void => {
      if (finished) {
        return;
      }
      finished = true;
      if (timeout) {
        clearTimeout(timeout);
      }
      backend = null;
      resolve();
    };
    timeout = setTimeout(() => {
      forceKillBackend(processToStop);
      finish();
    }, 2500);

    processToStop.once("exit", finish);
    processToStop.once("error", finish);

    try {
      const id = nextRequestId++;
      const message = JSON.stringify({ id, command: "shutdown", payload: {} });
      processToStop.stdin.write(`${message}\n`, "utf8", () => {
        processToStop.stdin.end();
      });
    } catch {
      forceKillBackend(processToStop);
      finish();
    }
  });
}

function sendCommand(command: string, payload: Record<string, unknown> = {}): Promise<unknown> {
  startBackend();
  if (!backend) {
    return Promise.reject(new Error("Python backend is not running"));
  }

  const id = nextRequestId++;
  const message = JSON.stringify({ id, command, payload });
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    backend?.stdin.write(`${message}\n`, "utf8", (error) => {
      if (error) {
        pending.delete(id);
        reject(error);
      }
    });
  });
}

function sendWindowBounds(): void {
  if (!mainWindow) {
    return;
  }
  const bounds = mainWindow.getBounds();
  void sendCommand("updateWindowBounds", { x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height }).catch(() => undefined);
}

async function quitApplication(): Promise<void> {
  if (quitting) {
    return;
  }
  quitting = true;
  if (zOrderInterval) {
    clearInterval(zOrderInterval);
    zOrderInterval = null;
  }
  await stopBackend();
  app.quit();
}

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 520,
    height: 760,
    minWidth: 460,
    minHeight: 640,
    frame: false,
    resizable: true,
    show: false,
    backgroundColor: "#141615",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  });

  mainWindow.loadFile(path.join(__dirname, "..", "renderer", "index.html"));
  mainWindow.once("ready-to-show", async () => {
    try {
      const state = await sendCommand("getState");
      if (state && typeof state === "object" && "always_on_top" in state) {
        latestState = state as Record<string, unknown>;
        applyWindowZOrder(latestState);
      }
      sendWindowBounds();
      mainWindow?.show();
    } catch (error) {
      mainWindow?.webContents.send("backend:error", String(error));
      mainWindow?.show();
    }
  });

  mainWindow.on("close", (event) => {
    if (quitting) {
      return;
    }
    event.preventDefault();
    void quitApplication();
  });
  mainWindow.on("move", sendWindowBounds);
  mainWindow.on("resize", sendWindowBounds);
  mainWindow.on("show", () => applyWindowZOrder());
  mainWindow.on("restore", () => applyWindowZOrder());
  mainWindow.on("blur", () => {
    if (shouldForceTopmost(latestState)) {
      applyWindowZOrder();
    }
  });
  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

app.whenReady().then(() => {
  startBackend();
  createWindow();
  startZOrderWatchdog();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    void quitApplication();
  }
});

app.on("before-quit", () => {
  quitting = true;
  if (zOrderInterval) {
    clearInterval(zOrderInterval);
    zOrderInterval = null;
  }
  void stopBackend();
});

ipcMain.handle("app:command", async (_event, command: string, payload: Record<string, unknown>) => {
  const result = await sendCommand(command, payload || {});
  if (result && typeof result === "object") {
    latestState = result as Record<string, unknown>;
    applyWindowZOrder(latestState);
  }
  return result;
});

ipcMain.handle("window:minimize", () => {
  mainWindow?.minimize();
});

ipcMain.handle("window:close", () => {
  void quitApplication();
});

ipcMain.handle("window:setAlwaysOnTop", async (_event, value: boolean) => {
  const result = await sendCommand("setAlwaysOnTop", { value });
  if (result && typeof result === "object") {
    latestState = result as Record<string, unknown>;
    applyWindowZOrder(latestState);
  }
  return result;
});

ipcMain.handle("external:open", async (_event, key: "tg" | "vk" | "yt") => {
  const url = key === "tg" ? SOCIAL_TG_URL : key === "vk" ? SOCIAL_VK_URL : SOCIAL_YT_URL;
  if (!ALLOWED_EXTERNAL_URLS.has(url)) {
    throw new Error("URL is not allowed");
  }
  await shell.openExternal(url);
});
