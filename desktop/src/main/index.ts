import { lstat, mkdir, chmod } from "node:fs/promises";
import path from "node:path";
import {
  app,
  BrowserWindow,
  ipcMain,
  protocol,
  session
} from "electron";
import { IPC_CHANNELS } from "../contracts";
import { ApiProxy } from "./apiProxy";
import { registerIpcHandlers } from "./ipc";
import {
  APP_SCHEME,
  installStaticProtocol,
  registerPrivilegedScheme
} from "./protocol";
import {
  enableApplicationSandbox,
  installAppSecurity,
  installSessionSecurity
} from "./security";
import {
  resolveQmdRuntimeConfiguration,
  QmdSupervisor,
  type QmdRuntimeConfiguration
} from "./qmdSupervisor";
import { RetrievalBroker } from "./retrievalBroker";
import {
  resolveSidecarExecutable,
  SidecarSupervisor
} from "./sidecar";
import { createMainWindow } from "./window";

const PRODUCT_NAME = "Local Context Forge";
const REQUIRED_SIDECAR_CAPABILITIES = [
  "desktop-handshake",
  "health",
  "library-api",
  "desktop-retrieval-v1"
] as const;

registerPrivilegedScheme(
  protocol.registerSchemesAsPrivileged.bind(protocol)
);
enableApplicationSandbox(app);

app.setName(PRODUCT_NAME);
const dataDir = path.join(app.getPath("appData"), PRODUCT_NAME);
app.setPath("userData", dataDir);

let mainWindow: BrowserWindow | undefined;
let quitting = false;

function configuredRendererRoot(): string {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, "renderer");
  }
  const configured = process.env.LCF_RENDERER_DIR;
  if (configured && path.isAbsolute(configured)) {
    return path.normalize(configured);
  }
  return path.resolve(__dirname, "../../resources/renderer");
}

function configuredSidecarExecutable(): string {
  try {
    return resolveSidecarExecutable({
      packaged: app.isPackaged,
      resourcesPath: process.resourcesPath,
      environment: process.env
    });
  } catch {
    // An absolute, deliberately nonexistent path lets the supervisor expose a
    // stable "configuration" state without discovering a system executable.
    return path.join(dataDir, ".sidecar-not-configured");
  }
}

async function configuredQmdRuntime(): Promise<QmdRuntimeConfiguration> {
  try {
    return await resolveQmdRuntimeConfiguration({
      packaged: app.isPackaged,
      resourcesPath: process.resourcesPath,
      environment: process.env
    });
  } catch {
    // Preserve lexical fallback without discovering a system Node/QMD. The
    // supervisor will fail this fixed, nonexistent configuration closed.
    return {
      nodeExecutable: path.join(dataDir, ".qmd-not-configured", "node"),
      workerEntry: path.join(dataDir, ".qmd-not-configured", "index.mjs"),
      buildManifestSha256: "0".repeat(64)
    };
  }
}

async function prepareDataDirectory(): Promise<void> {
  await mkdir(dataDir, { recursive: true, mode: 0o700 });
  const info = await lstat(dataDir);
  const uid =
    process.geteuid?.() ?? process.getuid?.() ?? -1;
  if (!info.isDirectory() || info.isSymbolicLink() || info.uid !== uid) {
    throw new Error("Desktop data directory is not private");
  }
  await chmod(dataDir, 0o700);
}

async function bootstrap(): Promise<void> {
  await prepareDataDirectory();
  installAppSecurity(app);
  installSessionSecurity(session.defaultSession);
  await installStaticProtocol(protocol, configuredRendererRoot());

  const qmdSupervisor = new QmdSupervisor({
    runtime: await configuredQmdRuntime(),
    appDataDir: dataDir,
    dataDir: path.join(dataDir, "qmd", "worker"),
    wikiRoot: path.join(dataDir, "wiki")
  });
  const retrievalBroker = new RetrievalBroker(
    qmdSupervisor,
    path.join(dataDir, "wiki")
  );
  const supervisor = new SidecarSupervisor({
    executablePath: configuredSidecarExecutable(),
    dataDir,
    appVersion: app.getVersion(),
    sidecarVersion: app.getVersion(),
    schemaVersion: 4,
    requiredCapabilities: REQUIRED_SIDECAR_CAPABILITIES,
    retrievalBroker
  });
  const apiProxy = new ApiProxy(8);

  registerIpcHandlers(ipcMain, {
    apiRequest: (input) =>
      apiProxy.request(input, supervisor.getConnection()),
    runtimeGet: () => supervisor.getStatus(),
    runtimeRetry: () => supervisor.retry(),
    appVersion: () => app.getVersion()
  });

  supervisor.subscribe((status) => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send(IPC_CHANNELS.runtimeChanged, status);
    }
  });

  const openMainWindow = async (): Promise<void> => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      return;
    }
    const preloadPath = path.resolve(__dirname, "../preload/index.cjs");
    mainWindow = await createMainWindow(
      BrowserWindow,
      preloadPath,
      app.isPackaged
    );
    mainWindow.on("closed", () => {
      mainWindow = undefined;
    });
  };

  app.on("second-instance", () => {
    if (!mainWindow || mainWindow.isDestroyed()) {
      return;
    }
    if (mainWindow.isMinimized()) {
      mainWindow.restore();
    }
    mainWindow.focus();
  });
  app.on("activate", () => {
    void openMainWindow();
  });
  app.on("window-all-closed", () => app.quit());
  app.on("before-quit", (event) => {
    if (quitting) {
      return;
    }
    event.preventDefault();
    void supervisor
      .shutdown()
      .catch(() => undefined)
      .then(() => qmdSupervisor.shutdown())
      .catch(() => undefined)
      .finally(() => {
        quitting = true;
        app.quit();
      });
  });

  await openMainWindow();
  void qmdSupervisor.start();
  void supervisor.start();
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  void app.whenReady().then(bootstrap).catch(() => {
    protocol.unhandle(APP_SCHEME);
    app.quit();
  });
}
