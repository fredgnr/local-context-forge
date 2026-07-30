#!/usr/bin/env bash
set -euo pipefail
umask 077

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(cd -- "${script_dir}/.." && pwd -P)"
env_file="${repo_root}/.env"
if [[ -f "${repo_root}/.lcf/runtime.env" ]]; then
  env_file="${repo_root}/.lcf/runtime.env"
fi
archive=""
target=""
replace=0
assume_yes=0
allow_missing_checksum=0
quarantine=""
target_abs=""

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

usage() {
  cat <<'EOF'
Usage:
  ./scripts/restore.sh --archive BACKUP.tar.gz --target DATA_DIR [--replace] [--yes]
                       [--allow-missing-checksum]

The target must match the host path mounted as /data and must not exist or be
empty. --replace moves an
existing target to a timestamped quarantine directory; it does not delete it.
An adjacent .sha256 sidecar is required unless explicitly waived.
EOF
}

while (($#)); do
  case "$1" in
    --archive)
      [[ $# -ge 2 ]] || { printf '%s\n' '--archive requires a value' >&2; exit 2; }
      archive="$2"
      shift
      ;;
    --target)
      [[ $# -ge 2 ]] || { printf '%s\n' '--target requires a value' >&2; exit 2; }
      target="$2"
      shift
      ;;
    --replace) replace=1 ;;
    --yes) assume_yes=1 ;;
    --allow-missing-checksum) allow_missing_checksum=1 ;;
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

if [[ -z "$archive" ]]; then
  usage >&2
  exit 2
fi
if [[ -z "$target" ]]; then
  printf '%s\n' '--target is required; use the host path mounted as /data.' >&2
  usage >&2
  exit 2
fi

if [[ "$archive" != /* ]]; then
  archive="$(cd -- "$(dirname -- "$archive")" && pwd -P)/$(basename -- "$archive")"
fi
if [[ ! -f "$archive" ]]; then
  printf 'Archive not found: %s\n' "$archive" >&2
  exit 1
fi

for command_name in tar awk python3; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    printf 'Required command not found: %s\n' "$command_name" >&2
    exit 1
  fi
done

if [[ "$target" = /* ]]; then
  target_candidate="$target"
else
  target_candidate="${repo_root}/${target#./}"
fi
target_parent="$(dirname -- "$target_candidate")"
target_name="$(basename -- "$target_candidate")"
case "$target_name" in
  ""|"."|"..")
    printf 'Refusing ambiguous restore target: %s\n' "$target_candidate" >&2
    exit 1
    ;;
esac
mkdir -p "$target_parent"
target_parent="$(cd -- "$target_parent" && pwd -P)"
target_abs="${target_parent}/${target_name}"

if [[ "$target_parent" == "/" || "$target_abs" == "/" || "$target_abs" == "$repo_root" ]]; then
  printf 'Refusing unsafe restore target: %s\n' "$target_abs" >&2
  exit 1
fi
if [[ -L "$target_abs" ]]; then
  printf 'Restore target must not be a symlink: %s\n' "$target_abs" >&2
  exit 1
fi

checksum_path="${archive}.sha256"
if [[ -f "$checksum_path" ]]; then
  python3 - "$archive" "$checksum_path" <<'PY'
import hashlib
import hmac
import pathlib
import sys

archive = pathlib.Path(sys.argv[1])
sidecar = pathlib.Path(sys.argv[2])
lines = [line for line in sidecar.read_text(encoding="utf-8").splitlines() if line]
if len(lines) != 1:
    raise SystemExit("checksum sidecar must contain exactly one non-empty line")
line = lines[0]
if (
    len(line) < 67
    or line[64:66] not in {"  ", " *"}
    or line[66:] != archive.name
):
    raise SystemExit("checksum sidecar does not name the selected archive")
expected = line[:64].lower()
if any(character not in "0123456789abcdef" for character in expected):
    raise SystemExit("checksum sidecar does not contain a SHA-256 digest")
digest = hashlib.sha256()
with archive.open("rb") as handle:
    while chunk := handle.read(1024 * 1024):
        digest.update(chunk)
if not hmac.compare_digest(expected, digest.hexdigest()):
    raise SystemExit(f"{archive.name}: FAILED")
print(f"{archive.name}: OK")
PY
else
  if ((allow_missing_checksum == 0)); then
    printf '%s\n' \
      'Adjacent .sha256 file is required; use --allow-missing-checksum only for a separately authenticated archive.' \
      >&2
    exit 1
  fi
  printf '%s\n' 'Warning: checksum requirement explicitly waived; archive authenticity is not verified.' >&2
fi

if command -v docker >/dev/null 2>&1 && compose_available; then
  running="$(compose_run ps --status running --services 2>/dev/null || true)"
  if grep -Eq '^(api|mcp)$' <<<"$running"; then
    printf '%s\n' 'Stop the stack before restore: ./scripts/lcf stop' >&2
    exit 1
  fi
fi
if command -v lsof >/dev/null 2>&1 \
  && lsof -nP -iTCP:"$(config_value API_PORT 8000)" -sTCP:LISTEN \
    >/dev/null 2>&1; then
  printf '%s\n' \
    'An API process is still listening. Stop native Local Context Forge writers before restore.' \
    >&2
  exit 1
fi
if [[ -f "${target_abs}/metadata.sqlite3" ]] \
  && command -v lsof >/dev/null 2>&1 \
  && lsof "${target_abs}/metadata.sqlite3" >/dev/null 2>&1; then
  printf '%s\n' \
    'The target metadata.sqlite3 is still open. Stop native writers before restore.' \
    >&2
  exit 1
fi

# Staging is a sibling of the final target, so the final rename remains on one
# filesystem even when restoring to an encrypted external volume.
stage_dir="$(mktemp -d "${target_parent}/.${target_name}.restore-stage.XXXXXX")"
entry_list="${stage_dir}/archive-entries.txt"
cleanup() {
  status=$?
  trap - EXIT INT TERM
  set +e
  if ((status != 0)) \
    && [[ -n "$quarantine" ]] \
    && [[ ! -e "$target_abs" && ! -L "$target_abs" ]] \
    && [[ -e "$quarantine" ]]; then
    mv -- "$quarantine" "$target_abs"
    printf 'Restore failed; original data moved back to: %s\n' "$target_abs" >&2
  fi
  rm -rf -- "$stage_dir"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
chmod 700 "$stage_dir"

tar -tzf "$archive" >"$entry_list"
if ! awk '
  BEGIN { ok = 1; data = 0 }
  /^\// { ok = 0 }
  /(^|\/)\.\.(\/|$)/ { ok = 0 }
  !/^lcf-backup\// { ok = 0 }
  /^lcf-backup\/data\// { data = 1 }
  END { exit !(ok && data) }
' "$entry_list"; then
  printf '%s\n' 'Unsafe or unsupported archive layout; expected only lcf-backup/... paths.' >&2
  exit 1
fi

python3 - "$archive" "$stage_dir" <<'PY'
import json
import errno
import os
import pathlib
import shutil
import sys
import tarfile
import unicodedata

archive = sys.argv[1]
stage = pathlib.Path(sys.argv[2]).resolve()
root = pathlib.PurePosixPath("lcf-backup")
data_root = pathlib.PurePosixPath("lcf-backup/data")
max_members = 500_000
try:
    max_bytes = int(os.environ.get("LCF_RESTORE_MAX_BYTES", str(100 * 1024**3)))
except ValueError:
    raise SystemExit("LCF_RESTORE_MAX_BYTES must be an integer") from None

def normalized(path: pathlib.PurePosixPath) -> pathlib.PurePosixPath:
    if path.is_absolute():
        raise ValueError("absolute archive path")
    parts = []
    for part in path.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                raise ValueError("path escapes archive root")
            parts.pop()
        else:
            parts.append(part)
    return pathlib.PurePosixPath(*parts)

def is_within(path: pathlib.PurePosixPath, parent: pathlib.PurePosixPath) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False

with tarfile.open(archive, "r:gz") as bundle:
    members = bundle.getmembers()
    if len(members) > max_members:
        raise SystemExit(f"archive has too many members: {len(members)}")
    seen = set()
    portable_seen = {}
    regular_bytes = 0
    normalized_members = []
    regular_paths = set()
    for member in members:
        if "\\" in member.name or "\\" in member.linkname:
            raise SystemExit(f"backslashes are not allowed in archive paths: {member.name}")
        if not (member.isdir() or member.isreg() or member.issym() or member.islnk()):
            raise SystemExit(f"unsupported special archive member: {member.name}")
        if member.mode & 0o6000:
            raise SystemExit(f"setuid/setgid archive member: {member.name}")
        try:
            member_path = normalized(pathlib.PurePosixPath(member.name))
        except ValueError as error:
            raise SystemExit(f"unsafe archive member: {member.name}: {error}") from None
        if not is_within(member_path, root):
            raise SystemExit(f"unsafe archive member: {member.name}")
        if member_path in seen:
            raise SystemExit(f"duplicate archive member: {member.name}")
        seen.add(member_path)
        portable_key = unicodedata.normalize(
            "NFC", member_path.as_posix()
        ).casefold()
        previous_path = portable_seen.get(portable_key)
        if previous_path is not None and previous_path != member_path:
            raise SystemExit(
                "archive paths collide on portable filesystems: "
                f"{previous_path} and {member_path}"
            )
        portable_seen[portable_key] = member_path
        if member.isreg():
            regular_bytes += member.size
            if regular_bytes > max_bytes:
                raise SystemExit(
                    "archive expands beyond LCF_RESTORE_MAX_BYTES "
                    f"({max_bytes} bytes)"
                )
            regular_paths.add(member_path)
        if member.issym():
            if ".git" in member_path.parts:
                raise SystemExit(
                    f"links are forbidden inside service-owned .git metadata: {member.name}"
                )
            if not is_within(member_path, data_root):
                raise SystemExit(f"link outside data tree: {member.name}")
            link = pathlib.PurePosixPath(member.linkname)
            if link.is_absolute():
                raise SystemExit(f"absolute symlink target: {member.name}")
            try:
                target = normalized(member_path.parent / link)
            except ValueError:
                raise SystemExit(
                    f"symlink escapes restored data: {member.name}"
                ) from None
            if not is_within(target, data_root):
                raise SystemExit(f"symlink escapes restored data: {member.name}")
        elif member.islnk():
            if ".git" in member_path.parts:
                raise SystemExit(
                    f"links are forbidden inside service-owned .git metadata: {member.name}"
                )
            if not is_within(member_path, data_root):
                raise SystemExit(f"link outside data tree: {member.name}")
            link = pathlib.PurePosixPath(member.linkname)
            if link.is_absolute():
                raise SystemExit(f"absolute hardlink target: {member.name}")
            try:
                target = normalized(link)
            except ValueError:
                raise SystemExit(
                    f"hardlink escapes restored data: {member.name}"
                ) from None
            if not is_within(target, data_root):
                raise SystemExit(f"hardlink escapes restored data: {member.name}")
        normalized_members.append((member, member_path))

    manifest_name = pathlib.PurePosixPath("lcf-backup/manifest.json")
    manifest_entry = next(
        (
            member
            for member, member_path in normalized_members
            if member_path == manifest_name
        ),
        None,
    )
    if manifest_entry is None or not manifest_entry.isreg() or manifest_entry.size > 1_000_000:
        raise SystemExit("backup manifest is missing or invalid")
    manifest_handle = bundle.extractfile(manifest_entry)
    if manifest_handle is None:
        raise SystemExit("backup manifest cannot be read")
    try:
        manifest = json.loads(manifest_handle.read().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise SystemExit("backup manifest is not valid UTF-8 JSON") from None
    if manifest.get("format") != "local-context-forge-backup-v1":
        raise SystemExit("unsupported backup manifest format")

    directories = sorted(
        (
            (member, member_path)
            for member, member_path in normalized_members
            if member.isdir()
        ),
        key=lambda item: len(item[1].parts),
    )
    for _member, member_path in directories:
        destination = stage / member_path.as_posix()
        destination.mkdir(parents=True, exist_ok=True)

    for member, member_path in normalized_members:
        if not member.isreg():
            continue
        destination = stage / member_path.as_posix()
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = bundle.extractfile(member)
        if source is None:
            raise SystemExit(f"cannot read archive member: {member.name}")
        try:
            with destination.open("xb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
                output.flush()
                os.fsync(output.fileno())
        except FileExistsError:
            raise SystemExit(
                f"archive path collides with an existing directory: {member.name}"
            ) from None
        if destination.stat().st_size != member.size:
            raise SystemExit(f"archive member size mismatch: {member.name}")
        destination.chmod(member.mode & 0o777)

    for member, member_path in normalized_members:
        if not member.issym():
            continue
        destination = stage / member_path.as_posix()
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() or destination.is_symlink():
            raise SystemExit(f"symlink path collision: {member.name}")
        os.symlink(member.linkname, destination)

    pending_hardlinks = [
        (member, member_path)
        for member, member_path in normalized_members
        if member.islnk()
    ]
    while pending_hardlinks:
        deferred = []
        progressed = False
        for member, member_path in pending_hardlinks:
            target_path = normalized(pathlib.PurePosixPath(member.linkname))
            target = stage / target_path.as_posix()
            destination = stage / member_path.as_posix()
            if target_path not in regular_paths and not target.exists():
                deferred.append((member, member_path))
                continue
            if not target.is_file() or target.is_symlink():
                raise SystemExit(f"invalid hardlink target: {member.name}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() or destination.is_symlink():
                raise SystemExit(f"hardlink path collision: {member.name}")
            os.link(target, destination)
            regular_paths.add(member_path)
            progressed = True
        if deferred and not progressed:
            raise SystemExit("hardlink cycle or missing hardlink target")
        pending_hardlinks = deferred

    for member, member_path in sorted(
        directories, key=lambda item: len(item[1].parts), reverse=True
    ):
        destination = stage / member_path.as_posix()
        destination.chmod(member.mode & 0o777)
        descriptor = os.open(destination, os.O_RDONLY)
        try:
            try:
                os.fsync(descriptor)
            except OSError as error:
                if error.errno not in {errno.EINVAL, errno.ENOTSUP}:
                    raise
        finally:
            os.close(descriptor)
PY

directory_has_entries() (
  shopt -s nullglob dotglob
  entries=("$1"/*)
  ((${#entries[@]} > 0))
)

target_nonempty=0
if [[ -d "$target_abs" ]] && directory_has_entries "$target_abs"; then
  target_nonempty=1
elif [[ -e "$target_abs" && ! -d "$target_abs" ]]; then
  target_nonempty=1
fi

if ((target_nonempty == 1 && replace == 0)); then
  printf 'Target is not empty: %s\nUse --replace to move it to quarantine first.\n' "$target_abs" >&2
  exit 1
fi

if ((target_nonempty == 1 && assume_yes == 0)); then
  if [[ ! -t 0 ]]; then
    printf '%s\n' '--replace in non-interactive mode also requires --yes.' >&2
    exit 1
  fi
  printf 'Move existing %s to quarantine and restore? [y/N] ' "$target_abs"
  read -r answer
  case "$answer" in
    y|Y|yes|YES) ;;
    *) printf '%s\n' 'Restore cancelled.'; exit 1 ;;
  esac
fi

restored_data="${stage_dir}/lcf-backup/data"
if [[ ! -d "$restored_data" ]]; then
  printf '%s\n' 'Archive does not contain lcf-backup/data.' >&2
  exit 1
fi

if [[ -e "$target_abs" ]]; then
  if ((target_nonempty == 1)); then
    quarantine="${target_abs}.quarantine.$(date -u '+%Y%m%dT%H%M%SZ')"
    if [[ -e "$quarantine" || -L "$quarantine" ]]; then
      printf 'Refusing to overwrite an existing quarantine path: %s\n' \
        "$quarantine" >&2
      exit 1
    fi
    mv -- "$target_abs" "$quarantine"
    printf 'Existing data moved to: %s\n' "$quarantine"
  else
    rmdir "$target_abs"
  fi
fi

if ! mv -- "$restored_data" "$target_abs"; then
  printf '%s\n' 'Atomic restore rename failed.' >&2
  exit 1
fi
chmod 700 "$target_abs"
python3 - "$target_abs" "$target_parent" <<'PY'
import os
import errno
import sys

for path in sys.argv[1:]:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        try:
            os.fsync(descriptor)
        except OSError as error:
            if error.errno not in {errno.EINVAL, errno.ENOTSUP}:
                raise
    finally:
        os.close(descriptor)
PY
printf 'Restored data to: %s\n' "$target_abs"
printf '%s\n' 'Next: ./scripts/lcf start'
