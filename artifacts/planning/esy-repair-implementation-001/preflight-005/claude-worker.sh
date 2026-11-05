#!/bin/bash
set -euo pipefail
role=$1
workspace=$2
prompt=$3
profile=$4
case "$role" in
 review) model=fable; tools=""; permission=plan ;;
 code) : "${CLAUDE_CODING_MODEL:?exact coding model required}"; model=$CLAUDE_CODING_MODEL; tools="Read,Edit,Write,Glob,Grep"; permission=acceptEdits ;;
 *) exit 64 ;;
esac
: "${CLAUDE_BIN:?absolute executable required}"
cd "$workspace"
exec /usr/bin/sandbox-exec -f "$profile" "$CLAUDE_BIN" --print --model "$model" --output-format json --no-session-persistence --safe-mode --disable-slash-commands --restricted --setting-sources "" --strict-mcp-config --mcp-config '{"mcpServers":{}}' --permission-mode "$permission" --tools "$tools" < "$prompt"
