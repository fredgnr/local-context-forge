#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(cd -- "${script_dir}/.." && pwd -P)"
native_mode=0
check_only=0

usage() {
  cat <<'EOF'
Usage: ./scripts/macos-bootstrap.sh [--native] [--check]

  --native  Also install native Node/Python/QMD dependencies and project deps.
  --check   Only report missing prerequisites; do not install Homebrew packages.
EOF
}

python_is_supported() {
  command -v python3 >/dev/null 2>&1 \
    && python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 8))'
}

while (($#)); do
  case "$1" in
    --native) native_mode=1 ;;
    --check) check_only=1 ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown option: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [[ "$(uname -s)" != "Darwin" ]]; then
  printf '%s\n' 'This bootstrap targets macOS. Use Docker/WSL instructions on other systems.' >&2
  exit 1
fi

printf 'macOS architecture: %s\n' "$(uname -m)"
if [[ "$(uname -m)" != "arm64" ]]; then
  printf '%s\n' 'Warning: this guide is tuned for Apple Silicon; Intel can still use Compose.' >&2
fi

missing=0
for command_name in git curl tar; do
  if command -v "$command_name" >/dev/null 2>&1; then
    printf 'ok: %s\n' "$command_name"
  else
    printf 'missing: %s\n' "$command_name" >&2
    missing=1
  fi
done

if ((native_mode == 0)); then
  if command -v docker >/dev/null 2>&1; then
    printf '%s\n' 'ok: docker'
    if docker compose version >/dev/null 2>&1; then
      printf '%s\n' 'ok: docker compose v2'
    else
      printf '%s\n' 'missing: docker compose v2 plugin' >&2
      missing=1
    fi
  else
    printf '%s\n' 'missing: docker' >&2
    missing=1
  fi
elif command -v docker >/dev/null 2>&1; then
  printf '%s\n' 'optional: docker is available, but native mode does not require it'
fi

needs_homebrew=$native_mode
for command_name in jq rsync; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    needs_homebrew=1
  fi
done
if ! python_is_supported; then
  needs_homebrew=1
fi

if ! command -v brew >/dev/null 2>&1; then
  if ((needs_homebrew == 1)); then
    printf '%s\n' \
      'missing: Homebrew (needed for jq/python3/rsync or native mode): https://brew.sh' \
      >&2
    missing=1
  fi
elif ((check_only == 0)); then
  if ! command -v jq >/dev/null 2>&1; then
    brew install jq
  fi
  if ! python_is_supported; then
    brew install python
  fi
  if ! command -v rsync >/dev/null 2>&1; then
    brew install rsync
  fi
fi

if command -v brew >/dev/null 2>&1 \
  && brew list --versions node@22 >/dev/null 2>&1; then
  node_bin="$(brew --prefix node@22)/bin"
  export PATH="${node_bin}:${PATH}"
fi

if ((check_only == 1)); then
  for command_name in jq python3 rsync; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
      printf 'missing: %s\n' "$command_name" >&2
      missing=1
    else
      printf 'ok: %s\n' "$command_name"
    fi
  done
  if command -v python3 >/dev/null 2>&1 && ! python_is_supported; then
    printf '%s\n' 'unsupported: Python 3.8+ is required by backup/restore helpers' >&2
    missing=1
  fi
  if ((native_mode == 1)); then
    for command_name in node npm python3 ctags; do
      if command -v "$command_name" >/dev/null 2>&1; then
        printf 'ok: %s\n' "$command_name"
      else
        printf 'missing: %s\n' "$command_name" >&2
        missing=1
      fi
    done
    if [[ -x "${repo_root}/.native/node_modules/.bin/qmd" ]]; then
      printf '%s\n' 'ok: project-local qmd'
    else
      printf '%s\n' 'missing: project-local qmd (run without --check)' >&2
      missing=1
    fi
    if command -v node >/dev/null 2>&1 \
      && [[ "$(node -p 'Number(process.versions.node.split(`.`)[0])')" -lt 22 ]]; then
      printf '%s\n' 'unsupported: Node 22+ is required' >&2
      missing=1
    fi
  fi
  exit "$missing"
fi

for command_name in jq python3 rsync; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    printf 'missing after bootstrap: %s\n' "$command_name" >&2
    missing=1
  fi
done
if command -v python3 >/dev/null 2>&1 && ! python_is_supported; then
  printf '%s\n' 'unsupported after bootstrap: Python 3.8+ is required' >&2
  missing=1
fi

if ((missing == 1)); then
  if ((native_mode == 1)); then
    printf '%s\n' 'Install the reported Git/Homebrew prerequisites, then rerun native bootstrap.' >&2
  else
    printf '%s\n' 'Install the reported Docker/Git/jq prerequisites, then rerun this script.' >&2
  fi
  exit 1
fi

if [[ ! -f "${repo_root}/.env" ]]; then
  cp "${repo_root}/.env.example" "${repo_root}/.env"
  chmod 600 "${repo_root}/.env"
  printf '%s\n' 'Created .env from .env.example (mode 600).'
else
  printf '%s\n' 'Kept existing .env unchanged.'
fi

mkdir -p "${repo_root}/data" "${repo_root}/backups" "${repo_root}/imports"
chmod 700 "${repo_root}/data" "${repo_root}/backups" "${repo_root}/imports"

if ((native_mode == 1)); then
  formulae=(node@22 python@3.12 sqlite universal-ctags jq)
  for formula in "${formulae[@]}"; do
    if brew list --versions "$formula" >/dev/null 2>&1; then
      printf 'ok: Homebrew %s\n' "$formula"
    else
      brew install "$formula"
    fi
  done

  node_bin="$(brew --prefix node@22)/bin"
  python_bin="$(brew --prefix python@3.12)/bin/python3.12"
  export PATH="${node_bin}:${PATH}"

  if [[ "$(node -p 'Number(process.versions.node.split(`.`)[0])')" -lt 22 ]]; then
    printf '%s\n' 'Node 22+ is required for QMD.' >&2
    exit 1
  fi

  npm install \
    --prefix "${repo_root}/.native" \
    --no-audit \
    --no-fund \
    '@tobilu/qmd@2.5.3'
  "${repo_root}/.native/node_modules/.bin/qmd" --version
  "$python_bin" -m venv "${repo_root}/.venv"
  "${repo_root}/.venv/bin/pip" install --upgrade pip
  "${repo_root}/.venv/bin/pip" install \
    -r "${repo_root}/backend/requirements.txt" \
    -r "${repo_root}/mcp/requirements.txt" \
    -r "${repo_root}/backend/requirements-dev.txt"
  "${repo_root}/.venv/bin/pip" install --no-deps --editable "${repo_root}/backend"
  "${repo_root}/.venv/bin/pip" install --no-deps --editable "${repo_root}/mcp"
  (
    cd "${repo_root}/web"
    npm ci
  )
  printf '%s\n' 'Native dependencies installed. Start everything with: make dev-native'
fi

printf '%s\n' 'Bootstrap complete.'
if ((native_mode == 1)); then
  printf '%s\n' 'Next: make dev-native'
else
  printf '%s\n' 'Next: ./install.sh'
fi
