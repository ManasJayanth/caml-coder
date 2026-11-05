#!/bin/bash
set -euo pipefail
[[ $# -eq 4 && "$1" = review ]] || exit 64
cd "$2"
exec /usr/bin/sandbox-exec -f "$4" /opt/homebrew/bin/claude --print --model fable --output-format json --no-session-persistence --safe-mode --restricted --disable-slash-commands --setting-sources "" --strict-mcp-config --mcp-config '{"mcpServers":{}}' --permission-mode plan --tools "" < "$3"
