"use strict";

const path = require("node:path");
const {
  flipFuses,
  FuseVersion,
  FuseV1Options
} = require("@electron/fuses");
const {
  PRODUCT_NAME,
  requireRegularFile
} = require("./packagingAuditCommon.cjs");
const {
  assertEngineeringSmokeMode,
  assertNoProductionEnvironment,
  validateHost
} = require("./prepareEngineeringSmoke.cjs");

const SECURE_FUSES = Object.freeze({
  version: FuseVersion.V1,
  resetAdHocDarwinSignature: true,
  strictlyRequireAllFuses: true,
  [FuseV1Options.RunAsNode]: false,
  [FuseV1Options.EnableCookieEncryption]: true,
  [FuseV1Options.EnableNodeOptionsEnvironmentVariable]: false,
  [FuseV1Options.EnableNodeCliInspectArguments]: false,
  [FuseV1Options.EnableEmbeddedAsarIntegrityValidation]: true,
  [FuseV1Options.OnlyLoadAppFromAsar]: true,
  [FuseV1Options.LoadBrowserProcessSpecificV8Snapshot]: true,
  [FuseV1Options.GrantFileProtocolExtraPrivileges]: false,
  [FuseV1Options.WasmTrapHandlers]: true
});

function engineeringSmokeExecutable(context) {
  if (
    !context ||
    context.electronPlatformName !== "darwin" ||
    (context.arch !== 3 && context.arch !== "arm64") ||
    context.packager?.appInfo?.productFilename !== PRODUCT_NAME ||
    typeof context.appOutDir !== "string" ||
    !path.isAbsolute(context.appOutDir)
  ) {
    throw new TypeError(
      "Engineering-smoke afterPack requires a fixed Darwin arm64 context"
    );
  }
  const executable = path.join(
    context.appOutDir,
    `${PRODUCT_NAME}.app`,
    "Contents",
    "MacOS",
    PRODUCT_NAME
  );
  requireRegularFile(executable, "Engineering-smoke Electron executable");
  return executable;
}

function createAfterPackEngineeringSmoke(dependencies = {}) {
  const applyFuses = dependencies.flipFuses || flipFuses;
  return async function afterPackEngineeringSmoke(context) {
    const environment = dependencies.environment || process.env;
    const platformName = dependencies.platform || process.platform;
    const architecture = dependencies.architecture || process.arch;
    validateHost(platformName, architecture);
    assertEngineeringSmokeMode(environment);
    assertNoProductionEnvironment(environment);
    const executable = engineeringSmokeExecutable(context);
    await applyFuses(executable, SECURE_FUSES);
    return { executable: path.basename(executable), secureFuses: true };
  };
}

const afterPackEngineeringSmoke = createAfterPackEngineeringSmoke();

module.exports = afterPackEngineeringSmoke;
module.exports.SECURE_FUSES = SECURE_FUSES;
module.exports.createAfterPackEngineeringSmoke = createAfterPackEngineeringSmoke;
module.exports.engineeringSmokeExecutable = engineeringSmokeExecutable;
