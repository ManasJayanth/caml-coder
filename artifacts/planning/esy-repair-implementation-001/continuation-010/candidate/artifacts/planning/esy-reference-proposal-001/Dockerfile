FROM ocaml-sft-node-esy-probe:001
USER 1000:1000
ENV ESY__BUILD_CONCURRENCY=2 ESY__FETCH_CONCURRENCY=2
WORKDIR /home/opam/esy-reference
COPY --chown=1000:1000 package.json main.ml ./
RUN esy install
RUN --network=none esy build-dependencies
RUN --network=none esy ocamlopt -version && esy ocamlopt -o reference.exe main.ml && ./reference.exe
RUN --network=none esy command-env > reference-command-env.txt
