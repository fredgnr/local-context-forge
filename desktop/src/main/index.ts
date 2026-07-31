import { chmod, lstat, mkdir, realpath } from "node:fs/promises";
import path from "node:path";
import {
  app,
  BrowserWindow,
  dialog,
  ipcMain,
  protocol,
  session,
  shell
} from "electron";
import {
  IPC_CHANNELS,
  type ApiRequest,
  type ApiResponse
} from "../contracts";
import { ApiProxy, ApiProxyError } from "./apiProxy";
import { registerIpcHandlers } from "./ipc";
import {
  isLocalSourceGrant,
  LocalSourceGrantManager
} from "./localSourceGrants";
import { LocalSourcePicker } from "./localSourcePicker";
import { resolveLocalSourceExcludedDirectories } from "./localSourcePolicy";
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
import { McpBridgeServer } from "./mcpBridge";
import { McpOnboardingService } from "./mcpOnboarding";
import { SidecarMcpReadService } from "./mcpSidecarRead";
import { ProviderAttemptClient } from "./providers/providerAttemptClient";
import { ProviderAttemptSupervisor } from "./providers/providerAttemptSupervisor";
import { ProviderResolver } from "./providers/providerResolver";
import { BoundedProcessRunner } from "./providers/processRunner";
import { RetrievalBroker } from "./retrievalBroker";
import {
  resolveSidecarExecutable,
  SidecarSupervisor
} from "./sidecar";
import {
  CANONICAL_RELEASES_URL,
  UpdateClient
} from "./updateClient";
import { registerUpdateIpcHandlers } from "./updateIpc";
import { createMainWindow } from "./window";

const PRODUCT_NAME = "Local Context Forge";
const productCacheDirectory = path.join(
  path.dirname(app.getPath("appData")),
  "Caches",
  PRODUCT_NAME
);
const REQUIRED_SIDECAR_CAPABILITIES = [
  "desktop-handshake",
  "health",
  "library-api",
  "desktop-retrieval-v1",
  "desktop-provider-v1"
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
  if (
    !info.isDirectory() ||
    info.isSymbolicLink() ||
    info.uid !== uid ||
    (await realpath(dataDir)) !== dataDir
  ) {
    throw new Error("Desktop data directory is not private");
  }
  await chmod(dataDir, 0o700);
}

async function localSourceRoots(): Promise<{
  readonly home: string;
  readonly volumes: string;
}> {
  const home = path.resolve(app.getPath("home"));
  const volumes = "/Volumes";
  for (const root of [home, volumes]) {
    const info = await lstat(root);
    if (
      !info.isDirectory() ||
      info.isSymbolicLink() ||
      (await realpath(root)) !== root
    ) {
      throw new Error("Desktop local source root is unavailable");
    }
  }
  return { home, volumes };
}

async function bootstrap(): Promise<void> {
  await prepareDataDirectory();
  const sourceRoots = await localSourceRoots();
  const localSourceExcludedDirectories =
    await resolveLocalSourceExcludedDirectories({
      homeDirectory: sourceRoots.home,
      productCacheDirectory,
      environment: process.env
    });
  installAppSecurity(app);
  installSessionSecurity(session.defaultSession);
  await installStaticProtocol(protocol, configuredRendererRoot());

  const qmdSupervisor = new QmdSupervisor({
    runtime: await configuredQmdRuntime(),
    appDataDir: dataDir,
    dataDir: path.join(dataDir, "qmd", "worker"),
    cacheRoot: path.join(productCacheDirectory, "qmd-runtime"),
    wikiRoot: path.join(dataDir, "wiki")
  });
  const retrievalBroker = new RetrievalBroker(
    qmdSupervisor,
    path.join(dataDir, "wiki")
  );
  const supervisor = new SidecarSupervisor({
    executablePath: configuredSidecarExecutable(),
    dataDir,
    localSourceRoots: [sourceRoots.home, sourceRoots.volumes],
    appVersion: app.getVersion(),
    sidecarVersion: app.getVersion(),
    schemaVersion: 5,
    requiredCapabilities: REQUIRED_SIDECAR_CAPABILITIES,
    retrievalBroker
  });
  const localSourceGrants = new LocalSourceGrantManager({
    dataDirectory: dataDir,
    homeDirectory: sourceRoots.home,
    volumesDirectory: sourceRoots.volumes,
    excludedDirectories: localSourceExcludedDirectories
  });
  const localSourcePicker = new LocalSourcePicker({
    grants: localSourceGrants,
    openDirectory: async () => {
      if (!mainWindow || mainWindow.isDestroyed()) {
        throw new Error("Main window is unavailable");
      }
      return await dialog.showOpenDialog(mainWindow, {
        title: "选择本地代码仓库",
        buttonLabel: "选择仓库",
        properties: ["openDirectory", "dontAddToRecent"]
      });
    }
  });
  const providerRunner = new BoundedProcessRunner();
  const providerResolver = new ProviderResolver(
    providerRunner,
    process.env
  );
  const providerSupervisor = new ProviderAttemptSupervisor(
    new ProviderAttemptClient(dataDir),
    () => supervisor.getConnection(),
    {
      resolver: providerResolver,
      runner: providerRunner
    }
  );
  const mcpOnboarding = new McpOnboardingService({
    resolver: providerResolver,
    runner: providerRunner,
    environment: process.env,
    packaged: app.isPackaged,
    isInApplicationsFolder: () => app.isInApplicationsFolder(),
    resourcesPath: process.resourcesPath
  });
  const mcpBridge = new McpBridgeServer({
    dataDir,
    tempRoot: app.getPath("temp"),
    readService: new SidecarMcpReadService(
      () => supervisor.getConnection()
    ),
    authorizeClient: async (client, signal) => {
      if (signal.aborted) {
        return false;
      }
      const options: Electron.MessageBoxOptions = {
        type: "question",
        title: "允许本地 MCP 查询？",
        message: `允许 ${client.name} ${client.version} 查询已发布的本地文档？`,
        detail:
          "仅开放只读的 resolve-library-id 和 query-docs；" +
          "客户端断开、授权超时或应用退出后，本次授权立即失效。",
        buttons: ["拒绝", "仅允许本次连接"],
        defaultId: 0,
        cancelId: 0,
        noLink: true,
        signal
      };
      const result =
        mainWindow && !mainWindow.isDestroyed()
          ? await dialog.showMessageBox(mainWindow, options)
          : await dialog.showMessageBox(options);
      return !signal.aborted && result.response === 1;
    }
  });
  const apiProxy = new ApiProxy(8);
  const requestDesktopApi = async (
    input: ApiRequest
  ): Promise<ApiResponse> => {
    const connection = supervisor.getConnection();
    if (!connection) {
      throw new ApiProxyError("unavailable");
    }
    return await apiProxy.request(input, connection, async (admitted) => {
      if (
        admitted.method !== "POST" ||
        admitted.path !== "/api/libraries" ||
        admitted.body === null ||
        typeof admitted.body !== "object" ||
        Array.isArray(admitted.body) ||
        !isLocalSourceGrant(admitted.body.source)
      ) {
        return admitted;
      }
      let localPath: string;
      try {
        localPath = await localSourceGrants.consume(admitted.body.source);
      } catch {
        throw new ApiProxyError("invalid-response");
      }
      return {
        ...admitted,
        body: {
          ...admitted.body,
          source: localPath
        }
      };
    });
  };
  const updateClient = await UpdateClient.create({
    packaged: app.isPackaged,
    platform: process.platform,
    architecture: process.arch,
    currentVersion: app.getVersion(),
    resourcesPath: process.resourcesPath,
    updateDirectory: path.join(dataDir, "updates"),
    openPath: (filePath) => shell.openPath(filePath),
    openExternal: async (url) => {
      if (url !== CANONICAL_RELEASES_URL) {
        throw new Error("Update release URL is not canonical");
      }
      await shell.openExternal(CANONICAL_RELEASES_URL);
    }
  });

  registerIpcHandlers(ipcMain, {
    apiRequest: requestDesktopApi,
    runtimeGet: () => supervisor.getStatus(),
    runtimeRetry: () => supervisor.retry(),
    mcpSetupGet: () => mcpOnboarding.status(),
    mcpSetupConfigure: () => mcpOnboarding.configure(),
    mcpSetupClear: () => mcpOnboarding.clear(),
    localSourceSelect: () => localSourcePicker.select(),
    appVersion: () => app.getVersion()
  });
  registerUpdateIpcHandlers(ipcMain, {
    status: () => updateClient.getStatus(),
    check: () => updateClient.check(),
    downloadOrOpen: () => updateClient.downloadOrOpen(),
    cancel: () => updateClient.cancel(),
    openReleasePage: () => updateClient.openReleasePage()
  });

  supervisor.subscribe((status) => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send(IPC_CHANNELS.runtimeChanged, status);
    }
  });
  updateClient.subscribe((status) => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send(IPC_CHANNELS.updateChanged, status);
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
    localSourcePicker.shutdown();
    void updateClient
      .shutdown()
      .catch(() => undefined)
      .then(() => mcpBridge.shutdown())
      .catch(() => undefined)
      .then(() => mcpOnboarding.shutdown())
      .catch(() => undefined)
      .then(() => providerSupervisor.shutdown())
      .catch(() => undefined)
      .then(() => supervisor.shutdown())
      .catch(() => undefined)
      .then(() => qmdSupervisor.shutdown())
      .catch(() => undefined)
      .finally(() => {
        quitting = true;
        app.quit();
      });
  });

  await openMainWindow();
  void mcpBridge.start().catch(() => undefined);
  void qmdSupervisor.start();
  void supervisor.start();
  providerSupervisor.start();
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  void app.whenReady().then(bootstrap).catch(() => {
    protocol.unhandle(APP_SCHEME);
    app.quit();
  });
}
