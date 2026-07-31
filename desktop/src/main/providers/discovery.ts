import { createHash } from "node:crypto";
import { constants as fsConstants, createReadStream } from "node:fs";
import {
  access,
  lstat,
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

type ReadTextFile = (
  filePath: string,
  encoding: BufferEncoding
) => Promise<string>;
type ReadDirectory = (directory: string) => Promise<readonly string[]>;

export interface DiscoveryDependencies {
  readonly lstat?: typeof lstat;
  readonly realpath?: typeof realpath;
  readonly readFile?: ReadTextFile;
  readonly access?: typeof access;
  readonly hashFile?: (filePath: string) => Promise<string>;
  readonly readDirectory?: ReadDirectory;
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
  if ((info.mode & 0o022) !== 0) {
    throw new UnsupportedProviderInstallation(
      "Provider executable is group- or world-writable"
    );
  }
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

export async function discoverCodexInstallation(
  wrapperCommandPath: string,
  dependencies: DiscoveryDependencies = {}
): Promise<CodexInstallation> {
  if (!path.isAbsolute(wrapperCommandPath)) {
    throw new UnsupportedProviderInstallation(
      "Codex wrapper path must be absolute"
    );
  }
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
    packageVersion,
    packageRoot,
    managedPackageRoot: packageRoot,
    wrapperPath,
    executable
  };
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
