# Local Context Forge backend

This package is the shared domain engine used by both the legacy HTTP/Docker
deployment and the Electron Python sidecar. The desktop build does not expose
its FastAPI routes on TCP: Electron Main reaches a private Unix-domain-socket
sidecar through an allowlisted IPC proxy. See
[`docs/17-system-design.md`](../docs/17-system-design.md) for the authoritative
topology and [`docs/development/status.md`](../docs/development/status.md) for
what has actually been validated.

## Shared domain behavior

The backend turns a repository into a reviewable, Git-backed API Wiki:

1. Archive an exact Git commit (or hash a plain directory) into an immutable
   source snapshot.
2. Extract a deterministic manifest, symbols, README/tests/examples, and
   source-line evidence. Desktop ingestion disables Ctags; the legacy/native
   deployment can invoke Universal Ctags with `--options=NONE --links=no`, with
   Python AST and conservative regex extraction as the fallback.
3. Generate typed Wiki proposals through the deployment's provider adapter.
   Desktop delegates one bounded provider attempt to Electron Main (Codex by
   default, with Cursor only through explicit preflight/fallback policy).
   Legacy/native operation supports the deterministic `mock` provider, Ollama,
   and its host-runner-backed Codex/Cursor paths.
4. Require at least one source reference and validate it against the exact
   evidence/symbol line ranges visible to that generation, plus snapshot SHA,
   sensitive-path, symlink, path, and line bounds.
5. Write Markdown plus JSON sidecars to a Git repository.
6. Publish and reconcile the lexical QMD corpus. Vector construction remains an
   explicit, forced rebuild; hybrid retrieval is used only for a ready matching
   profile, with built-in lexical fallback.

An explicit version such as `main` or `1.0.0` is materialized as
`<version>+git.<sha12>`. This keeps SQLite pages, Wiki directories, and QMD
collections from different commits physically separate. Supplying the raw
version to the pages API resolves to the latest materialized commit.

Generation receives a bounded copy of the current target Wiki, or the most
recent published Wiki, as `existing_wiki`. It edits that persistent baseline,
but the current source evidence always wins and unsupported old claims must be
removed. Provider adapters deliberately receive bounded single-pass evidence,
not complete map-reduce coverage of every file in a very large monorepo.

The source-reference gate is deliberately narrower than factual verification:
it now enforces generation-time evidence membership, but it does not prove that
cited lines entail a page claim. Human review remains required.

## Source boundaries by deployment

Legacy/native local directory imports are disabled by default. Mount
repositories read-only below `/imports` and set
`LCF_LOCAL_SOURCE_ROOTS=/imports`. Its remote cloning accepts credential-free
HTTPS/443 only and requires an exact `LCF_REMOTE_SOURCE_HOSTS` match (GitHub,
GitLab, and Bitbucket by default). Pre-clone SSH/private repositories into
`/imports` instead of sharing credentials with the service.

Desktop local imports instead begin with the native directory picker and an
opaque Main-owned grant; the Renderer never submits an arbitrary filesystem
path. Desktop remote imports are Main-validated public GitHub HTTPS URLs only.
Its sidecar also disables Ctags. After those deployment-specific admission
checks, both paths use the shared immutable snapshot and evidence rules below.

A local source may never contain the data directory, be contained by it, or
resolve to a filesystem root. A local source discovered as Git must be exactly
the repository top level and contain a standalone `.git` directory. Linked
worktrees/gitdir pointer files, non-regular `.git/config`, `commondir`, alternate
object stores, and metadata/object paths escaping the repository are rejected.
The Dulwich tree export also rejects submodules, Git LFS pointer files, and
NFC/casefold path collisions. For a monorepo subtree, submodule, LFS-backed repository, or
linked worktree, fully check it out first, then export/copy the materialized
worktree or subtree without its parent `.git` metadata into `/imports` and
ingest that as a non-Git directory with `ref=HEAD`. Local non-Git snapshots
compare source-before, copied, and source-after hashes and fail if writers
changed the directory.
Source and service-owned Wiki Git operations use the pinned bundled Dulwich
library, not a target-machine `git` executable. The controlled repository
reader rejects unsafe metadata layouts and does not invoke system/global Git
configuration, credential helpers, interactive prompts, hooks, or external
filters. A standalone local repository's own regular `.git/config` is parsed
only under the explicit source-boundary checks; this is distinct from the
stricter service-owned Wiki canonicalization below. The final snapshot is capped by
`LCF_MAX_SNAPSHOT_FILES`/`LCF_MAX_SNAPSHOT_BYTES`; this is not a hard cap on all
Git object/network transfer during a remote clone.

## Shared persistence, review, and queue semantics

SQLite is the runtime materialization used by the API and MCP. The Wiki Git
repository is a recoverable audit artifact; editing or reverting Git files does
not silently change runtime query results. `lint` detects Markdown, sidecar,
index, and dirty-worktree drift so an administrator can explicitly repair the
materialization. Broken relative links are currently reported as post-publish
lint warnings rather than claimed as a publication gate.

Every service-owned Wiki operation uses the controlled Dulwich boundary and
rewrites `.git/config` to a minimal local configuration with hooks, fsmonitor,
external attributes, and credential helpers disabled. `.git` and its config
must be local regular directories/files, not links. This hardens a restored
Wiki but does not authenticate it: restore only a trusted complete backup,
since a SHA-256 sidecar is not a signature.

Manual proposal approval writes recoverable staged pages, but a version becomes
query-visible/default only after every proposal is published and none is
rejected. A rejected proposal blocks activation. A materialized
source/version is immutable; use a new version label for a revised generation.

Each API or sidecar process uses the SQLite-backed `PersistentJobDispatcher` and
holds a runtime owner lock. Startup and
`POST /api/admin/jobs/recover-orphans` preserve queued rows so the active
dispatcher resumes them in FIFO order. Only `running`/`cancelling` rows whose
owner is gone become `failed`/orphaned; an explicit retry creates a new job.
`POST /api/admin/ingest/drain` blocks new ingest while backup checks the active
set; `resume` opens the gate again. `POST /api/admin/reindex` reconstructs QMD
collection registration from fully published versions only.

## Legacy/native HTTP and QMD operation

The script, HTTP administration routes, purge operation, and environment
variables below describe the legacy/native deployment. Packaged desktop owns
QMD through its Main-managed worker/broker and its Renderer allowlist does not
expose admin, reindex, or library-delete operations.

QMD registration, refresh, removal, and full rebuild share one global
cross-process writer lock. Normal publish calls register a collection and run
a current-config-wide BM25 update only. `scripts/reindex.sh --embed` invokes
the API; `--library/--version` limits which published versions are re-registered,
but QMD's subsequent parameterless `update` and `embed -f` refresh every
collection already registered in that config. The script exits nonzero if any
registration, the global update, or a requested embed fails. Its JSON remains
useful for identifying the failed item. The embedding model is explicitly pinned to
`hf:ggml-org/embeddinggemma-300M-GGUF/embeddinggemma-300M-Q8_0.gguf`.
After changing `QMD_EMBED_MODEL`, restart the same runtime that will serve
queries, request the appropriate registration scope and force the config-wide
rebuild there, and only then enable hybrid. Compose
and native QMD config/cache directories are deliberately separate and must not
be mixed.

`DELETE /api/libraries/{id}?purge=true` removes that library's snapshots,
facts, Wiki, proposal/job control files, and known QMD collections. The response
reports missing paths, filesystem failures, and each QMD removal result. Purge
is application-level cleanup, not secure erase of SSD blocks, backups, model
caches, filesystem snapshots, or other external copies.

Run the legacy/native HTTP service locally:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
LCF_DATA_DIR=./data uvicorn app.main:app --reload --port 8000
```

Health endpoints are available at both `/health` and `/api/health`. Interactive
OpenAPI documentation is at `/docs`.

This command is for backend development and legacy operation. It is not how the
packaged desktop sidecar is launched, authenticated, or supervised.

Legacy/native environment variables (these do not configure the packaged
desktop runtime):

| Variable | Default | Purpose |
| --- | --- | --- |
| `LCF_DATA_DIR` | `./data` | SQLite, snapshots, facts, proposals, and Wiki Git repos |
| `LCF_LOCAL_SOURCE_ROOTS` | empty | `:`-separated read-only local import allowlist; Docker uses `/imports` |
| `LCF_REMOTE_SOURCE_HOSTS` | `github.com,gitlab.com,bitbucket.org` | Exact HTTPS/443 remote Git hostname allowlist |
| `LCF_QMD_ENABLED` | `true` | Enable QMD if the `qmd` executable is installed |
| `LCF_QMD_HYBRID_ENABLED` | `true` | Permit hybrid only when the persisted model/corpus profile is ready; otherwise queries stay lexical |
| `QMD_EMBED_MODEL` | EmbeddingGemma 300M Q8 URI | Exact embedding GGUF used by both rebuild and query |
| `QMD_CONFIG_DIR` | `<data>/qmd/config` | QMD collection metadata |
| `XDG_CACHE_HOME` | `<data>/qmd/cache` | Local QMD models and embeddings |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | Ollama API on the Windows generator or Mac |
| `OLLAMA_MODEL` | `qwen3.5:9b` | Documentation generation model |
| `OLLAMA_NUM_CTX` | `32768` | Ollama context window for bounded single-pass generation |
| `OLLAMA_NUM_PREDICT` | `8192` | Maximum generated tokens |
| `LCF_ENABLE_CODEX_PROVIDER` | `false` | Explicitly opt in to official `codex exec` |
| `LCF_CODEX_STRICT_ISOLATION` | `true` | Ignore user config/rules while running an ephemeral Codex job |
| `LCF_CODEX_FILESYSTEM_ISOLATED` | `false` | Required acknowledgement that Codex runs in a container/VM exposing only evidence |
| `LCF_CODEX_ENV_ALLOWLIST` | empty | Comma-separated non-secret variables allowed into the minimal Codex environment |
| `LCF_CTAGS_BIN` | `ctags` | Universal Ctags executable for deterministic cross-language symbols |
| `LCF_MAX_SNAPSHOT_FILES` | `100000` | Maximum members in one final immutable source snapshot |
| `LCF_MAX_SNAPSHOT_BYTES` | `2147483648` | Maximum regular-file bytes in one final snapshot |
| `LCF_MAX_EVIDENCE_BYTES` | `240000` | Persistent evidence-pack content cap |
| `LCF_MAX_MODEL_PAYLOAD_BYTES` | `100000` | Final hard JSON budget sent to one model request |
| `LCF_MAX_MODEL_EVIDENCE_BYTES` | `30000` | Evidence subset budget inside a model request |
| `LCF_MAX_EXISTING_WIKI_BYTES` | `20000` | Prior-Wiki baseline budget inside a model request |

The legacy/internal direct Codex adapter places only bounded evidence JSON in
its working directory and runs the CLI with `--ephemeral`,
`--ignore-user-config`, `--ignore-rules`, and a read-only sandbox. However, that
CLI sandbox can still read files outside its working directory. The provider
therefore refuses to run until it is placed in a dedicated container/VM exposing
only the evidence and
`LCF_CODEX_FILESYSTEM_ISOLATED=true` is set. It is intended for a single user,
not for sharing a subscription login as a server. Set strict isolation to
`false` only when deliberately supporting an older official CLI that does not
expose the two ignore flags. Packaged desktop does not use these flags or this
adapter; Main creates and supervises the bounded provider attempt.

The Codex child receives a minimal environment (`PATH`, `HOME`, `NO_COLOR`, and
`TERM`) plus explicitly allowed non-secret variables. Cloud, CI, API-key,
credential, token, proxy, and session variables are never forwarded.

The legacy shipped HTTP/API/MCP deployment is a trusted, local, single-user
design. It has no authentication, per-library ACL, or total/per-page Markdown
response byte cap. Query count limits and process timeouts do not make it safe
as a shared service.
