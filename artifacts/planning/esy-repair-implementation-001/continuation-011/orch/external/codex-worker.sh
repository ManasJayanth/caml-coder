#!/bin/bash
# Frozen role template. Every argument is supplied by the verified controller;
# no environment variable can replace the executable, model, sandbox, or prompt.
set -euo pipefail
if [[ $# -ne 5 ]]; then
  echo "usage: codex-worker.sh ROLE WORKSPACE PROMPT PROFILE CODEX_EXECUTABLE" >&2
  exit 64
fi
role=$1
workspace=$2
prompt=$3
profile=$4
codex_bin=$5
case "$role" in
  code) model=gpt-6-luna; sandbox=danger-full-access; shell_flag=--enable ;;
  plan|review) model=gpt-6-astra; sandbox=read-only; shell_flag=--disable ;;
  *) echo "unsupported role" >&2; exit 64 ;;
esac
[[ "$workspace" = /* && -d "$workspace" && ! -L "$workspace" ]] || { echo "verified absolute workspace required" >&2; exit 64; }
[[ "$prompt" = /* && -f "$prompt" && ! -L "$prompt" ]] || { echo "verified absolute prompt required" >&2; exit 64; }
[[ "$profile" = /* && -f "$profile" && ! -L "$profile" ]] || { echo "verified absolute sandbox profile required" >&2; exit 64; }
[[ "$codex_bin" = /* && -x "$codex_bin" && ! -L "$codex_bin" ]] || { echo "verified absolute Codex executable required" >&2; exit 64; }

cd "$workspace"
exec /usr/bin/sandbox-exec -f "$profile" "$codex_bin" exec --disable apps --disable plugins --disable hooks --disable multi_agent --disable shell_snapshot "$shell_flag" shell_tool --ignore-user-config --ephemeral --skip-git-repo-check --model "$model" --sandbox "$sandbox" --cd "$workspace" --json - < "$prompt"
