This is the formal macOS arm64 desktop release of Local Context Forge.

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
