#!/bin/bash
set -euo pipefail
if [[ $# -ne 4 ]]; then
  echo "usage: codex-worker.sh ROLE WORKSPACE PROMPT PROFILE" >&2
  exit 64
fi
role=$1
workspace=$2
prompt=$3
profile=$4
case "$role" in
 code) model=gpt-6-luna; sandbox=danger-full-access; shell_flag=--enable ;;
 plan|review) model=gpt-6-astra; sandbox=read-only; shell_flag=--disable ;;
 *) exit 64 ;;
esac
[[ "$workspace" = /* && -d "$workspace" ]] || { echo "absolute workspace required" >&2; exit 64; }
[[ "$prompt" = /* && -f "$prompt" ]] || { echo "absolute prompt required" >&2; exit 64; }
[[ "$profile" = /* && -f "$profile" ]] || { echo "absolute sandbox profile required" >&2; exit 64; }
[[ -n "${CODEX_BIN:-}" && "$CODEX_BIN" = /* && -x "$CODEX_BIN" ]] || {
  echo "absolute executable required" >&2; exit 64;
}
CODEX_BIN=$(/usr/bin/realpath "$CODEX_BIN")
[[ "$CODEX_BIN" = /* && -x "$CODEX_BIN" ]] || { echo "invalid resolved Codex executable" >&2; exit 64; }
cd "$workspace"
exec /usr/bin/sandbox-exec -f "$profile" "$CODEX_BIN" exec --disable apps --disable plugins --disable hooks --disable multi_agent --disable shell_snapshot "$shell_flag" shell_tool --ignore-user-config --ephemeral --skip-git-repo-check --model "$model" --sandbox "$sandbox" --cd "$workspace" --json - < "$prompt"
