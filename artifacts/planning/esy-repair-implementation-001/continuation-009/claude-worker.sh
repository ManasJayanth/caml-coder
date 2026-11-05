#!/bin/bash
set -euo pipefail
[[ $# -eq 4 && "$1" = review ]] || exit 64
exec /bin/bash /Users/psac/development/prometheansacrifice/ocaml-rl-sft/artifacts/planning/esy-repair-implementation-001/bootstrap/trusted-codex-worker-003.sh "$@"
