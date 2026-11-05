#!/bin/bash
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
. "$here/worker-common.sh"; . "$here/env.sh"
[[ $# -eq 4 && "$1" = code ]] || die "usage: code WORKSPACE PROMPT PROFILE"
ws=$2; prompt=$3; profile=$4
abs_dir "$ws" workspace; abs_file "$prompt" prompt; abs_file "$profile" profile
abs_exe "${PI_BIN:-}" PI_BIN; abs_exe "${SANDBOX_EXEC:-}" SANDBOX_EXEC
: "${PI_PROVIDER:?}"; : "${PI_CODING_MODEL:?}"
cd "$ws"
exec "$SANDBOX_EXEC" -f "$profile" "$PI_BIN" --print --mode json --provider "$PI_PROVIDER" --model "$PI_CODING_MODEL" \
  --thinking high --no-session --no-extensions --no-mcp --no-skills --no-prompt-templates \
  --no-context-files --no-themes --no-approve --offline --tools read,edit,write "@$prompt"
