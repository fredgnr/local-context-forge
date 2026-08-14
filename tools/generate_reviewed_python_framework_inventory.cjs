#!/usr/bin/env node
"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { TextDecoder } = require("node:util");
const zlib = require("node:zlib");

const verifier = require("./verify_reviewed_python_framework.cjs");

const PAYLOAD_CONTRACT = Object.freeze({
  size: 32_739_568,
  sha256: "f922c9d7c78f3745dc453211677fbce2e4b415616556b11376a92ca7a17fc391",
  uncompressedSize: 111_151_616,
  root: "Versions/3.13",
});
const SOURCE_CORE_CONTRACT = Object.freeze({
  entryCount: 3654,
  inventorySha256: "863a6353e58b9c71dc44847051aa582519a66b9347d8c09915ef5254c694bb5d",
});
const SEALED_CORE_CONTRACT = Object.freeze({
  entryCount: 3648,
  inventorySha256: "fdd600648dfce22601ceb0f5a8464d3784f58aa7d7dd09b288e1c942c14167f9",
});
const MAX_CPIO_ENTRIES = 100_000;
const MAX_CPIO_NAME_BYTES = 16 * 1024;
const MAX_CPIO_FILE_BYTES = 256 * 1024 * 1024;
const ODC_HEADER_BYTES = 76;
const ODC_MAGIC = "070707";
const UTF8_DECODER = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true });

const INSTALLER_APPLEDOUBLE_TRANSFORMATIONS = Object.freeze([
  Object.freeze({
    kind: "remove-appledouble",
    path: "Frameworks/Tcl.framework/Versions/8.6/._libtclstub8.6.a",
    type: "file",
    mode: "0664",
    size: 9659,
    sha256: "2786200124513c86f02ed86cef008074a0630d018d25dcd1e71b457d730a65a4",
  }),
  Object.freeze({
    kind: "remove-appledouble",
    path: "Frameworks/Tcl.framework/Versions/8.6/._tclConfig.sh",
    type: "file",
    mode: "0664",
    size: 9657,
    sha256: "1d6110013bd67af351c53295328fc306c1ecafd0125c9f0d00a5e0a4faf1f6a1",
  }),
  Object.freeze({
    kind: "remove-appledouble",
    path: "Frameworks/Tcl.framework/Versions/8.6/._tclooConfig.sh",
    type: "file",
    mode: "0664",
    size: 9658,
    sha256: "b4ca9da4be56dd8bc38a8005326cec5039dbfd3aea35ad16357735ae28cb70ad",
  }),
  Object.freeze({
    kind: "remove-appledouble",
    path: "Frameworks/Tk.framework/Versions/8.6/._libtkstub8.6.a",
    type: "file",
    mode: "0664",
    size: 9657,
    sha256: "70102ab1fa3f67eac935d12e4391bae490fdb839d588d79de606583271360f80",
  }),
  Object.freeze({
    kind: "remove-appledouble",
    path: "Frameworks/Tk.framework/Versions/8.6/._tkConfig.sh",
    type: "file",
    mode: "0664",
    size: 9651,
    sha256: "7af57a8a231e62a7b7a5b3af1741fa68a960e11504cc9e6f9089031187bcc74f",
  }),
  Object.freeze({
    kind: "remove-appledouble",
    path: "lib/python3.13/config-3.13-darwin/._python.o",
    type: "file",
    mode: "0664",
    size: 9650,
    sha256: "1497e74129983366dfc418b967ac756fe8219e128a36bd3ce9f6cc0341e5164f",
  }),
]);

const INSTALLER_SYMLINK_MODE_TRANSFORMATIONS = Object.freeze([
  ["Frameworks/Tcl.framework/Headers", "Versions/Current/Headers"],
  ["Frameworks/Tcl.framework/PrivateHeaders", "Versions/Current/PrivateHeaders"],
  ["Frameworks/Tcl.framework/Resources", "Versions/Current/Resources"],
  ["Frameworks/Tcl.framework/Tcl", "Versions/Current/Tcl"],
  ["Frameworks/Tcl.framework/Versions/Current", "8.6"],
  ["Frameworks/Tcl.framework/libtclstub8.6.a", "Versions/8.6/libtclstub8.6.a"],
  ["Frameworks/Tcl.framework/tclConfig.sh", "Versions/Current/tclConfig.sh"],
  ["Frameworks/Tk.framework/Headers", "Versions/Current/Headers"],
  ["Frameworks/Tk.framework/PrivateHeaders", "Versions/Current/PrivateHeaders"],
  ["Frameworks/Tk.framework/Resources", "Versions/Current/Resources"],
  ["Frameworks/Tk.framework/Tk", "Versions/Current/Tk"],
  ["Frameworks/Tk.framework/Versions/Current", "8.6"],
  ["Frameworks/Tk.framework/libtkstub8.6.a", "Versions/8.6/libtkstub8.6.a"],
  ["Frameworks/Tk.framework/tkConfig.sh", "Versions/Current/tkConfig.sh"],
  ["Headers", "include/python3.13"],
  ["bin/idle3", "idle3.13"],
  ["bin/pydoc3", "pydoc3.13"],
  ["bin/python3", "python3.13"],
  ["bin/python3-config", "python3.13-config"],
  ["bin/python3-intel64", "python3.13-intel64"],
  ["lib/libcrypto.dylib", "libcrypto.3.dylib"],
  ["lib/libcurses.dylib", "libncurses.6.dylib"],
  ["lib/libform.dylib", "libform.6.dylib"],
  ["lib/libmenu.dylib", "libmenu.6.dylib"],
  ["lib/libncurses.dylib", "libncurses.6.dylib"],
  ["lib/libpanel.dylib", "libpanel.6.dylib"],
  ["lib/libpython3.13.dylib", "../Python"],
  ["lib/libssl.dylib", "libssl.3.dylib"],
  ["lib/pkgconfig/python3-embed.pc", "python-3.13-embed.pc"],
  ["lib/pkgconfig/python3.pc", "python-3.13.pc"],
  ["lib/python3.13/config-3.13-darwin/libpython3.13.a", "../../../Python"],
  ["lib/python3.13/config-3.13-darwin/libpython3.13.dylib", "../../../Python"],
  ["share/man/man1/python3.1", "python3.13.1"],
].map(([entryPath, target]) => Object.freeze({
  kind: "symlink-mode",
  path: entryPath,
  type: "symlink",
  target,
  fromMode: "0775",
  toMode: "0777",
})));

const TRANSFORMATION_CONTRACT = Object.freeze([
  ...INSTALLER_APPLEDOUBLE_TRANSFORMATIONS,
  ...INSTALLER_SYMLINK_MODE_TRANSFORMATIONS,
].sort((left, right) => {
  const pathOrder = left.path < right.path ? -1 : left.path > right.path ? 1 : 0;
  if (pathOrder !== 0) {
    return pathOrder;
  }
  return left.kind < right.kind ? -1 : left.kind > right.kind ? 1 : 0;
}));

function fail(message, cause) {
  const error = new Error(message, cause === undefined ? undefined : { cause });
  error.name = "InventoryGenerationError";
  throw error;
}

function statIdentity(info) {
  return [
    info.dev,
    info.ino,
    info.mode,
    info.nlink,
    info.uid,
    info.gid,
    info.size,
    info.mtimeNs,
    info.ctimeNs,
  ];
}

function sameIdentity(left, right) {
  const leftIdentity = statIdentity(left);
  const rightIdentity = statIdentity(right);
  return leftIdentity.every((value, index) => value === rightIdentity[index]);
}

function readPinnedPayload(payloadPath) {
  if (
    typeof payloadPath !== "string" ||
    payloadPath.length === 0 ||
    payloadPath.includes("\0")
  ) {
    fail("Payload path is unsafe");
  }
  const resolved = path.resolve(payloadPath);
  const before = fs.lstatSync(resolved, { bigint: true });
  if (
    !before.isFile() ||
    before.isSymbolicLink() ||
    before.nlink !== 1n ||
    before.size !== BigInt(PAYLOAD_CONTRACT.size)
  ) {
    fail("Payload file identity is unsafe");
  }
  const requiredNoFollow = fs.constants.O_NOFOLLOW;
  if (!Number.isInteger(requiredNoFollow) || requiredNoFollow === 0) {
    fail("O_NOFOLLOW is unavailable");
  }
  const descriptor = fs.openSync(
    resolved,
    fs.constants.O_RDONLY | requiredNoFollow,
  );
  try {
    const heldBefore = fs.fstatSync(descriptor, { bigint: true });
    if (!sameIdentity(before, heldBefore)) {
      fail("Payload changed before reading");
    }
    const content = Buffer.alloc(PAYLOAD_CONTRACT.size);
    let offset = 0;
    while (offset < content.length) {
      const count = fs.readSync(
        descriptor,
        content,
        offset,
        content.length - offset,
        null,
      );
      if (count === 0) {
        fail("Payload was truncated while reading");
      }
      offset += count;
    }
    const heldAfter = fs.fstatSync(descriptor, { bigint: true });
    const namedAfter = fs.lstatSync(resolved, { bigint: true });
    if (
      !sameIdentity(heldBefore, heldAfter) ||
      !sameIdentity(heldBefore, namedAfter)
    ) {
      fail("Payload changed while reading");
    }
    const digest = crypto.createHash("sha256").update(content).digest("hex");
    if (digest !== PAYLOAD_CONTRACT.sha256) {
      fail("Payload digest differs from the reviewed contract");
    }
    return content;
  } finally {
    fs.closeSync(descriptor);
  }
}

function parseOctal(header, start, end, label) {
  const value = header.slice(start, end);
  if (!/^[0-7]+$/.test(value)) {
    fail(`CPIO ${label} is malformed`);
  }
  const parsed = Number.parseInt(value, 8);
  if (!Number.isSafeInteger(parsed)) {
    fail(`CPIO ${label} is outside the safe integer range`);
  }
  return parsed;
}

function decodeName(value) {
  try {
    return UTF8_DECODER.decode(value);
  } catch (error) {
    fail("CPIO path is not valid UTF-8", error);
  }
}

function validateArchivePath(name) {
  if (name === "." || name === "TRAILER!!!") {
    return;
  }
  if (
    !name.startsWith("./") ||
    name.includes("\\") ||
    name.includes("\0") ||
    path.posix.isAbsolute(name)
  ) {
    fail("CPIO path is unsafe");
  }
  const parts = name.slice(2).split("/");
  if (parts.some((part) => part === "" || part === "." || part === "..")) {
    fail("CPIO path is unsafe");
  }
}

function parseOdcPayload(compressed) {
  let payload;
  try {
    payload = zlib.gunzipSync(compressed, {
      maxOutputLength: PAYLOAD_CONTRACT.uncompressedSize,
    });
  } catch (error) {
    fail("Payload gzip stream is invalid", error);
  }
  if (payload.length !== PAYLOAD_CONTRACT.uncompressedSize) {
    fail("Payload uncompressed size differs from the reviewed contract");
  }

  const entries = [];
  const paths = new Set();
  let offset = 0;
  let sawTrailer = false;
  while (offset < payload.length) {
    if (entries.length >= MAX_CPIO_ENTRIES) {
      fail("Payload exceeds its entry bound");
    }
    if (offset + ODC_HEADER_BYTES > payload.length) {
      fail("CPIO header is truncated");
    }
    const header = payload.subarray(offset, offset + ODC_HEADER_BYTES).toString("ascii");
    offset += ODC_HEADER_BYTES;
    if (header.slice(0, 6) !== ODC_MAGIC) {
      fail("CPIO magic is invalid");
    }
    const mode = parseOctal(header, 18, 24, "mode");
    const uid = parseOctal(header, 24, 30, "uid");
    const gid = parseOctal(header, 30, 36, "gid");
    const linkCount = parseOctal(header, 36, 42, "link count");
    const nameSize = parseOctal(header, 59, 65, "name size");
    const fileSize = parseOctal(header, 65, 76, "file size");
    if (
      nameSize < 2 ||
      nameSize > MAX_CPIO_NAME_BYTES ||
      fileSize > MAX_CPIO_FILE_BYTES ||
      offset + nameSize + fileSize > payload.length
    ) {
      fail("CPIO entry exceeds its bounds");
    }
    const encodedName = payload.subarray(offset, offset + nameSize);
    offset += nameSize;
    if (encodedName[encodedName.length - 1] !== 0) {
      fail("CPIO path is not NUL terminated");
    }
    const name = decodeName(encodedName.subarray(0, encodedName.length - 1));
    validateArchivePath(name);
    const content = payload.subarray(offset, offset + fileSize);
    offset += fileSize;
    if (name === "TRAILER!!!") {
      if (fileSize !== 0) {
        fail("CPIO trailer is malformed");
      }
      sawTrailer = true;
      break;
    }
    if (paths.has(name)) {
      fail("CPIO contains a duplicate path");
    }
    paths.add(name);
    const typeBits = mode & 0o170000;
    let type;
    if (typeBits === 0o040000) {
      type = "directory";
    } else if (typeBits === 0o100000) {
      type = "file";
    } else if (typeBits === 0o120000) {
      type = "symlink";
    } else {
      fail("CPIO contains a special file");
    }
    if (
      uid !== 0 ||
      gid !== 0 ||
      linkCount < 1 ||
      (type !== "directory" && linkCount !== 1) ||
      (type === "directory" && fileSize !== 0)
    ) {
      fail("CPIO entry metadata differs from the reviewed contract");
    }
    entries.push(Object.freeze({
      content,
      mode: (mode & 0o7777).toString(8).padStart(4, "0"),
      name,
      type,
    }));
  }
  const trailing = payload.subarray(offset);
  if (
    !sawTrailer ||
    trailing.length > 511 ||
    trailing.some((value) => value !== 0)
  ) {
    fail("CPIO trailer or final length is invalid");
  }
  return entries;
}

function isExcluded(relativePath) {
  return verifier.CORE_EXCLUDED_PATHS.some(
    (excluded) => relativePath === excluded || relativePath.startsWith(`${excluded}/`),
  );
}

function isBytecodeCache(relativePath) {
  const parts = relativePath.split("/").map((part) => part.toLowerCase());
  const basename = parts[parts.length - 1];
  return (
    parts.includes("__pycache__") ||
    basename.endsWith(".pyc") ||
    basename.endsWith(".pyo")
  );
}

function sealedMode(mode) {
  return (Number.parseInt(mode, 8) & ~0o022).toString(8).padStart(4, "0");
}

function buildExpectedManifest(compressedPayload) {
  const rawEntries = parseOdcPayload(compressedPayload);
  const rootPrefix = `./${PAYLOAD_CONTRACT.root}/`;
  const appleDouble = new Map(
    INSTALLER_APPLEDOUBLE_TRANSFORMATIONS.map((entry) => [entry.path, entry]),
  );
  const symlinkModes = new Map(
    INSTALLER_SYMLINK_MODE_TRANSFORMATIONS.map((entry) => [entry.path, entry]),
  );
  const observedAppleDouble = new Set();
  const observedSymlinkModes = new Set();
  const reviewedBroken = new Map(
    verifier.REVIEWED_BROKEN_SYMLINKS.map((entry) => [entry.path, entry.target]),
  );
  const observedBroken = new Map();
  const sourceEntries = [];
  const entries = [];

  for (const raw of rawEntries) {
    if (!raw.name.startsWith(rootPrefix)) {
      continue;
    }
    const relativePath = raw.name.slice(rootPrefix.length);
    if (
      relativePath.length === 0 ||
      isExcluded(relativePath) ||
      isBytecodeCache(relativePath)
    ) {
      continue;
    }
    const sourceItem = {
      path: relativePath,
      mode: raw.type === "symlink" ? raw.mode : sealedMode(raw.mode),
      type: raw.type,
    };
    if (raw.type === "file") {
      sourceItem.size = raw.content.length;
      sourceItem.sha256 = crypto.createHash("sha256").update(raw.content).digest("hex");
    } else if (raw.type === "symlink") {
      const target = decodeName(raw.content);
      if (
        target.length === 0 ||
        target.includes("\0") ||
        path.posix.isAbsolute(target)
      ) {
        fail("Payload symlink target is unsafe");
      }
      sourceItem.target = target;
      sourceItem.sha256 = crypto.createHash("sha256").update(raw.content).digest("hex");
      if (reviewedBroken.get(relativePath) === target) {
        sourceItem.broken = true;
      }
    }
    sourceEntries.push(Object.freeze(sourceItem));

    const appleDoubleRule = appleDouble.get(relativePath);
    if (appleDoubleRule !== undefined) {
      if (
        raw.type !== "file" ||
        raw.mode !== appleDoubleRule.mode ||
        raw.content.length !== appleDoubleRule.size ||
        crypto.createHash("sha256").update(raw.content).digest("hex") !==
          appleDoubleRule.sha256
      ) {
        fail("AppleDouble transformation source changed");
      }
      observedAppleDouble.add(relativePath);
      continue;
    }

    const item = { ...sourceItem };
    if (raw.type === "symlink") {
      const target = sourceItem.target;
      const symlinkRule = symlinkModes.get(relativePath);
      if (
        symlinkRule === undefined ||
        raw.mode !== symlinkRule.fromMode ||
        target !== symlinkRule.target
      ) {
        fail("Installer symlink-mode transformation source changed");
      }
      item.mode = symlinkRule.toMode;
      observedSymlinkModes.add(relativePath);
      if (reviewedBroken.get(relativePath) === target) {
        item.broken = true;
        observedBroken.set(relativePath, target);
      }
    }
    entries.push(Object.freeze(item));
  }

  if (
    observedAppleDouble.size !== appleDouble.size ||
    [...appleDouble.keys()].some((entryPath) => !observedAppleDouble.has(entryPath)) ||
    observedSymlinkModes.size !== symlinkModes.size ||
    [...symlinkModes.keys()].some((entryPath) => !observedSymlinkModes.has(entryPath)) ||
    observedBroken.size !== reviewedBroken.size ||
    [...reviewedBroken].some(
      ([entryPath, target]) => observedBroken.get(entryPath) !== target,
    )
  ) {
    fail("Installer transformation coverage changed");
  }

  sourceEntries.sort((left, right) => verifier.comparePythonStrings(
    left.path,
    right.path,
  ));
  entries.sort((left, right) => verifier.comparePythonStrings(
    left.path,
    right.path,
  ));
  const sourceInventorySha256 = crypto
    .createHash("sha256")
    .update(verifier.canonicalJsonBytes(sourceEntries))
    .digest("hex");
  const inventorySha256 = crypto
    .createHash("sha256")
    .update(verifier.canonicalJsonBytes(entries))
    .digest("hex");
  if (
    sourceEntries.length !== SOURCE_CORE_CONTRACT.entryCount ||
    sourceInventorySha256 !== SOURCE_CORE_CONTRACT.inventorySha256 ||
    entries.length !== SEALED_CORE_CONTRACT.entryCount ||
    inventorySha256 !== SEALED_CORE_CONTRACT.inventorySha256
  ) {
    fail("Derived framework inventory differs from the reviewed contract");
  }
  return Object.freeze({
    schemaVersion: 1,
    source: Object.freeze({
      payloadSize: PAYLOAD_CONTRACT.size,
      payloadSha256: PAYLOAD_CONTRACT.sha256,
      coreEntryCount: sourceEntries.length,
      coreInventorySha256: sourceInventorySha256,
    }),
    transformations: TRANSFORMATION_CONTRACT,
    entryCount: entries.length,
    inventorySha256,
    entries,
  });
}

function parseArguments(argv) {
  if (!Array.isArray(argv) || argv.length !== 4) {
    fail("Usage: generate_reviewed_python_framework_inventory.cjs --payload PATH (--output PATH | --check PATH)");
  }
  const result = Object.create(null);
  for (let index = 0; index < argv.length; index += 2) {
    const option = argv[index];
    const value = argv[index + 1];
    if (
      (option !== "--payload" && option !== "--output" && option !== "--check") ||
      Object.hasOwn(result, option) ||
      typeof value !== "string" ||
      value.length === 0 ||
      value.startsWith("--")
    ) {
      fail("Usage: generate_reviewed_python_framework_inventory.cjs --payload PATH (--output PATH | --check PATH)");
    }
    result[option] = value;
  }
  if (
    !Object.hasOwn(result, "--payload") ||
    (Object.hasOwn(result, "--output") === Object.hasOwn(result, "--check"))
  ) {
    fail("Usage: generate_reviewed_python_framework_inventory.cjs --payload PATH (--output PATH | --check PATH)");
  }
  return {
    payload: result["--payload"],
    output: result["--output"],
    check: result["--check"],
  };
}

function main() {
  try {
    const options = parseArguments(process.argv.slice(2));
    const manifest = buildExpectedManifest(readPinnedPayload(options.payload));
    const content = Buffer.from(`${JSON.stringify(manifest)}\n`, "utf8");
    if (options.output !== undefined) {
      fs.writeFileSync(options.output, content, { flag: "wx", mode: 0o644 });
    } else {
      const existing = fs.readFileSync(options.check);
      if (!crypto.timingSafeEqual(
        crypto.createHash("sha256").update(existing).digest(),
        crypto.createHash("sha256").update(content).digest(),
      )) {
        fail("Reviewed inventory file differs from the locked Payload derivation");
      }
    }
    process.stdout.write(
      `entries=${manifest.entryCount} inventory_sha256=${manifest.inventorySha256}\n`,
    );
  } catch (_error) {
    process.stderr.write("Reviewed Python framework inventory generation failed\n");
    process.exitCode = 1;
  }
}

module.exports = Object.freeze({
  INSTALLER_APPLEDOUBLE_TRANSFORMATIONS,
  INSTALLER_SYMLINK_MODE_TRANSFORMATIONS,
  PAYLOAD_CONTRACT,
  SEALED_CORE_CONTRACT,
  SOURCE_CORE_CONTRACT,
  TRANSFORMATION_CONTRACT,
  buildExpectedManifest,
  parseArguments,
  parseOdcPayload,
  readPinnedPayload,
});

if (require.main === module) {
  main();
}
