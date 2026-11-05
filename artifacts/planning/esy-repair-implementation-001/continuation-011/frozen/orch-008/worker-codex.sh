#!/bin/bash
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
. "$here/worker-common.sh"; . "$here/env.sh"
[[ $# -eq 4 ]] || die "usage: ROLE WORKSPACE PROMPT PROFILE"
abs_exe "${CODEX_BIN:-}" CODEX_BIN; abs_file "${CODEX_WORKER:-}" CODEX_WORKER
exec /bin/bash "$CODEX_WORKER" "$1" "$2" "$3" "$4" "$CODEX_BIN"   # model/sandbox fixed inside frozen script
