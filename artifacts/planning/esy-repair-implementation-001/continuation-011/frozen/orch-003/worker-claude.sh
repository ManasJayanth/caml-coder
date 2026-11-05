#!/bin/bash
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
. "$here/worker-common.sh"; . "$here/env.sh"
[[ $# -eq 4 ]] || die "usage: ROLE WORKSPACE PROMPT PROFILE"
role=$1; ws=$2; prompt=$3; profile=$4
abs_dir "$ws" workspace; abs_file "$prompt" prompt; abs_file "$profile" profile
abs_exe "${SANDBOX_EXEC:-}" SANDBOX_EXEC
case "$role" in
  review|plan)
    case "${REVIEW_BACKEND:-codex}" in
      codex) exec /bin/bash "$here/worker-codex.sh" "$role" "$ws" "$prompt" "$profile" ;;
      fable) : "${CLAUDE_BIN:?}"; : "${CLAUDE_FABLE_MODEL:?}"; abs_exe "$CLAUDE_BIN" CLAUDE_BIN
             cd "$ws"
             exec "$SANDBOX_EXEC" -f "$profile" "$CLAUDE_BIN" --print --model "$CLAUDE_FABLE_MODEL" \
               --output-format json --no-session-persistence --restricted --setting-sources "" \
               --strict-mcp-config --mcp-config '{"mcpServers":{}}' --permission-mode default \
               --tools "" < "$prompt" ;;
      *) die "REVIEW_BACKEND must be codex|fable" ;;
    esac ;;
  code)
    : "${CLAUDE_CODING_MODEL:?coding via Claude not approved}"; : "${CLAUDE_BIN:?}"; abs_exe "$CLAUDE_BIN" CLAUDE_BIN
    cd "$ws"
    exec "$SANDBOX_EXEC" -f "$profile" "$CLAUDE_BIN" --print --model "$CLAUDE_CODING_MODEL" --output-format json \
      --no-session-persistence --restricted --setting-sources "" --strict-mcp-config \
      --mcp-config '{"mcpServers":{}}' --permission-mode acceptEdits --tools "Read,Edit,Write,Glob,Grep" < "$prompt" ;;
  *) die "unsupported role" ;;
esac
