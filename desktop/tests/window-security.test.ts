import type { App, Session, WebContents } from "electron";
import { describe, expect, it, vi } from "vitest";
import {
  enableApplicationSandbox,
  hardenWebContents,
  installAppSecurity,
  installSessionSecurity,
  shouldAllowNavigation
} from "../src/main/security";
import { createWindowOptions } from "../src/main/window";

describe("BrowserWindow and session security", () => {
  it("enables the app-wide sandbox before windows are created", () => {
    const application = { enableSandbox: vi.fn() };
    enableApplicationSandbox(application);
    expect(application.enableSandbox).toHaveBeenCalledOnce();
  });

  it("uses the fixed sandboxed production window options", () => {
    const options = createWindowOptions("/absolute/preload.cjs", true);
    expect(options.webPreferences).toMatchObject({
      preload: "/absolute/preload.cjs",
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true,
      webviewTag: false,
      devTools: false
    });
    expect(() => createWindowOptions("relative.cjs", true)).toThrow();
  });

  it("denies navigation, redirects, webviews and window.open", () => {
    const handlers = new Map<string, (...args: any[]) => void>();
    const contents = {
      setWindowOpenHandler: vi.fn(),
      on: vi.fn((name: string, handler: (...args: any[]) => void) => {
        handlers.set(name, handler);
      })
    } as unknown as WebContents;

    hardenWebContents(contents);
    expect(shouldAllowNavigation()).toBe(false);
    expect(contents.setWindowOpenHandler).toHaveBeenCalledOnce();
    expect(
      (contents.setWindowOpenHandler as ReturnType<typeof vi.fn>).mock.calls[0]?.[0]()
    ).toEqual({ action: "deny" });

    for (const name of ["will-navigate", "will-redirect", "will-attach-webview"]) {
      const preventDefault = vi.fn();
      handlers.get(name)?.({ preventDefault });
      expect(preventDefault).toHaveBeenCalledOnce();
    }
  });

  it("installs fail-closed permission, media, device, download and picker handlers", () => {
    const eventHandlers = new Map<string, (...args: any[]) => void>();
    const permissionCheck = vi.fn();
    const permissionRequest = vi.fn();
    const devicePermission = vi.fn();
    const displayMedia = vi.fn();
    const electronSession = {
      setPermissionCheckHandler: vi.fn((handler) => permissionCheck.mockImplementation(handler)),
      setPermissionRequestHandler: vi.fn((handler) =>
        permissionRequest.mockImplementation(handler)
      ),
      setDevicePermissionHandler: vi.fn((handler) =>
        devicePermission.mockImplementation(handler)
      ),
      setDisplayMediaRequestHandler: vi.fn((handler) =>
        displayMedia.mockImplementation(handler)
      ),
      on: vi.fn((name: string, handler: (...args: any[]) => void) => {
        eventHandlers.set(name, handler);
      })
    } as unknown as Session;

    installSessionSecurity(electronSession);
    expect(permissionCheck()).toBe(false);
    const permissionCallback = vi.fn();
    permissionRequest(undefined, "camera", permissionCallback);
    expect(permissionCallback).toHaveBeenCalledWith(false);
    expect(devicePermission()).toBe(false);
    const mediaCallback = vi.fn();
    displayMedia({}, mediaCallback);
    expect(mediaCallback).toHaveBeenCalledWith({});

    const downloadEvent = { preventDefault: vi.fn() };
    const item = { cancel: vi.fn() };
    eventHandlers.get("will-download")?.(downloadEvent, item);
    expect(downloadEvent.preventDefault).toHaveBeenCalledOnce();
    expect(item.cancel).toHaveBeenCalledOnce();

    for (const eventName of [
      "select-serial-port",
      "select-hid-device",
      "select-usb-device"
    ]) {
      const event = { preventDefault: vi.fn() };
      const callback = vi.fn();
      if (eventName === "select-serial-port") {
        eventHandlers.get(eventName)?.(event, [], undefined, callback);
      } else {
        eventHandlers.get(eventName)?.(event, {}, callback);
      }
      expect(event.preventDefault).toHaveBeenCalledOnce();
      expect(callback).toHaveBeenCalledWith("");
    }
  });

  it("denies certificate exceptions at the app boundary", () => {
    const handlers = new Map<string, (...args: any[]) => void>();
    const app = {
      on: vi.fn((name: string, handler: (...args: any[]) => void) => {
        handlers.set(name, handler);
      })
    } as unknown as App;
    installAppSecurity(app);

    const event = { preventDefault: vi.fn() };
    const callback = vi.fn();
    handlers.get("certificate-error")?.(
      event,
      undefined,
      "https://invalid",
      "certificate-error",
      {},
      callback
    );
    expect(event.preventDefault).toHaveBeenCalledOnce();
    expect(callback).toHaveBeenCalledWith(false);
  });
});
