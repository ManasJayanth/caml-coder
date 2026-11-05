#!/bin/bash
set -euo pipefail
role=$1
workspace=$2
prompt=$3
profile=$4
[ "$role" = code ] || exit 64
: "${PI_BIN:?absolute executable required}"
: "${PI_PROVIDER:?exact provider required}"
: "${PI_CODING_MODEL:?exact coding model required}"
cd "$workspace"
exec /usr/bin/sandbox-exec -f "$profile" "$PI_BIN" --print --mode json --provider "$PI_PROVIDER" --model "$PI_CODING_MODEL" --no-session --no-extensions --no-mcp --no-skills --no-prompt-templates --no-context-files --no-approve --tools read,edit,write < "$prompt"
