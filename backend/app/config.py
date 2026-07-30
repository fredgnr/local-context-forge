from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class Settings:
    """Runtime settings.

    All mutable state lives below ``data_dir`` so the service can be moved
    between a laptop and Docker without changing application code.
    """

    data_dir: Path
    database_path: Path
    qmd_bin: str = "qmd"
    qmd_enabled: bool = True
    qmd_hybrid_enabled: bool = True
    qmd_config_dir: Path | None = None
    qmd_cache_dir: Path | None = None
    local_source_roots: tuple[Path, ...] = ()
    remote_source_hosts: tuple[str, ...] = (
        "github.com",
        "gitlab.com",
        "bitbucket.org",
    )
    ctags_bin: str = "ctags"
    ctags_enabled: bool = True
    ctags_timeout_seconds: int = 120
    ollama_base_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "qwen3.5:9b"
    ollama_timeout_seconds: int = 600
    ollama_num_ctx: int = 32_768
    ollama_num_predict: int = 8_192
    codex_bin: str = "codex"
    codex_model: str | None = None
    codex_enabled: bool = False
    codex_strict_isolation: bool = True
    codex_filesystem_isolated: bool = False
    codex_env_allowlist: tuple[str, ...] = ()
    runner_dir: Path | None = None
    runner_timeout_seconds: int = 1800
    runner_max_response_bytes: int = 2_097_152
    default_provider: str = "auto"
    worker_poll_seconds: float = 0.5
    worker_shutdown_grace_seconds: float = 10.0
    max_file_bytes: int = 384_000
    max_snapshot_files: int = 100_000
    max_snapshot_bytes: int = 2_147_483_648
    max_evidence_bytes: int = 240_000
    max_existing_wiki_bytes: int = 20_000
    max_model_payload_bytes: int = 100_000
    max_model_manifest_bytes: int = 12_000
    max_model_symbols_bytes: int = 25_000
    max_model_evidence_bytes: int = 30_000
    max_model_symbols: int = 80
    max_model_manifest_files: int = 150
    max_symbols: int = 2_000

    @classmethod
    def from_env(cls) -> Settings:
        data_dir = Path(os.getenv("LCF_DATA_DIR", "./data")).expanduser().resolve()
        database_path = (
            Path(os.getenv("LCF_DATABASE_PATH", str(data_dir / "metadata.sqlite3")))
            .expanduser()
            .resolve()
        )
        source_roots = tuple(
            Path(item.strip()).expanduser().resolve()
            for item in os.getenv("LCF_LOCAL_SOURCE_ROOTS", "").split(os.pathsep)
            if item.strip()
        )
        codex_env_allowlist = tuple(
            item.strip()
            for item in os.getenv("LCF_CODEX_ENV_ALLOWLIST", "").split(",")
            if item.strip()
        )
        remote_source_hosts = tuple(
            item.strip().lower().rstrip(".")
            for item in os.getenv(
                "LCF_REMOTE_SOURCE_HOSTS",
                "github.com,gitlab.com,bitbucket.org",
            ).split(",")
            if item.strip()
        )
        return cls(
            data_dir=data_dir,
            database_path=database_path,
            qmd_bin=os.getenv("LCF_QMD_BIN", "qmd"),
            qmd_enabled=_as_bool(os.getenv("LCF_QMD_ENABLED"), True),
            qmd_hybrid_enabled=_as_bool(
                os.getenv("LCF_QMD_HYBRID_ENABLED"), True
            ),
            qmd_config_dir=Path(
                os.getenv("QMD_CONFIG_DIR", str(data_dir / "qmd" / "config"))
            )
            .expanduser()
            .resolve(),
            qmd_cache_dir=Path(
                os.getenv("XDG_CACHE_HOME", str(data_dir / "qmd" / "cache"))
            )
            .expanduser()
            .resolve(),
            local_source_roots=source_roots,
            remote_source_hosts=remote_source_hosts,
            ctags_bin=os.getenv("LCF_CTAGS_BIN", "ctags"),
            ctags_enabled=_as_bool(os.getenv("LCF_CTAGS_ENABLED"), True),
            ctags_timeout_seconds=int(os.getenv("LCF_CTAGS_TIMEOUT_SECONDS", "120")),
            ollama_base_url=os.getenv(
                "OLLAMA_BASE_URL", "http://host.docker.internal:11434"
            ).rstrip("/"),
            ollama_model=os.getenv("OLLAMA_MODEL", "qwen3.5:9b"),
            ollama_timeout_seconds=int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "600")),
            ollama_num_ctx=int(os.getenv("OLLAMA_NUM_CTX", "32768")),
            ollama_num_predict=int(os.getenv("OLLAMA_NUM_PREDICT", "8192")),
            codex_bin=os.getenv("LCF_CODEX_BIN", "codex"),
            codex_model=os.getenv("LCF_CODEX_MODEL") or None,
            codex_enabled=_as_bool(os.getenv("LCF_ENABLE_CODEX_PROVIDER"), False),
            codex_strict_isolation=_as_bool(
                os.getenv("LCF_CODEX_STRICT_ISOLATION"), True
            ),
            codex_filesystem_isolated=_as_bool(
                os.getenv("LCF_CODEX_FILESYSTEM_ISOLATED"), False
            ),
            codex_env_allowlist=codex_env_allowlist,
            runner_dir=Path(
                os.getenv("LCF_RUNNER_DIR", str(data_dir / "runner"))
            )
            .expanduser()
            .resolve(),
            runner_timeout_seconds=int(
                os.getenv(
                    "LCF_HOST_RUNNER_TIMEOUT_SECONDS",
                    os.getenv("LCF_RUNNER_TIMEOUT_SECONDS", "1800"),
                )
            ),
            runner_max_response_bytes=int(
                os.getenv("LCF_RUNNER_MAX_RESPONSE_BYTES", "2097152")
            ),
            default_provider=os.getenv("LCF_DEFAULT_PROVIDER", "auto")
            .strip()
            .lower(),
            worker_poll_seconds=float(
                os.getenv("LCF_WORKER_POLL_SECONDS", "0.5")
            ),
            worker_shutdown_grace_seconds=float(
                os.getenv("LCF_WORKER_SHUTDOWN_GRACE_SECONDS", "10")
            ),
            max_file_bytes=int(os.getenv("LCF_MAX_FILE_BYTES", "384000")),
            max_snapshot_files=int(
                os.getenv("LCF_MAX_SNAPSHOT_FILES", "100000")
            ),
            max_snapshot_bytes=int(
                os.getenv("LCF_MAX_SNAPSHOT_BYTES", "2147483648")
            ),
            max_evidence_bytes=int(os.getenv("LCF_MAX_EVIDENCE_BYTES", "240000")),
            max_existing_wiki_bytes=int(
                os.getenv("LCF_MAX_EXISTING_WIKI_BYTES", "20000")
            ),
            max_model_payload_bytes=int(
                os.getenv("LCF_MAX_MODEL_PAYLOAD_BYTES", "100000")
            ),
            max_model_manifest_bytes=int(
                os.getenv("LCF_MAX_MODEL_MANIFEST_BYTES", "12000")
            ),
            max_model_symbols_bytes=int(
                os.getenv("LCF_MAX_MODEL_SYMBOLS_BYTES", "25000")
            ),
            max_model_evidence_bytes=int(
                os.getenv("LCF_MAX_MODEL_EVIDENCE_BYTES", "30000")
            ),
            max_model_symbols=int(os.getenv("LCF_MAX_MODEL_SYMBOLS", "80")),
            max_model_manifest_files=int(
                os.getenv("LCF_MAX_MODEL_MANIFEST_FILES", "150")
            ),
            max_symbols=int(os.getenv("LCF_MAX_SYMBOLS", "2000")),
        )

    def ensure_directories(self) -> None:
        paths = [
            self.data_dir,
            self.database_path.parent,
            self.sources_dir,
            self.facts_dir,
            self.proposals_dir,
            self.wiki_dir,
            self.jobs_dir,
            self.locks_dir,
        ]
        if self.qmd_config_dir:
            paths.append(self.qmd_config_dir)
        if self.qmd_cache_dir:
            paths.append(self.qmd_cache_dir)
        paths.extend([self.runner_inbox_dir, self.runner_outbox_dir])
        for path in paths:
            path.mkdir(parents=True, exist_ok=True)

    @property
    def sources_dir(self) -> Path:
        return self.data_dir / "sources"

    @property
    def facts_dir(self) -> Path:
        return self.data_dir / "facts"

    @property
    def proposals_dir(self) -> Path:
        return self.data_dir / "proposals"

    @property
    def wiki_dir(self) -> Path:
        return self.data_dir / "wiki"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def locks_dir(self) -> Path:
        return self.data_dir / "locks"

    @property
    def resolved_runner_dir(self) -> Path:
        return (self.runner_dir or (self.data_dir / "runner")).resolve()

    @property
    def runner_inbox_dir(self) -> Path:
        return self.resolved_runner_dir / "inbox"

    @property
    def runner_outbox_dir(self) -> Path:
        return self.resolved_runner_dir / "outbox"
