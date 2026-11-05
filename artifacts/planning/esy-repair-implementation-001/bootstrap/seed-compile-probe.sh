set -eu
cp -a /home/opam/esy-cache-seed/_esy/. /home/opam/esy-reference/_esy/
cp -a /home/opam/esy-cache-seed/node-cache/. /home/opam/esy-reference/node_modules/.cache/
printf '%s\n' 'let () = print_endline "esy-cache-probe:passed"' > /work/main.ml
/home/opam/esy/bin/esy ocamlopt -o /work/main.exe /work/main.ml
/work/main.exe
