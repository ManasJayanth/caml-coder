# Active reviewer policy — revision 002

The user replaced Claude Fable with Codex Astra. The mandatory review command is now `codex-worker.sh review`, selecting `gpt-6-astra`, read-only, in a fresh process. Planning also uses `gpt-6-astra` but in a separate fresh process. Coding remains `gpt-6-luna`.

The old Fable requirement and Fable-specific resume blocker are superseded. Preserve old reports as historical evidence; do not require a Fable login or response to continue. Claude remains an optional coding backend only.

All other acceptance criteria, independent review, E2E requirements, isolation restrictions, six-hour/12-round budgets, and guarded import rules remain unchanged. A smoke response establishes availability only, not repair acceptance.

Current code remains an unimported bootstrap candidate. C0 is partial, C1-C7 remain outstanding. No esy image or runner was repaired by this policy change.
