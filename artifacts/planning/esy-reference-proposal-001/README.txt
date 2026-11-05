Offline esy OCaml reference project proposal

This is a small proposed native-compiler probe, not executed evidence. The
program checks a computed list against an exact expected value, then prints a
stable success marker. It does not need Dune, external libraries, network
access, or generated-code execution.

Exact package and compiler identities
-------------------------------------
The active package.json pins npm package `ocaml` to exactly `5.5.1000`. The
official registry metadata captured in registry-latest.json identifies that
package id, archive URL, npm integrity, and zero package dependencies. The
verified archive audit in latest-compiler-source-audit.json records
`package/package.json` version `5.5.1000` alongside `package/VERSION` content
`5.5.1`. Thus `5.5.1000` is the npm package version; the compiler source is
version `5.5.1`.

The source archive SHA-512 is
`99524f952e11da29f5000c3e85404542a814ab9d8a1e0c6eedae83df7d3a843c86fd253a7bbfd89486ee0145c9ecf5f00411907be48cb83c937958f2770a086d`.
The registry metadata declares integrity
`sha512-mVJPlS4R2in1AAw+hUBFQqgUq52KHgxu7a6D3306hDyG/SU6e7/YlIbuAUXJ7PXwBBGQe+SMuDyTeVjydwoIbQ==`.
Parent evidence should retain the exact metadata and archive verification
before resolution is considered complete.

The earlier npm `ocaml@5.3.0` package manifest is preserved as
package-ocaml-5.3.0-historical.json. The esy compiler guide recommends major or
minor semver ranges such as `5.x` and `5.1.x`; this probe instead pins an exact
package version for reproducibility.

Build and run proposal
----------------------
The pinned esy getting-started guide shows `ocaml` as a package.json
dependency, compiles with `esy ocamlopt -o hello.exe hello.ml`, and runs the
executable. After resolving the dependency and capturing its lock data in the
isolated offline image, run:

1. `esy ocamlopt -o main.exe main.ml`
2. `./main.exe`

Require exit status 0 and exact stdout `esy-ocaml-reference:passed`.

The parent-reported esy 0.9.2 and Node 24.22.0 builds are tool binaries only;
they do not establish that this project resolves or builds offline. Remaining
work is to ensure lock data and compiler build inputs are present in the
isolated cache, then compile and run the assertion. No Reason, Dune, Melange,
esy/Node runtime compatibility, or broader toolchain readiness is claimed.
