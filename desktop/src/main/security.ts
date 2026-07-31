import type {
  App,
  DownloadItem,
  Event,
  Session,
  WebContents
} from "electron";

export function shouldAllowNavigation(): false {
  return false;
}

export function enableApplicationSandbox(
  application: Pick<App, "enableSandbox">
): void {
  application.enableSandbox();
}

export function hardenWebContents(contents: WebContents): void {
  contents.setWindowOpenHandler(() => ({ action: "deny" }));
  contents.on("will-navigate", (event) => {
    if (!shouldAllowNavigation()) {
      event.preventDefault();
    }
  });
  contents.on("will-redirect", (event) => event.preventDefault());
  contents.on("will-attach-webview", (event) => event.preventDefault());
}

export function installSessionSecurity(electronSession: Session): void {
  electronSession.setPermissionCheckHandler(() => false);
  electronSession.setPermissionRequestHandler(
    (_webContents, _permission, callback) => callback(false)
  );
  electronSession.setDevicePermissionHandler(() => false);
  electronSession.setDisplayMediaRequestHandler((_request, callback) => {
    callback({});
  });
  electronSession.on(
    "will-download",
    (event: Event, item: DownloadItem) => {
      event.preventDefault();
      item.cancel();
    }
  );
  electronSession.on(
    "select-serial-port",
    (event, _portList, _webContents, callback) => {
      event.preventDefault();
      callback("");
    }
  );
  electronSession.on(
    "select-hid-device",
    (event, _details, callback) => {
      event.preventDefault();
      callback("");
    }
  );
  electronSession.on(
    "select-usb-device",
    (event, _details, callback) => {
      event.preventDefault();
      callback("");
    }
  );
}

export function installAppSecurity(app: App): void {
  app.on("web-contents-created", (_event, contents) => {
    hardenWebContents(contents);
  });
  app.on(
    "certificate-error",
    (event, _webContents, _url, _error, _certificate, callback) => {
      event.preventDefault();
      callback(false);
    }
  );
}
