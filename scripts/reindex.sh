#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(cd -- "${script_dir}/.." && pwd -P)"
env_file="${repo_root}/.env"
if [[ -f "${repo_root}/.lcf/runtime.env" ]]; then
  env_file="${repo_root}/.lcf/runtime.env"
fi
embed=false
library_id=""
version=""

usage() {
  cat <<'EOF'
Usage: ./scripts/reindex.sh [--embed] [--library ID [--version VERSION]]

Registers the selected fully published Wiki versions with QMD, then refreshes
the complete QMD config once. --embed force-rebuilds embeddings/reranker data
for every registered collection in that config and may download models.
EOF
}

config_value() {
  local key="$1"
  local fallback="$2"
  local current=""
  local from_file=""
  if current="$(printenv "$key" 2>/dev/null)" && [[ -n "$current" ]]; then
    printf '%s' "$current"
    return
  fi
  if [[ -f "$env_file" ]]; then
    from_file="$(awk -v wanted="$key" '
      index($0, wanted "=") == 1 {
        sub(/^[^=]*=/, "")
        print
        exit
      }
    ' "$env_file")"
  fi
  printf '%s' "${from_file:-$fallback}"
}

while (($#)); do
  case "$1" in
    --embed) embed=true ;;
    --library)
      [[ $# -ge 2 ]] || { printf '%s\n' '--library requires a value' >&2; exit 2; }
      library_id="$2"
      shift
      ;;
    --version)
      [[ $# -ge 2 ]] || { printf '%s\n' '--version requires a value' >&2; exit 2; }
      version="$2"
      shift
      ;;
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

if [[ -n "$version" && -z "$library_id" ]]; then
  printf '%s\n' '--version requires --library' >&2
  exit 2
fi
for command_name in curl python3; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    printf 'Required command not found: %s\n' "$command_name" >&2
    exit 1
  fi
done

api_url="${LCF_API_URL:-http://127.0.0.1:$(config_value API_PORT 8000)}"
request_url="${api_url}/api/admin/reindex?embed=${embed}"
if [[ -n "$library_id" ]]; then
  encoded_library="$(
    python3 -c 'import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' \
      "$library_id"
  )"
  request_url="${request_url}&library_id=${encoded_library}"
fi
if [[ -n "$version" ]]; then
  encoded_version="$(
    python3 -c 'import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' \
      "$version"
  )"
  request_url="${request_url}&version=${encoded_version}"
fi

response="$(
  curl --fail --silent --show-error -X POST "$request_url"
)"
python3 -m json.tool <<<"$response"
if ! EMBED_REQUESTED="$embed" python3 -c '
import json
import os
import sys
payload = json.load(sys.stdin)
registrations = payload.get("registrations")
refresh = payload.get("refresh")
valid = (
    isinstance(registrations, list)
    and len(registrations) == payload.get("published_versions")
    and all(item.get("registered") is True for item in registrations)
    and isinstance(refresh, dict)
    and refresh.get("updated") is True
)
if os.environ.get("EMBED_REQUESTED") == "true":
    valid = valid and refresh.get("embedded") is True
raise SystemExit(0 if valid else 1)
' <<<"$response"; then
  printf '%s\n' \
    'QMD registration, refresh, or requested embedding did not complete successfully.' >&2
  exit 1
fi
