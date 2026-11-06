# Before attempt 38: isolate the workload before it starts

Status: host probes executed; production containment NOT accepted. No candidate ran. 37 of 48 coding launches consumed.

On Darwin arm64, the six unconfined positive controls exited zero. The process-fork denial allowed a simple command but rejected the fork and nested-session controls. The syscall filter allowed an ordinary fork and rejected direct setsid and setpgid; posix_spawn with setpgroup=0 still succeeded. These finite controls rule out using either profile alone to claim cleanup of the fork-capable harness. See results.json for exact outcomes, including negative controls. Do not signal retained PID/PGID values after reap.

The host reports hardware virtualization support. No prepared macOS guest was found in the conventional local VM locations checked. Apple's Virtualization.framework reports supported macOS build 26B123, minimum 2 vCPUs and 4 GiB guest RAM. A HEAD request to the Apple-provided restore URL returned 25,595,669,503 bytes and SHA-256 6613b34e8589db2202a01ec37a2648afb141ece13428175183f8f3e38438534f. No installer downloaded or VM started. The previously pinned Linux checker image was absent; a Linux container is not a substitute for Darwin acceptance.

## Small follow-up cards and gates

1. Provision and qualify a disposable macOS guest: verify installer integrity, record host/guest versions and the base disk identity. Use a fresh writable clone per run. No host directory mounts, Docker sockets, host credentials or network access during the test; return only bounded results over a dedicated channel. Require a real clean guest boot and independently observed teardown; merely finding an installer is not acceptance.
2. Before any candidate code, run fixed clean and detached-descendant controls. Inside the guest prove the descendant changed sessions, redirected its streams, ignored TERM and remained alive after leader exit. Outside the guest verify teardown targets only this run's owned VM and actually completes; keep an unrelated canary alive. Missing readiness, interrupted teardown and lost observer must be failures with retained evidence. Never infer cleanup solely from the workload's own receipt.
3. Independently review whether guest shutdown is merely outer test safety or an enforceable lifecycle boundary for EACH production workload. A supervisor for tests alone does not fix C9. The public runner must refuse unsupported commands before launch, or tie success to actual teardown of each workload's qualified boundary. Document any change in supported commands before adopting it.
4. Only after those decisions: fresh Astra plan for Luna, isolated patch authoring, Astra pre-execution review, O70 and the complete registered suite under qualified containment. C10/O71 remains downstream. Do not spend a coding launch on the same blocked C9 instructions.

A disposable VM is a proposed path, not a proof that Darwin has no other viable mechanism. Mac guest installation and initial configuration are still required.
