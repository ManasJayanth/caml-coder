FROM --platform=linux/amd64 ocaml/opam@sha256:52ae74f2f384d509b9c001aaec682ad390202836b5c655358290f49d97934a9a
USER 1000:1000
ENV OPAMYES=1 OPAMJOBS=2
RUN opam install --yes --jobs=2 dune.3.24.2 reason.3.18.0 melange.7.0.1-55
RUN opam list --installed --columns=name,version > /home/opam/installed-packages.txt
