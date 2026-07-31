This is the formal macOS arm64 desktop release of Local Context Forge.

Creating a Draft Release is only a candidate-build checkpoint. Public
publication requires a protected `workflow_dispatch --ref main` after physical
testing, bound to the exact `release-manifest.json` SHA-256. The release tag is
data for the trusted-main verifier, not its checkout ref. An already-published
pre-state or any post-publication attestation, immutable-state, tag, Release
ID, notes, or asset mismatch is a release security incident, not an
idempotent-success case. Immediately before publication, promotion order and
latest-release status are recalculated against a freshly fetched `origin/main`
comparison ref so parallel tag promotions cannot make an older version latest.

The DMG and ZIP use the project's reviewed self-signed certificate. They are
not Apple-notarized, so macOS may display an unidentified-developer warning.
Verify `SHA256SUMS`, `release-manifest.json`, and the detached Ed25519 update
manifest before installation.

Install only the DMG; the ZIP and updater metadata are release-client assets,
not manual installation entry points. See the
[Electron desktop installation guide](https://github.com/fredgnr/local-context-forge/blob/main/docs/16-electron-desktop-guide.md)
for checksum, Applications, and macOS Privacy & Security steps.

Automatic update application remains disabled until the physical
`VAL-UPDATE-001` upgrade gate has passed.
