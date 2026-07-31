import path from "node:path";
import type {
  BrowserWindow,
  BrowserWindowConstructorOptions
} from "electron";
import { APP_ORIGIN } from "./protocol";

export function createWindowOptions(
  preloadPath: string,
  production: boolean
): BrowserWindowConstructorOptions {
  if (!path.isAbsolute(preloadPath)) {
    throw new TypeError("Preload path must be absolute");
  }

  return {
    width: 1280,
    height: 820,
    minWidth: 960,
    minHeight: 640,
    show: false,
    backgroundColor: "#111827",
    webPreferences: {
      preload: preloadPath,
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true,
      webviewTag: false,
      devTools: !production
    }
  };
}

export async function createMainWindow(
  BrowserWindowClass: typeof BrowserWindow,
  preloadPath: string,
  production: boolean
): Promise<BrowserWindow> {
  const window = new BrowserWindowClass(
    createWindowOptions(preloadPath, production)
  );
  window.once("ready-to-show", () => window.show());
  await window.loadURL(`${APP_ORIGIN}/`);
  return window;
}
