#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(cd -- "${script_dir}/.." && pwd -P)"
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

api_url="${LCF_API_URL:-http://127.0.0.1:$(config_value API_PORT 8000)}"
demo_slug="lcf-demo-sdk"
demo_source="${LCF_DEMO_SOURCE:-}"

for command_name in curl jq; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    printf 'Required command not found: %s\n' "$command_name" >&2
    exit 1
  fi
done

curl --fail --silent --show-error "${api_url}/api/health" >/dev/null

if [[ -z "$demo_source" ]]; then
  if command -v docker >/dev/null 2>&1 \
    && compose_available \
    && compose_run ps --status running --services 2>/dev/null | grep -qx api; then
    demo_source="/examples/demo-python-sdk"
  else
    demo_source="${repo_root}/examples/demo-python-sdk"
  fi
fi

libraries_json="$(curl --fail --silent --show-error \
  "${api_url}/api/libraries?search=${demo_slug}")"
library_id="$(jq -r --arg slug "$demo_slug" \
  'map(select(.slug == $slug)) | .[0].id // empty' <<<"$libraries_json")"

if [[ -z "$library_id" ]]; then
  payload="$(jq -n \
    --arg name "LCF Demo SDK" \
    --arg slug "$demo_slug" \
    --arg source "$demo_source" \
    '{
      name: $name,
      slug: $slug,
      source: $source,
      description: "Small deterministic Python SDK used by Local Context Forge smoke tests."
    }')"
  created="$(curl --fail --silent --show-error \
    -H 'Content-Type: application/json' \
    --data "$payload" \
    "${api_url}/api/libraries")"
  library_id="$(jq -er '.id' <<<"$created")"
  printf 'Created demo library: %s\n' "$(jq -r '.context7_id' <<<"$created")"
else
  printf 'Reusing demo library id: %s\n' "$library_id"
  current_source="$(jq -r --arg id "$library_id" \
    'map(select(.id == $id)) | .[0].source // empty' <<<"$libraries_json")"
  if [[ "$current_source" != "$demo_source" ]]; then
    patch_payload="$(jq -n --arg source "$demo_source" '{source:$source}')"
    curl --fail --silent --show-error \
      -X PATCH \
      -H 'Content-Type: application/json' \
      --data "$patch_payload" \
      "${api_url}/api/libraries/${library_id}" >/dev/null
    printf 'Updated demo source for this runtime: %s\n' "$demo_source"
  fi
fi

published_pages="$(curl --fail --silent --show-error \
  "${api_url}/api/libraries/${library_id}/pages?version=1.0.0")"
if [[ "$(jq -r 'length' <<<"$published_pages")" -gt 0 ]]; then
  printf '%s\n' 'Demo version 1.0.0 is already published; skipping immutable ingest.'
else
  ingest_payload='{"version":"1.0.0","ref":"HEAD","provider":"mock","auto_publish":true}'
  job="$(curl --fail --silent --show-error \
    -H 'Content-Type: application/json' \
    --data "$ingest_payload" \
    "${api_url}/api/libraries/${library_id}/ingest")"
  job_id="$(jq -er '.id' <<<"$job")"
  printf 'Demo ingest job: %s\n' "$job_id"

  deadline=$((SECONDS + 180))
  while ((SECONDS < deadline)); do
    job="$(curl --fail --silent --show-error "${api_url}/api/jobs/${job_id}")"
    status="$(jq -er '.status' <<<"$job")"
    stage="$(jq -r '.stage // "unknown"' <<<"$job")"
    progress="$(jq -r '.progress // 0' <<<"$job")"
    printf '  %-12s %3s%% %s\n' "$stage" "$progress" "$status"
    case "$status" in
      completed) break ;;
      failed)
        jq . <<<"$job" >&2
        exit 1
        ;;
    esac
    sleep 1
  done

  if [[ "$(jq -r '.status' <<<"$job")" != "completed" ]]; then
    printf '%s\n' 'Timed out waiting for demo ingest.' >&2
    exit 1
  fi
fi

query_payload="$(jq -n \
  --arg id "$library_id" \
  '{
    library_id: $id,
    version: "1.0.0",
    query: "How do I create a client with a timeout?",
    limit: 5
  }')"
result="$(curl --fail --silent --show-error \
  -H 'Content-Type: application/json' \
  --data "$query_payload" \
  "${api_url}/api/query")"

printf 'Demo published. Retrieval engine: %s; results: %s\n' \
  "$(jq -r '.engine' <<<"$result")" \
  "$(jq -r '.results | length' <<<"$result")"
printf 'Open the UI at http://127.0.0.1:%s\n' "$(config_value WEB_PORT 8080)"
