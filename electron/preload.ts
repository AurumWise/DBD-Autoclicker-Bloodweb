import { contextBridge, ipcRenderer } from "electron";

type StateHandler = (state: unknown) => void;
type ErrorHandler = (message: string) => void;

contextBridge.exposeInMainWorld("bloodweb", {
  command(command: string, payload: Record<string, unknown> = {}) {
    return ipcRenderer.invoke("app:command", command, payload);
  },
  setAlwaysOnTop(value: boolean) {
    return ipcRenderer.invoke("window:setAlwaysOnTop", value);
  },
  minimize() {
    return ipcRenderer.invoke("window:minimize");
  },
  close() {
    return ipcRenderer.invoke("window:close");
  },
  openExternal(key: "tg" | "vk" | "yt") {
    return ipcRenderer.invoke("external:open", key);
  },
  onState(handler: StateHandler) {
    const listener = (_event: Electron.IpcRendererEvent, state: unknown) => handler(state);
    ipcRenderer.on("backend:state", listener);
    return () => ipcRenderer.removeListener("backend:state", listener);
  },
  onError(handler: ErrorHandler) {
    const listener = (_event: Electron.IpcRendererEvent, message: string) => handler(message);
    ipcRenderer.on("backend:error", listener);
    return () => ipcRenderer.removeListener("backend:error", listener);
  }
});
