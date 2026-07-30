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
mcp_url="${LCF_MCP_URL:-http://127.0.0.1:$(config_value MCP_PORT 8001)}"
web_url="${LCF_WEB_URL:-http://127.0.0.1:$(config_value WEB_PORT 8080)}"

for command_name in curl jq; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    printf 'Required command not found: %s\n' "$command_name" >&2
    exit 1
  fi
done

check_url() {
  local label="$1"
  local url="$2"
  if curl --fail --silent --show-error --max-time 10 "$url" >/dev/null; then
    printf 'ok: %s (%s)\n' "$label" "$url"
  else
    printf 'failed: %s (%s)\n' "$label" "$url" >&2
    return 1
  fi
}

check_url "api" "${api_url}/api/health"
check_url "mcp" "${mcp_url}/health"
check_url "web" "${web_url}/healthz"

libraries="$(curl --fail --silent --show-error "${api_url}/api/libraries")"
printf 'ok: library list (%s libraries)\n' "$(jq -r 'length' <<<"$libraries")"

demo_id="$(jq -r 'map(select(.slug == "lcf-demo-sdk")) | .[0].id // empty' \
  <<<"$libraries")"
if [[ -n "$demo_id" ]]; then
  query_payload="$(jq -n \
    --arg id "$demo_id" \
    '{library_id:$id,version:"1.0.0",query:"create client timeout",limit:3}')"
  query_result="$(curl --fail --silent --show-error \
    -H 'Content-Type: application/json' \
    --data "$query_payload" \
    "${api_url}/api/query")"
  jq -e '.engine | type == "string"' <<<"$query_result" >/dev/null
  jq -e '.results | type == "array"' <<<"$query_result" >/dev/null
  printf 'ok: demo query (%s engine, %s results)\n' \
    "$(jq -r '.engine' <<<"$query_result")" \
    "$(jq -r '.results | length' <<<"$query_result")"
else
  printf '%s\n' 'skip: demo query (run ./scripts/demo-seed.sh first)'
fi

if command -v docker >/dev/null 2>&1 && compose_available; then
  compose_run ps
fi

printf '%s\n' 'Smoke test passed.'
