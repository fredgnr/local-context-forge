#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(cd -- "${script_dir}/.." && pwd -P)"
log_dir=""
pids=()
tail_pid=""
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

api_port="$(config_value API_PORT 8000)"
mcp_port="$(config_value MCP_PORT 8001)"
web_port="$(config_value VITE_PORT "$(config_value WEB_PORT 8080)")"
ollama_base_url="$(config_value OLLAMA_BASE_URL http://host.docker.internal:11434)"
ollama_model="$(config_value OLLAMA_MODEL qwen3.5:9b)"
ollama_timeout="$(config_value OLLAMA_TIMEOUT_SECONDS 600)"
ollama_num_ctx="$(config_value OLLAMA_NUM_CTX 32768)"
ollama_num_predict="$(config_value OLLAMA_NUM_PREDICT 8192)"
qmd_enabled="$(config_value LCF_QMD_ENABLED true)"
qmd_hybrid_enabled="$(config_value LCF_QMD_HYBRID_ENABLED true)"
qmd_embed_model="$(config_value QMD_EMBED_MODEL hf:ggml-org/embeddinggemma-300M-GGUF/embeddinggemma-300M-Q8_0.gguf)"
ctags_enabled="$(config_value LCF_CTAGS_ENABLED true)"
ctags_timeout="$(config_value LCF_CTAGS_TIMEOUT_SECONDS 120)"
codex_enabled="$(config_value LCF_ENABLE_CODEX_PROVIDER false)"
backend_timeout="$(config_value BACKEND_TIMEOUT_SECONDS 660)"
max_file_bytes="$(config_value LCF_MAX_FILE_BYTES 384000)"
max_snapshot_files="$(config_value LCF_MAX_SNAPSHOT_FILES 100000)"
max_snapshot_bytes="$(config_value LCF_MAX_SNAPSHOT_BYTES 2147483648)"
max_evidence_bytes="$(config_value LCF_MAX_EVIDENCE_BYTES 240000)"
max_existing_wiki_bytes="$(config_value LCF_MAX_EXISTING_WIKI_BYTES 20000)"
max_model_payload_bytes="$(config_value LCF_MAX_MODEL_PAYLOAD_BYTES 100000)"
max_model_manifest_bytes="$(config_value LCF_MAX_MODEL_MANIFEST_BYTES 12000)"
max_model_symbols_bytes="$(config_value LCF_MAX_MODEL_SYMBOLS_BYTES 25000)"
max_model_evidence_bytes="$(config_value LCF_MAX_MODEL_EVIDENCE_BYTES 30000)"
max_model_symbols="$(config_value LCF_MAX_MODEL_SYMBOLS 80)"
max_model_manifest_files="$(config_value LCF_MAX_MODEL_MANIFEST_FILES 150)"
max_symbols="$(config_value LCF_MAX_SYMBOLS 2000)"
remote_source_hosts="$(config_value LCF_REMOTE_SOURCE_HOSTS github.com,gitlab.com,bitbucket.org)"

if command -v brew >/dev/null 2>&1 \
  && brew list --versions node@22 >/dev/null 2>&1; then
  native_node_bin="$(brew --prefix node@22)/bin"
  export PATH="${repo_root}/.native/node_modules/.bin:${native_node_bin}:${PATH}"
else
  export PATH="${repo_root}/.native/node_modules/.bin:${PATH}"
fi

for path in \
  "${repo_root}/.venv/bin/uvicorn" \
  "${repo_root}/.venv/bin/python" \
  "${repo_root}/.native/node_modules/.bin/qmd" \
  "${repo_root}/web/node_modules"; do
  if [[ ! -e "$path" ]]; then
    printf 'Native dependency missing: %s\nRun ./scripts/macos-bootstrap.sh --native first.\n' "$path" >&2
    exit 1
  fi
done

for command_name in node npm qmd; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    printf 'Native command missing: %s\nRun ./scripts/macos-bootstrap.sh --native first.\n' \
      "$command_name" >&2
    exit 1
  fi
done
if [[ "$(node -p 'Number(process.versions.node.split(`.`)[0])')" -lt 22 ]]; then
  printf '%s\n' 'Node 22+ is required. Rerun ./scripts/macos-bootstrap.sh --native.' >&2
  exit 1
fi

for port in "$api_port" "$mcp_port" "$web_port"; do
  if command -v lsof >/dev/null 2>&1 \
    && lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    printf 'Port %s is already in use. Stop the existing service or change its port variable.\n' "$port" >&2
    exit 1
  fi
done

mkdir -p \
  "${repo_root}/data/qmd/native-config" \
  "${repo_root}/data/qmd/native-cache" \
  "${repo_root}/imports"
log_dir="$(mktemp -d "${TMPDIR:-/tmp}/lcf-dev-native.XXXXXX")"

cleanup() {
  status=$?
  trap - EXIT INT TERM
  set +e
  if [[ -n "$tail_pid" ]]; then
    kill "$tail_pid" 2>/dev/null
  fi
  for pid in "${pids[@]:-}"; do
    if command -v pkill >/dev/null 2>&1; then
      pkill -TERM -P "$pid" 2>/dev/null
    fi
    kill "$pid" 2>/dev/null
  done
  for pid in "${pids[@]:-}"; do
    wait "$pid" 2>/dev/null
  done
  printf 'Native services stopped. Logs kept at %s\n' "$log_dir"
  exit "$status"
}
trap cleanup EXIT INT TERM

(
  cd "${repo_root}/backend"
  exec env \
    LCF_DATA_DIR="${repo_root}/data" \
    LCF_LOCAL_SOURCE_ROOTS="${repo_root}/examples:${repo_root}/imports" \
    LCF_REMOTE_SOURCE_HOSTS="$remote_source_hosts" \
    LCF_QMD_ENABLED="$qmd_enabled" \
    LCF_QMD_HYBRID_ENABLED="$qmd_hybrid_enabled" \
    QMD_EMBED_MODEL="$qmd_embed_model" \
    LCF_CTAGS_ENABLED="$ctags_enabled" \
    LCF_CTAGS_TIMEOUT_SECONDS="$ctags_timeout" \
    LCF_ENABLE_CODEX_PROVIDER="$codex_enabled" \
    QMD_CONFIG_DIR="${repo_root}/data/qmd/native-config" \
    XDG_CACHE_HOME="${repo_root}/data/qmd/native-cache" \
    OLLAMA_BASE_URL="$ollama_base_url" \
    OLLAMA_MODEL="$ollama_model" \
    OLLAMA_TIMEOUT_SECONDS="$ollama_timeout" \
    OLLAMA_NUM_CTX="$ollama_num_ctx" \
    OLLAMA_NUM_PREDICT="$ollama_num_predict" \
    LCF_MAX_FILE_BYTES="$max_file_bytes" \
    LCF_MAX_SNAPSHOT_FILES="$max_snapshot_files" \
    LCF_MAX_SNAPSHOT_BYTES="$max_snapshot_bytes" \
    LCF_MAX_EVIDENCE_BYTES="$max_evidence_bytes" \
    LCF_MAX_EXISTING_WIKI_BYTES="$max_existing_wiki_bytes" \
    LCF_MAX_MODEL_PAYLOAD_BYTES="$max_model_payload_bytes" \
    LCF_MAX_MODEL_MANIFEST_BYTES="$max_model_manifest_bytes" \
    LCF_MAX_MODEL_SYMBOLS_BYTES="$max_model_symbols_bytes" \
    LCF_MAX_MODEL_EVIDENCE_BYTES="$max_model_evidence_bytes" \
    LCF_MAX_MODEL_SYMBOLS="$max_model_symbols" \
    LCF_MAX_MODEL_MANIFEST_FILES="$max_model_manifest_files" \
    LCF_MAX_SYMBOLS="$max_symbols" \
    LCF_CORS_ORIGINS="http://127.0.0.1:${web_port},http://localhost:${web_port}" \
    "${repo_root}/.venv/bin/uvicorn" \
      app.main:app \
      --host 127.0.0.1 \
      --port "$api_port" \
      --reload
) >"${log_dir}/api.log" 2>&1 &
pids+=("$!")

(
  cd "${repo_root}/mcp"
  exec env \
    BACKEND_URL="http://127.0.0.1:${api_port}" \
    BACKEND_TIMEOUT_SECONDS="$backend_timeout" \
    MCP_TRANSPORT=streamable-http \
    MCP_HOST=127.0.0.1 \
    MCP_PORT="$mcp_port" \
    MCP_PATH=/mcp \
    "${repo_root}/.venv/bin/python" -m mcp_server.server
) >"${log_dir}/mcp.log" 2>&1 &
pids+=("$!")

(
  cd "${repo_root}/web"
  exec env \
    VITE_DEV_API_TARGET="http://127.0.0.1:${api_port}" \
    npm run dev -- --host 127.0.0.1 --port "$web_port"
) >"${log_dir}/web.log" 2>&1 &
pids+=("$!")

printf 'Starting native API, MCP and Web. Logs: %s\n' "$log_dir"
tail -n +1 -F \
  "${log_dir}/api.log" \
  "${log_dir}/mcp.log" \
  "${log_dir}/web.log" &
tail_pid="$!"

ready_deadline=$((SECONDS + 90))
ready=0
while ((SECONDS < ready_deadline)); do
  for pid in "${pids[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      set +e
      wait "$pid"
      child_status=$?
      set -e
      exit "$child_status"
    fi
  done
  if curl --fail --silent "http://127.0.0.1:${api_port}/api/health" >/dev/null 2>&1 \
    && curl --fail --silent "http://127.0.0.1:${mcp_port}/health" >/dev/null 2>&1 \
    && curl --fail --silent "http://127.0.0.1:${web_port}/" >/dev/null 2>&1; then
    printf '\nReady: UI http://127.0.0.1:%s · API :%s · MCP :%s/mcp\n' \
      "$web_port" "$api_port" "$mcp_port"
    printf '%s\n' 'Press Ctrl-C to stop all three processes.'
    ready=1
    break
  fi
  sleep 1
done

if ((ready == 0)); then
  printf '%s\n' 'Timed out waiting for native services; inspect the logs above.' >&2
  exit 1
fi

# macOS ships Bash 3.2 without `wait -n`, so monitor children portably.
while :; do
  for pid in "${pids[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      set +e
      wait "$pid"
      child_status=$?
      set -e
      exit "$child_status"
    fi
  done
  sleep 1
done
