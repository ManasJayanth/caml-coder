die(){ echo "worker: $*" >&2; exit 64; }
abs_file(){ [[ "$1" = /* && -f "$1" && ! -L "$1" ]] || die "absolute regular non-symlink file required: $2"; }
abs_dir(){  [[ "$1" = /* && -d "$1" && ! -L "$1" ]] || die "absolute non-symlink dir required: $2"; }
abs_exe(){  [[ "$1" = /* && -x "$1" && ! -L "$1" ]] || die "absolute executable non-symlink required: $2"; }
