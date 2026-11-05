#!/bin/bash
set -euo pipefail
role=$1
workspace=$2
prompt=$3
profile=$4
case "$role" in
 code) model=gpt-6-luna; sandbox=danger-full-access; shell_flag=--enable ;;
 plan|review) model=gpt-6-astra; sandbox=read-only; shell_flag=--disable ;;
 *) exit 64 ;;
esac
: "${CODEX_BIN:?absolute executable required}"
cd "$workspace"
exec /usr/bin/sandbox-exec -f "$profile" "$CODEX_BIN" exec -c 'model_reasoning_effort="high"' --disable apps --disable plugins --disable hooks --disable multi_agent --disable shell_snapshot "$shell_flag" shell_tool --ignore-user-config --ephemeral --skip-git-repo-check --model "$model" --sandbox "$sandbox" --cd "$workspace" --json - < "$prompt"
