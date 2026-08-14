declare const __LCF_DISTRIBUTION_PROFILE__:
  | "standard"
  | "engineering-smoke"
  | undefined;

export type DistributionProfileName =
  | "standard"
  | "engineering-smoke";

export interface DistributionProfile {
  readonly name: DistributionProfileName;
  readonly productName: string;
  readonly dataDirectoryName: string;
  readonly cacheDirectoryName: string;
  readonly updaterPolicy: "standard" | "engineering-disabled";
  readonly engineeringOnly: boolean;
}

const STANDARD_PROFILE: DistributionProfile = Object.freeze({
  name: "standard",
  productName: "Local Context Forge",
  dataDirectoryName: "Local Context Forge",
  cacheDirectoryName: "Local Context Forge",
  updaterPolicy: "standard",
  engineeringOnly: false
});

const ENGINEERING_SMOKE_PROFILE: DistributionProfile = Object.freeze({
  name: "engineering-smoke",
  productName: "Local Context Forge Engineering Smoke",
  dataDirectoryName: "Local Context Forge Engineering Smoke",
  cacheDirectoryName: "Local Context Forge Engineering Smoke",
  updaterPolicy: "engineering-disabled",
  engineeringOnly: true
});

export function resolveDistributionProfile(
  name: DistributionProfileName
): DistributionProfile {
  switch (name) {
    case "standard":
      return STANDARD_PROFILE;
    case "engineering-smoke":
      return ENGINEERING_SMOKE_PROFILE;
  }
}

const compiledProfileName: DistributionProfileName =
  typeof __LCF_DISTRIBUTION_PROFILE__ === "undefined"
    ? "standard"
    : __LCF_DISTRIBUTION_PROFILE__;

export const COMPILED_DISTRIBUTION_PROFILE =
  resolveDistributionProfile(compiledProfileName);
