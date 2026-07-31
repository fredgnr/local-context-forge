import { createHash } from "node:crypto";
import { execFile } from "node:child_process";
import { constants as fsConstants, createReadStream } from "node:fs";
import {
  access,
  lstat,
  open,
  readdir,
  readFile,
  realpath
} from "node:fs/promises";
import path from "node:path";
import type {
  CodexInstallation,
  CursorInstallation,
  FileIdentity
} from "./contracts";

const CODEX_WRAPPER_PACKAGE = "@openai/codex";
const CODEX_PLATFORM_ALIAS = "@openai/codex-darwin-arm64";
const CODEX_PLATFORM_SUFFIX = "darwin-arm64";
const CODEX_TARGET = "aarch64-apple-darwin";
const PACKAGE_VERSION = /^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/;
const STANDALONE_RELEASE =
  /^(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)-aarch64-apple-darwin$/;
const OFFICIAL_TEAM_IDENTIFIER = "2DC432GLL2";
const OFFICIAL_SIGNING_AUTHORITY =
  "Developer ID Application: OpenAI OpCo, LLC (2DC432GLL2)";
const SIGNED_PLATFORM = "darwin";
const SIGNED_ARCHITECTURE = "arm64";
const CODE_SIGN_TIMEOUT_MS = 10_000;
const CODE_SIGN_OUTPUT_LIMIT_BYTES = 64 * 1024;
const HOMEBREW_VISIBLE_PATH = "/opt/homebrew/bin/codex";
const HOMEBREW_CASK_ROOT = "/opt/homebrew/Caskroom/codex";
const RELEASE_VISIBLE_PATH = "/usr/local/bin/codex";

type ReadTextFile = (
  filePath: string,
  encoding: BufferEncoding
) => Promise<string>;
type ReadDirectory = (directory: string) => Promise<readonly string[]>;
type VerifyExecutable = (filePath: string) => Promise<void>;

export interface DiscoveryDependencies {
  readonly lstat?: typeof lstat;
  readonly realpath?: typeof realpath;
  readonly readFile?: ReadTextFile;
  readonly access?: typeof access;
  readonly hashFile?: (filePath: string) => Promise<string>;
  readonly readDirectory?: ReadDirectory;
  readonly environment?: NodeJS.ProcessEnv;
  readonly platform?: NodeJS.Platform;
  readonly architecture?: string;
  readonly effectiveUid?: number;
  readonly verifyOfficialSignature?: VerifyExecutable;
  readonly verifyArm64MachO?: VerifyExecutable;
}

class UnsupportedProviderInstallation extends Error {
  constructor(message: string) {
    super(message);
    this.name = "UnsupportedProviderInstallation";
  }
}

export { UnsupportedProviderInstallation };

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return (
    !!value &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    (Object.getPrototypeOf(value) === Object.prototype ||
      Object.getPrototypeOf(value) === null)
  );
}

async function sha256File(filePath: string): Promise<string> {
  const digest = createHash("sha256");
  await new Promise<void>((resolve, reject) => {
    const stream = createReadStream(filePath);
    stream.on("data", (chunk) => digest.update(chunk));
    stream.once("error", reject);
    stream.once("end", resolve);
  });
  return digest.digest("hex");
}

function safeParsePackageJson(text: string, label: string): Record<string, unknown> {
  if (Buffer.byteLength(text, "utf8") > 128 * 1024) {
    throw new UnsupportedProviderInstallation(`${label} metadata is too large`);
  }
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    throw new UnsupportedProviderInstallation(`${label} metadata is invalid`);
  }
  if (!isPlainObject(value)) {
    throw new UnsupportedProviderInstallation(`${label} metadata is invalid`);
  }
  return value;
}

function isOfficialRepository(value: unknown): boolean {
  if (!isPlainObject(value)) {
    return false;
  }
  return (
    value.url === "git+https://github.com/openai/codex.git" &&
    value.directory === "codex-cli"
  );
}

function isInside(root: string, candidate: string): boolean {
  const relative = path.relative(root, candidate);
  return relative !== "" && !relative.startsWith(`..${path.sep}`) && relative !== ".." && !path.isAbsolute(relative);
}

function currentEffectiveUid(
  dependencies: DiscoveryDependencies
): number | undefined {
  if (dependencies.effectiveUid !== undefined) {
    return dependencies.effectiveUid;
  }
  return typeof process.geteuid === "function"
    ? process.geteuid()
    : undefined;
}

function requireTrustedOwner(
  ownerUid: number,
  dependencies: DiscoveryDependencies,
  label: string
): void {
  const effectiveUid = currentEffectiveUid(dependencies);
  if (
    effectiveUid !== undefined &&
    ownerUid !== 0 &&
    ownerUid !== effectiveUid
  ) {
    throw new UnsupportedProviderInstallation(
      `${label} is owned by an untrusted account`
    );
  }
}

function requireSafeMode(mode: number, label: string): void {
  if ((mode & 0o022) !== 0) {
    throw new UnsupportedProviderInstallation(
      `${label} is group- or world-writable`
    );
  }
}

async function identifyExecutable(
  executablePath: string,
  dependencies: DiscoveryDependencies = {}
): Promise<FileIdentity> {
  const stat = dependencies.lstat ?? lstat;
  const resolveRealpath = dependencies.realpath ?? realpath;
  const checkAccess = dependencies.access ?? access;
  const hash = dependencies.hashFile ?? sha256File;
  const canonicalPath = await resolveRealpath(executablePath).catch(() => {
    throw new UnsupportedProviderInstallation("Provider executable is missing");
  });
  const info = await stat(canonicalPath).catch(() => undefined);
  if (!info?.isFile() || info.isSymbolicLink()) {
    throw new UnsupportedProviderInstallation(
      "Provider executable is not a regular file"
    );
  }
  requireTrustedOwner(info.uid, dependencies, "Provider executable");
  requireSafeMode(info.mode, "Provider executable");
  await checkAccess(canonicalPath, fsConstants.X_OK).catch(() => {
    throw new UnsupportedProviderInstallation(
      "Provider executable is not executable"
    );
  });
  return {
    canonicalPath,
    sha256: await hash(canonicalPath),
    size: info.size,
    mtimeMs: info.mtimeMs,
    device: info.dev,
    inode: info.ino,
    mode: info.mode
  };
}

function runCodesign(arguments_: readonly string[]): Promise<string> {
  return new Promise((resolve, reject) => {
    execFile(
      "/usr/bin/codesign",
      [...arguments_],
      {
        encoding: "utf8",
        env: {
          PATH: "/usr/bin:/bin:/usr/sbin:/sbin",
          LANG: "C"
        },
        maxBuffer: CODE_SIGN_OUTPUT_LIMIT_BYTES,
        timeout: CODE_SIGN_TIMEOUT_MS,
        windowsHide: true
      },
      (error, stdout, stderr) => {
        if (error) {
          reject(
            new UnsupportedProviderInstallation(
              "Codex signature verification failed"
            )
          );
          return;
        }
        resolve(`${stdout}${stderr}`);
      }
    );
  });
}

async function verifyOfficialCodexSignature(
  executablePath: string
): Promise<void> {
  await runCodesign([
    "--verify",
    "--strict",
    "--verbose=2",
    executablePath
  ]);
  const details = await runCodesign([
    "--display",
    "--verbose=4",
    executablePath
  ]);
  const lines = details.split(/\r?\n/).map((line) => line.trim());
  if (
    !lines.includes(`TeamIdentifier=${OFFICIAL_TEAM_IDENTIFIER}`) ||
    !lines.includes(`Authority=${OFFICIAL_SIGNING_AUTHORITY}`)
  ) {
    throw new UnsupportedProviderInstallation(
      "Codex signature identity is not OpenAI"
    );
  }
}

async function verifyThinArm64MachO(
  executablePath: string
): Promise<void> {
  const handle = await open(executablePath, "r").catch(() => undefined);
  if (!handle) {
    throw new UnsupportedProviderInstallation(
      "Codex Mach-O header is unavailable"
    );
  }
  try {
    const header = Buffer.alloc(8);
    const { bytesRead } = await handle.read(header, 0, header.length, 0);
    if (
      bytesRead !== header.length ||
      !header.subarray(0, 4).equals(
        Buffer.from([0xcf, 0xfa, 0xed, 0xfe])
      ) ||
      !header.subarray(4, 8).equals(
        Buffer.from([0x0c, 0x00, 0x00, 0x01])
      )
    ) {
      throw new UnsupportedProviderInstallation(
        "Codex executable is not an arm64 Mach-O"
      );
    }
  } finally {
    await handle.close();
  }
}

async function verifySignedExecutable(
  executablePath: string,
  dependencies: DiscoveryDependencies
): Promise<void> {
  const verifyMachO =
    dependencies.verifyArm64MachO ?? verifyThinArm64MachO;
  const verifySignature =
    dependencies.verifyOfficialSignature ??
    verifyOfficialCodexSignature;
  await verifyMachO(executablePath);
  await verifySignature(executablePath);
}

async function requireTrustedSymlink(
  linkPath: string,
  dependencies: DiscoveryDependencies
): Promise<string> {
  const stat = dependencies.lstat ?? lstat;
  const resolveRealpath = dependencies.realpath ?? realpath;
  const info = await stat(linkPath).catch(() => undefined);
  if (!info?.isSymbolicLink()) {
    throw new UnsupportedProviderInstallation(
      "Codex install entry is not the expected symlink"
    );
  }
  requireTrustedOwner(info.uid, dependencies, "Codex install entry");
  return await resolveRealpath(linkPath).catch(() => {
    throw new UnsupportedProviderInstallation(
      "Codex install entry is broken"
    );
  });
}

async function requireTrustedMetadata(
  metadataPath: string,
  dependencies: DiscoveryDependencies,
  label: string
): Promise<Record<string, unknown>> {
  const stat = dependencies.lstat ?? lstat;
  const resolveRealpath = dependencies.realpath ?? realpath;
  const readText =
    dependencies.readFile ?? (readFile as ReadTextFile);
  const info = await stat(metadataPath).catch(() => undefined);
  if (!info?.isFile() || info.isSymbolicLink()) {
    throw new UnsupportedProviderInstallation(
      `${label} metadata is missing`
    );
  }
  requireTrustedOwner(info.uid, dependencies, `${label} metadata`);
  requireSafeMode(info.mode, `${label} metadata`);
  const canonicalPath = await resolveRealpath(metadataPath).catch(
    () => undefined
  );
  if (canonicalPath !== metadataPath) {
    throw new UnsupportedProviderInstallation(
      `${label} metadata path is not canonical`
    );
  }
  return safeParsePackageJson(
    await readText(metadataPath, "utf8").catch(() => {
      throw new UnsupportedProviderInstallation(
        `${label} metadata is unreadable`
      );
    }),
    label
  );
}

function requireSignedRuntime(
  dependencies: DiscoveryDependencies
): void {
  if (
    (dependencies.platform ?? process.platform) !== SIGNED_PLATFORM ||
    (dependencies.architecture ?? process.arch) !== SIGNED_ARCHITECTURE
  ) {
    throw new UnsupportedProviderInstallation(
      "Signed Codex installs require native macOS arm64"
    );
  }
}

async function requireTrustedDirectory(
  directory: string,
  dependencies: DiscoveryDependencies,
  label: string
): Promise<void> {
  const stat = dependencies.lstat ?? lstat;
  const resolveRealpath = dependencies.realpath ?? realpath;
  const info = await stat(directory).catch(() => undefined);
  if (!info?.isDirectory() || info.isSymbolicLink()) {
    throw new UnsupportedProviderInstallation(
      `${label} is not a regular directory`
    );
  }
  requireTrustedOwner(info.uid, dependencies, label);
  requireSafeMode(info.mode, label);
  if ((await resolveRealpath(directory).catch(() => undefined)) !== directory) {
    throw new UnsupportedProviderInstallation(
      `${label} path is not canonical`
    );
  }
}

async function firstExistingPackageJson(
  packageRoot: string,
  dependencies: DiscoveryDependencies
): Promise<string> {
  const stat = dependencies.lstat ?? lstat;
  const candidates = [
    path.join(
      packageRoot,
      "node_modules",
      "@openai",
      "codex-darwin-arm64",
      "package.json"
    ),
    path.resolve(packageRoot, "..", "codex-darwin-arm64", "package.json"),
    path.resolve(
      packageRoot,
      "..",
      "..",
      "@openai",
      "codex-darwin-arm64",
      "package.json"
    )
  ];
  for (const candidate of new Set(candidates)) {
    const info = await stat(candidate).catch(() => undefined);
    if (info?.isFile()) {
      return candidate;
    }
  }
  throw new UnsupportedProviderInstallation(
    "Official Codex Darwin arm64 package is missing"
  );
}

async function discoverNpmCodexInstallation(
  wrapperCommandPath: string,
  dependencies: DiscoveryDependencies = {}
): Promise<CodexInstallation> {
  const resolveRealpath = dependencies.realpath ?? realpath;
  const readText = dependencies.readFile ?? (readFile as ReadTextFile);
  const wrapperPath = await resolveRealpath(wrapperCommandPath).catch(() => {
    throw new UnsupportedProviderInstallation("Codex wrapper is missing");
  });
  if (
    path.basename(wrapperPath) !== "codex.js" ||
    path.basename(path.dirname(wrapperPath)) !== "bin"
  ) {
    throw new UnsupportedProviderInstallation(
      "Codex command is not the official npm wrapper layout"
    );
  }

  const packageRoot = path.dirname(path.dirname(wrapperPath));
  const wrapperMetadata = safeParsePackageJson(
    await readText(path.join(packageRoot, "package.json"), "utf8").catch(() => {
      throw new UnsupportedProviderInstallation(
        "Codex wrapper package metadata is missing"
      );
    }),
    "Codex wrapper"
  );
  const packageVersion = wrapperMetadata.version;
  const optionalDependencies = wrapperMetadata.optionalDependencies;
  if (
    wrapperMetadata.name !== CODEX_WRAPPER_PACKAGE ||
    typeof packageVersion !== "string" ||
    !PACKAGE_VERSION.test(packageVersion) ||
    !isOfficialRepository(wrapperMetadata.repository) ||
    !isPlainObject(optionalDependencies) ||
    optionalDependencies[CODEX_PLATFORM_ALIAS] !==
      `npm:${CODEX_WRAPPER_PACKAGE}@${packageVersion}-${CODEX_PLATFORM_SUFFIX}`
  ) {
    throw new UnsupportedProviderInstallation(
      "Codex wrapper metadata does not match the official package"
    );
  }

  const platformJsonPath = await firstExistingPackageJson(
    packageRoot,
    dependencies
  );
  const canonicalPlatformJson = await resolveRealpath(platformJsonPath);
  const platformRoot = path.dirname(canonicalPlatformJson);
  const platformMetadata = safeParsePackageJson(
    await readText(canonicalPlatformJson, "utf8"),
    "Codex platform package"
  );
  if (
    platformMetadata.name !== CODEX_WRAPPER_PACKAGE ||
    platformMetadata.version !==
      `${packageVersion}-${CODEX_PLATFORM_SUFFIX}` ||
    !Array.isArray(platformMetadata.os) ||
    !platformMetadata.os.includes("darwin") ||
    !Array.isArray(platformMetadata.cpu) ||
    !platformMetadata.cpu.includes("arm64") ||
    !isOfficialRepository(platformMetadata.repository)
  ) {
    throw new UnsupportedProviderInstallation(
      "Codex platform metadata does not match Darwin arm64"
    );
  }

  const expectedExecutable = path.join(
    platformRoot,
    "vendor",
    CODEX_TARGET,
    "bin",
    "codex"
  );
  const executable = await identifyExecutable(
    expectedExecutable,
    dependencies
  );
  if (!isInside(platformRoot, executable.canonicalPath)) {
    throw new UnsupportedProviderInstallation(
      "Codex executable escapes its platform package"
    );
  }
  return {
    provider: "codex_cli",
    installationKind: "npm",
    packageVersion,
    packageRoot,
    managedPackageRoot: packageRoot,
    wrapperPath,
    executable,
    auxiliaryExecutables: []
  };
}

function standaloneVisiblePath(
  dependencies: DiscoveryDependencies
): string | undefined {
  const home = dependencies.environment?.HOME;
  return (
    typeof home === "string" &&
    path.isAbsolute(home) &&
    path.normalize(home) === home &&
    !home.includes("\0") &&
    home !== path.parse(home).root
  )
    ? path.join(path.normalize(home), ".local", "bin", "codex")
    : undefined;
}

function standaloneManagedRoot(
  dependencies: DiscoveryDependencies
): string | undefined {
  const environment = dependencies.environment;
  const home = environment?.HOME;
  if (
    !environment ||
    typeof home !== "string" ||
    !path.isAbsolute(home) ||
    path.normalize(home) !== home ||
    home.includes("\0") ||
    home === path.parse(home).root
  ) {
    return undefined;
  }
  const codexHome =
    typeof environment.CODEX_HOME === "string"
      ? environment.CODEX_HOME
      : path.join(home, ".codex");
  if (!path.isAbsolute(codexHome)) {
    return undefined;
  }
  if (
    path.normalize(codexHome) !== codexHome ||
    codexHome.includes("\0") ||
    codexHome === path.parse(codexHome).root
  ) {
    return undefined;
  }
  return path.join(
    path.normalize(codexHome),
    "packages",
    "standalone"
  );
}

async function discoverSignedPackage(
  input: {
    readonly installationKind: "standalone" | "homebrew-cask";
    readonly visiblePath: string;
    readonly releaseRoot: string;
    readonly packageVersion: string;
    readonly expectedExecutable: string;
    readonly managedPackageRoot: string;
  },
  dependencies: DiscoveryDependencies
): Promise<CodexInstallation> {
  await requireTrustedDirectory(
    input.releaseRoot,
    dependencies,
    "Codex release directory"
  );
  const metadata = await requireTrustedMetadata(
    path.join(input.releaseRoot, "codex-package.json"),
    dependencies,
    "Codex standalone package"
  );
  if (metadata.version !== input.packageVersion) {
    throw new UnsupportedProviderInstallation(
      "Codex standalone package version does not match its release path"
    );
  }
  const executable = await identifyExecutable(
    input.expectedExecutable,
    dependencies
  );
  if (
    executable.canonicalPath !== input.expectedExecutable ||
    !isInside(input.releaseRoot, executable.canonicalPath)
  ) {
    throw new UnsupportedProviderInstallation(
      "Codex executable escapes its signed package"
    );
  }
  const host = await identifyExecutable(
    path.join(input.releaseRoot, "bin", "codex-code-mode-host"),
    dependencies
  );
  if (!isInside(input.releaseRoot, host.canonicalPath)) {
    throw new UnsupportedProviderInstallation(
      "Codex code-mode host escapes its signed package"
    );
  }
  await verifySignedExecutable(executable.canonicalPath, dependencies);
  await verifySignedExecutable(host.canonicalPath, dependencies);
  return {
    provider: "codex_cli",
    installationKind: input.installationKind,
    packageVersion: input.packageVersion,
    packageRoot: input.releaseRoot,
    managedPackageRoot: input.managedPackageRoot,
    wrapperPath: input.visiblePath,
    executable,
    auxiliaryExecutables: [host]
  };
}

async function discoverStandaloneCodexInstallation(
  commandPath: string,
  dependencies: DiscoveryDependencies
): Promise<CodexInstallation> {
  requireSignedRuntime(dependencies);
  const visiblePath = standaloneVisiblePath(dependencies);
  const managedPackageRoot = standaloneManagedRoot(dependencies);
  if (
    !visiblePath ||
    !managedPackageRoot ||
    commandPath !== visiblePath
  ) {
    throw new UnsupportedProviderInstallation(
      "Codex command is not the official standalone install entry"
    );
  }
  const currentPath = path.join(managedPackageRoot, "current");
  const releaseRoot = await requireTrustedSymlink(
    currentPath,
    dependencies
  );
  const releasesRoot = path.join(managedPackageRoot, "releases");
  await requireTrustedDirectory(
    releasesRoot,
    dependencies,
    "Codex standalone releases directory"
  );
  const releaseRelative = path.relative(releasesRoot, releaseRoot);
  const releaseMatch =
    !releaseRelative.includes(path.sep) &&
    !path.isAbsolute(releaseRelative)
      ? STANDALONE_RELEASE.exec(releaseRelative)
      : null;
  const packageVersion = releaseMatch?.[1];
  if (
    !packageVersion ||
    path.join(releasesRoot, releaseRelative) !== releaseRoot
  ) {
    throw new UnsupportedProviderInstallation(
      "Codex standalone current link is outside its releases directory"
    );
  }
  const visibleTarget = await requireTrustedSymlink(
    visiblePath,
    dependencies
  );
  const executableCandidates = [
    path.join(releaseRoot, "bin", "codex"),
    path.join(releaseRoot, "codex")
  ];
  if (!executableCandidates.includes(visibleTarget)) {
    throw new UnsupportedProviderInstallation(
      "Codex standalone entry targets an unexpected file"
    );
  }
  return await discoverSignedPackage(
    {
      installationKind: "standalone",
      visiblePath,
      releaseRoot,
      packageVersion,
      expectedExecutable: visibleTarget,
      managedPackageRoot
    },
    dependencies
  );
}

async function discoverHomebrewCodexInstallation(
  commandPath: string,
  dependencies: DiscoveryDependencies
): Promise<CodexInstallation> {
  requireSignedRuntime(dependencies);
  if (commandPath !== HOMEBREW_VISIBLE_PATH) {
    throw new UnsupportedProviderInstallation(
      "Codex command is not the Homebrew cask entry"
    );
  }
  const executablePath = await requireTrustedSymlink(
    HOMEBREW_VISIBLE_PATH,
    dependencies
  );
  const relative = path.relative(HOMEBREW_CASK_ROOT, executablePath);
  const parts = relative.split(path.sep);
  const packageVersion = parts[0];
  if (
    parts.length !== 3 ||
    !packageVersion ||
    !PACKAGE_VERSION.test(packageVersion) ||
    parts[1] !== "bin" ||
    parts[2] !== "codex"
  ) {
    throw new UnsupportedProviderInstallation(
      "Codex Homebrew cask entry targets an unexpected layout"
    );
  }
  const releaseRoot = path.join(
    HOMEBREW_CASK_ROOT,
    packageVersion
  );
  return await discoverSignedPackage(
    {
      installationKind: "homebrew-cask",
      visiblePath: HOMEBREW_VISIBLE_PATH,
      releaseRoot,
      packageVersion,
      expectedExecutable: executablePath,
      managedPackageRoot: HOMEBREW_CASK_ROOT
    },
    dependencies
  );
}

async function discoverFixedReleaseCodexInstallation(
  commandPath: string,
  dependencies: DiscoveryDependencies
): Promise<CodexInstallation> {
  requireSignedRuntime(dependencies);
  if (commandPath !== RELEASE_VISIBLE_PATH) {
    throw new UnsupportedProviderInstallation(
      "Codex command is not the fixed release entry"
    );
  }
  const stat = dependencies.lstat ?? lstat;
  const resolveRealpath = dependencies.realpath ?? realpath;
  const visibleInfo = await stat(RELEASE_VISIBLE_PATH).catch(
    () => undefined
  );
  if (
    !visibleInfo ||
    (!visibleInfo.isFile() && !visibleInfo.isSymbolicLink())
  ) {
    throw new UnsupportedProviderInstallation(
      "Codex fixed release entry is invalid"
    );
  }
  requireTrustedOwner(
    visibleInfo.uid,
    dependencies,
    "Codex fixed release entry"
  );
  if (visibleInfo.isFile()) {
    requireSafeMode(
      visibleInfo.mode,
      "Codex fixed release entry"
    );
  }
  const executablePath = await resolveRealpath(RELEASE_VISIBLE_PATH).catch(
    () => {
      throw new UnsupportedProviderInstallation(
        "Codex fixed release entry is broken"
      );
    }
  );
  const executable = await identifyExecutable(
    executablePath,
    dependencies
  );
  await verifySignedExecutable(executable.canonicalPath, dependencies);
  const packageRoot = path.dirname(executable.canonicalPath);
  return {
    provider: "codex_cli",
    installationKind: "signed-binary",
    packageVersion: undefined,
    packageRoot,
    managedPackageRoot: packageRoot,
    wrapperPath: RELEASE_VISIBLE_PATH,
    executable,
    auxiliaryExecutables: []
  };
}

function isSignedLayoutCandidate(
  commandPath: string,
  dependencies: DiscoveryDependencies
): boolean {
  return (
    commandPath === standaloneVisiblePath(dependencies) ||
    commandPath === HOMEBREW_VISIBLE_PATH ||
    commandPath === RELEASE_VISIBLE_PATH
  );
}

async function discoverSignedCodexInstallation(
  commandPath: string,
  dependencies: DiscoveryDependencies
): Promise<CodexInstallation> {
  if (commandPath === standaloneVisiblePath(dependencies)) {
    return await discoverStandaloneCodexInstallation(
      commandPath,
      dependencies
    );
  }
  if (commandPath === HOMEBREW_VISIBLE_PATH) {
    return await discoverHomebrewCodexInstallation(
      commandPath,
      dependencies
    );
  }
  return await discoverFixedReleaseCodexInstallation(
    commandPath,
    dependencies
  );
}

export async function discoverCodexInstallation(
  wrapperCommandPath: string,
  dependencies: DiscoveryDependencies = {}
): Promise<CodexInstallation> {
  if (
    !path.isAbsolute(wrapperCommandPath) ||
    wrapperCommandPath.includes("\0") ||
    path.normalize(wrapperCommandPath) !== wrapperCommandPath
  ) {
    throw new UnsupportedProviderInstallation(
      "Codex wrapper path must be an absolute normalized path"
    );
  }
  try {
    return await discoverNpmCodexInstallation(
      wrapperCommandPath,
      dependencies
    );
  } catch (error) {
    if (
      !(error instanceof UnsupportedProviderInstallation) ||
      !isSignedLayoutCandidate(wrapperCommandPath, dependencies)
    ) {
      throw error;
    }
  }
  return await discoverSignedCodexInstallation(
    wrapperCommandPath,
    dependencies
  );
}

export async function discoverCursorInstallation(
  commandPath: string,
  dependencies: DiscoveryDependencies = {}
): Promise<CursorInstallation> {
  if (!path.isAbsolute(commandPath)) {
    throw new UnsupportedProviderInstallation(
      "Cursor executable path must be absolute"
    );
  }
  return {
    provider: "cursor_cli",
    executable: await identifyExecutable(commandPath, dependencies)
  };
}

export async function revalidateExecutableIdentity(
  identity: FileIdentity,
  dependencies: DiscoveryDependencies = {}
): Promise<void> {
  const current = await identifyExecutable(
    identity.canonicalPath,
    dependencies
  );
  const fields: readonly (keyof FileIdentity)[] = [
    "canonicalPath",
    "sha256",
    "size",
    "mtimeMs",
    "device",
    "inode",
    "mode"
  ];
  if (fields.some((field) => current[field] !== identity[field])) {
    throw new UnsupportedProviderInstallation(
      "Provider executable identity changed"
    );
  }
}

export async function revalidateCodexInstallation(
  installation: CodexInstallation,
  dependencies: DiscoveryDependencies = {}
): Promise<void> {
  await revalidateExecutableIdentity(
    installation.executable,
    dependencies
  );
  for (const identity of installation.auxiliaryExecutables) {
    await revalidateExecutableIdentity(identity, dependencies);
  }
  if (installation.installationKind !== "npm") {
    requireSignedRuntime(dependencies);
    await verifySignedExecutable(
      installation.executable.canonicalPath,
      dependencies
    );
    for (const identity of installation.auxiliaryExecutables) {
      await verifySignedExecutable(identity.canonicalPath, dependencies);
    }
  }
}

export async function findCommandOnPath(
  command: "codex" | "cursor-agent",
  environment: NodeJS.ProcessEnv,
  dependencies: Pick<DiscoveryDependencies, "access"> = {}
): Promise<string | undefined> {
  return (
    await findCommandCandidates(command, environment, dependencies)
  )[0];
}

async function safeDirectoryEntries(
  directory: string,
  readDirectory: ReadDirectory
): Promise<readonly string[]> {
  const entries = await readDirectory(directory).catch(() => []);
  return entries
    .filter(
      (entry) =>
        typeof entry === "string" &&
        /^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/.test(entry)
    )
    .sort()
    .slice(0, 128);
}

export async function findCommandCandidates(
  command: "codex" | "cursor-agent",
  environment: NodeJS.ProcessEnv,
  dependencies: Pick<
    DiscoveryDependencies,
    "access" | "readDirectory"
  > = {}
): Promise<readonly string[]> {
  const checkAccess = dependencies.access ?? access;
  const readDirectory: ReadDirectory =
    dependencies.readDirectory ??
    (async (directory) =>
      await readdir(directory, { encoding: "utf8" }));
  const directories: string[] = [];
  for (const directory of (environment.PATH ?? "").split(path.delimiter)) {
    if (!directory || !path.isAbsolute(directory)) {
      continue;
    }
    directories.push(path.normalize(directory));
  }
  const home =
    typeof environment.HOME === "string" &&
    path.isAbsolute(environment.HOME)
      ? path.normalize(environment.HOME)
      : undefined;
  directories.push("/opt/homebrew/bin", "/usr/local/bin");
  if (home) {
    directories.push(
      path.join(home, ".local", "bin"),
      path.join(home, ".npm-global", "bin"),
      path.join(home, ".npm", "bin"),
      path.join(home, ".volta", "bin"),
      path.join(home, ".bun", "bin")
    );
    if (command === "codex") {
      const versionedRoots = [
        {
          root: path.join(home, ".nvm", "versions", "node"),
          suffix: ["bin"]
        },
        {
          root: path.join(
            home,
            ".local",
            "share",
            "mise",
            "installs",
            "node"
          ),
          suffix: ["bin"]
        },
        {
          root: path.join(home, ".asdf", "installs", "nodejs"),
          suffix: ["bin"]
        },
        {
          root: path.join(
            home,
            "Library",
            "Application Support",
            "fnm",
            "node-versions"
          ),
          suffix: ["installation", "bin"]
        }
      ] as const;
      for (const layout of versionedRoots) {
        for (const version of await safeDirectoryEntries(
          layout.root,
          readDirectory
        )) {
          directories.push(
            path.join(layout.root, version, ...layout.suffix)
          );
        }
      }
    }
  }
  const candidates: string[] = [];
  for (const directory of new Set(directories)) {
    const candidate = path.join(directory, command);
    const available = await checkAccess(candidate, fsConstants.X_OK)
      .then(() => true)
      .catch(() => false);
    if (available) {
      candidates.push(candidate);
    }
  }
  return candidates;
}
