#!/usr/bin/env bash
set -euo pipefail
umask 077

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(cd -- "${script_dir}/.." && pwd -P)"
timestamp="$(date -u '+%Y%m%dT%H%M%SZ')"
env_file="${repo_root}/.env"
if [[ -f "${repo_root}/.lcf/runtime.env" ]]; then
  env_file="${repo_root}/.lcf/runtime.env"
fi

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

compose_available() {
  local context
  context="$(config_value LCF_DOCKER_CONTEXT "")"
  if [[ -n "$context" ]]; then
    docker --context "$context" compose version >/dev/null 2>&1
  else
    docker compose version >/dev/null 2>&1
  fi
}

compose_run() {
  local context
  context="$(config_value LCF_DOCKER_CONTEXT "")"
  if [[ -n "$context" ]]; then
    docker --context "$context" compose \
      --project-directory "$repo_root" --env-file "$env_file" \
      -f "${repo_root}/docker-compose.yml" "$@"
  else
    (
      cd "$repo_root"
      docker compose "$@"
    )
  fi
}

data_setting="$(config_value LOCAL_DATA_DIR ./data)"
if [[ "$data_setting" = /* ]]; then
  data_dir="$data_setting"
else
  data_dir="${repo_root}/${data_setting#./}"
fi

if [[ ! -d "$data_dir" ]]; then
  printf 'Data directory does not exist: %s\n' "$data_dir" >&2
  exit 1
fi
data_dir="$(cd -- "$data_dir" && pwd -P)"

if [[ "$data_dir" == "/" || "$data_dir" == "$repo_root" ]]; then
  printf 'Refusing unsafe data directory: %s\n' "$data_dir" >&2
  exit 1
fi

backup_setting="$(config_value BACKUP_DIR "${repo_root}/backups")"
if [[ "$backup_setting" = /* ]]; then
  backup_dir="$backup_setting"
else
  backup_dir="${repo_root}/${backup_setting#./}"
fi
mkdir -p "$backup_dir"
backup_dir="$(cd -- "$backup_dir" && pwd -P)"
case "${backup_dir}/" in
  "${data_dir}/"*)
    printf 'Backup directory must not be inside the data directory: %s\n' "$backup_dir" >&2
    exit 1
    ;;
esac

for command_name in curl python3 rsync tar; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    printf 'Required command not found: %s\n' "$command_name" >&2
    exit 1
  fi
done
if ! command -v shasum >/dev/null 2>&1 \
  && ! command -v sha256sum >/dev/null 2>&1; then
  printf '%s\n' 'No SHA-256 tool found; refusing to create an unverifiable backup.' >&2
  exit 1
fi

stop_timeout="$(config_value LCF_BACKUP_STOP_TIMEOUT_SECONDS 3600)"
if ! [[ "$stop_timeout" =~ ^[1-9][0-9]*$ ]]; then
  printf 'LCF_BACKUP_STOP_TIMEOUT_SECONDS must be a positive integer: %s\n' \
    "$stop_timeout" >&2
  exit 1
fi

lock_dir="${backup_dir}/.lcf-backup.lock"
if ! mkdir "$lock_dir" 2>/dev/null; then
  printf 'Another backup appears to be running: %s\n' "$lock_dir" >&2
  exit 1
fi
trap 'rmdir "$lock_dir" 2>/dev/null || true' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Keep the sensitive uncompressed staging copy on the operator-selected backup
# filesystem, not the system temporary directory. BACKUP_DIR should therefore
# be an encrypted, access-controlled volume with sufficient free space.
stage_dir="$(mktemp -d "${backup_dir}/.lcf-backup-stage.XXXXXX")"
stopped_services=()
api_drained=0
api_url="${LCF_API_URL:-http://127.0.0.1:$(config_value API_PORT 8000)}"
archive_partial=""
checksum_partial=""

cleanup() {
  status=$?
  trap - EXIT INT TERM
  set +e
  if [[ -n "$archive_partial" ]]; then
    rm -f -- "$archive_partial"
  fi
  if [[ -n "$checksum_partial" ]]; then
    rm -f -- "$checksum_partial"
  fi
  rm -rf -- "$stage_dir"
  rmdir "$lock_dir" 2>/dev/null
  if ((api_drained == 1)); then
    curl --fail --silent --show-error \
      -X POST "${api_url}/api/admin/ingest/resume" >/dev/null 2>&1
  fi
  if ((${#stopped_services[@]})); then
    compose_run start "${stopped_services[@]}" >/dev/null
    printf 'Restarted services: %s\n' "${stopped_services[*]}"
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if command -v docker >/dev/null 2>&1 && compose_available; then
  while IFS= read -r service_name; do
    case "$service_name" in
      api|mcp) stopped_services+=("$service_name") ;;
    esac
  done < <(compose_run ps --status running --services 2>/dev/null)
  if printf '%s\n' "${stopped_services[@]}" | grep -qx api; then
    # First reconcile interrupted running/cancelling tasks from a previous
    # crash. Durable queued rows are preserved. Then atomically stop this API
    # process from accepting new jobs before checking the active set.
    curl --fail --silent --show-error \
      -X POST "${api_url}/api/admin/jobs/recover-orphans" >/dev/null
    drain_response="$(
      curl --fail --silent --show-error \
        -X POST "${api_url}/api/admin/ingest/drain"
    )"
    api_drained=1
    active_count="$(
      python3 -c \
        'import json,sys; print(int(json.load(sys.stdin)["active_count"]))' \
        <<<"$drain_response"
    )"
    if ((active_count != 0)); then
      printf 'Refusing backup while %s ingest job(s) are active:\n' \
        "$active_count" >&2
      python3 -c '
import json
import sys
for job in json.load(sys.stdin).get("active_jobs", []):
    print(f"  {job.get('\''id'\'')}  {job.get('\''status'\'')}  {job.get('\''stage'\'')}", file=sys.stderr)
' <<<"$drain_response"
      printf '%s\n' 'Wait for terminal states, then rerun the backup.' >&2
      exit 1
    fi
  fi
  if ((${#stopped_services[@]})); then
    printf 'Pausing writers for a consistent backup: %s\n' "${stopped_services[*]}"
    compose_run stop --timeout "$stop_timeout" "${stopped_services[@]}"
  fi
fi

database_path="${data_dir}/metadata.sqlite3"
if command -v lsof >/dev/null 2>&1 \
  && lsof -nP -iTCP:"$(config_value API_PORT 8000)" -sTCP:LISTEN >/dev/null 2>&1; then
  printf '%s\n' 'An API process is still listening. Stop native Local Context Forge writers and rerun.' >&2
  exit 1
fi
if [[ -f "$database_path" ]] && command -v lsof >/dev/null 2>&1; then
  if lsof "$database_path" >/dev/null 2>&1; then
    printf '%s\n' 'A non-Compose process still has metadata.sqlite3 open. Stop native API/QMD writers and rerun.' >&2
    exit 1
  fi
fi

archive_root="${stage_dir}/lcf-backup"
mkdir -p "${archive_root}/data"

rsync -aH \
  --exclude '/tmp/' \
  --exclude '/qmd/cache/' \
  --exclude '/qmd/native-cache/' \
  "$data_dir/" "${archive_root}/data/"

project_commit="unversioned"
if git -C "$repo_root" rev-parse --verify HEAD >/dev/null 2>&1; then
  project_commit="$(git -C "$repo_root" rev-parse HEAD)"
fi

cat >"${archive_root}/manifest.json" <<EOF
{
  "format": "local-context-forge-backup-v1",
  "created_at": "${timestamp}",
  "project_commit": "${project_commit}",
  "data_directory": "/data",
  "excluded": ["tmp", "qmd/cache", "qmd/native-cache"],
  "confidentiality": "Contains complete accepted source snapshots; store only on encrypted, access-controlled media."
}
EOF

archive_name="lcf-backup-${timestamp}.tar.gz"
archive_path="${backup_dir}/${archive_name}"
checksum_path="${archive_path}.sha256"
if [[ -e "$archive_path" || -e "$checksum_path" ]]; then
  printf 'Refusing to overwrite an existing backup: %s\n' "$archive_path" >&2
  exit 1
fi
archive_partial="${backup_dir}/.${archive_name}.partial.$$"
checksum_partial="${backup_dir}/.${archive_name}.sha256.partial.$$"
tar -C "$stage_dir" -czf "$archive_partial" lcf-backup

if command -v shasum >/dev/null 2>&1; then
  digest="$(shasum -a 256 "$archive_partial" | awk '{print $1}')"
else
  digest="$(sha256sum "$archive_partial" | awk '{print $1}')"
fi
printf '%s  %s\n' "$digest" "$archive_name" >"$checksum_partial"
chmod 600 "$archive_partial" "$checksum_partial"
python3 - "$archive_partial" "$checksum_partial" "$backup_dir" <<'PY'
import os
import pathlib
import sys

for value in sys.argv[1:3]:
    with pathlib.Path(value).open("rb") as handle:
        os.fsync(handle.fileno())
directory = os.open(sys.argv[3], os.O_RDONLY)
try:
    os.fsync(directory)
finally:
    os.close(directory)
PY
# Publish the sidecar first: an interruption can leave a harmless orphan
# sidecar, but never a formally named archive without its checksum.
mv -- "$checksum_partial" "$checksum_path"
checksum_partial=""
mv -- "$archive_partial" "$archive_path"
archive_partial=""
python3 - "$backup_dir" <<'PY'
import os
import errno
import sys

directory = os.open(sys.argv[1], os.O_RDONLY)
try:
    try:
        os.fsync(directory)
    except OSError as error:
        if error.errno not in {errno.EINVAL, errno.ENOTSUP}:
            raise
finally:
    os.close(directory)
PY

printf 'Backup created: %s\n' "$archive_path"
printf 'Checksum: %s.sha256\n' "$archive_path"
printf '%s\n' 'Sensitive: this archive contains complete source snapshots. Store it encrypted.'
