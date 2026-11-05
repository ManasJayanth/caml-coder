Offline reference fixtures; not a compatibility or readiness claim

Purpose
-------
These tiny projects are intended for execution only inside the parent's pinned,
isolated toolchain image. They check basic native OCaml and Reason compilation,
one deterministic assertion failure, and Melange-to-JavaScript emission. No
fixture calls the network, runs generated JavaScript, or executes generated
model output. These files have not been built in this task.

Source grounding
----------------
* OCaml's pinned tutorial data/tutorials/language/3ds_03_sets.md:13 describes
  Set.to_list as requiring OCaml 5.1 (with elements as the earlier fallback).
  The positive fixture uses Set.to_list; the target compiler is expected to be
  newer than that documented minimum.
* Reason's pinned docs/installation.md:43-57 shows Reason installation and
  refmt; lines 77-101 use a .re program with Dune language 3.6 and an executable
  stanza. The Reason fixture follows that project form and uses list/map syntax
  shown in docs/basic-structures.md:31-55.
* Melange's pinned docs/build-system.md:68-100 documents Dune language 3.21,
  `(using melange 1.0)`, and a `(library (modes melange))` stanza. Lines
  142-171 show the `melange.emit` entry point. The fixture uses those stanzas.
  docs/how-to-guides.md:58-90 also shows the library form with melange.ppx;
  this fixture omits the PPX because its source has no PPX syntax.

Parent-reported pinned tool versions for the intended container are Dune
3.24.2, Reason 3.18.0, and Melange 7.0.1-55. This fixture records no proof that
those binaries are present or usable; the parent performs the isolated build.

Expected checks
---------------
1. `cd ocaml-native && dune exec ./main.exe` prints `ocaml-reference:passed`.
2. `cd ocaml-native && dune exec ./wrong_result.exe` exits nonzero by assertion.
3. `cd reason-native && dune exec ./main.exe` prints `reason-reference:passed`.
4. `cd reason-native && dune exec ./wrong_result.exe` exits nonzero by assertion.
5. `cd melange-emission && dune build` emits `app.js` under Dune's _build tree.
6. Each `negative-invalid-source` project is expected to fail compilation.

The wrong-result programs are executable assertions, not invalid source. The
separate invalid-source projects ensure parser/compiler rejection can also be
observed without making positive projects unbuildable.
