# Update verification key

Formal desktop releases require
`update-metadata-ed25519-public.pem` in this directory and its SHA-256 in
`runtime/update-metadata-key.lock.json`.

Packaging copies both the PEM and that exact lock into
`Contents/Resources/update/`, where the application code signature covers
them. `beforePack` rejects an unprovisioned lock, credential-generation drift,
a digest mismatch, symlink/hardlink input, or a non-Ed25519 key. Main repeats
the lock/pin/key-type check before enabling update checks.

The public key is safe to commit. Its private key must exist only inside the
single versioned protected-Environment secret
`DESKTOP_RELEASE_CREDENTIAL_BUNDLE_BASE64`. Run
`tools/bootstrap_desktop_release_keys.py` on an administrator-controlled
machine to create the independent update key and self-signed code-signing
certificate. The credential bundle and both public locks share one
`credentialGenerationId`. Do not substitute a sample key or commit generated
private material.

Until an administrator provisions and reviews the public key and both lock
files, ordinary source CI remains available and the formal release workflow
fails closed.
