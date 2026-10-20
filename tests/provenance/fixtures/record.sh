#!/bin/sh
# Records the blame_*.txt porcelain fixtures from real git runs (fixed dates and identity). Usage: sh record.sh
set -eu
out=$(cd "$(dirname "$0")" && pwd)
r=$(mktemp -d)
trap 'rm -rf "$r"' EXIT
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 GIT_AUTHOR_NAME=dev GIT_AUTHOR_EMAIL=dev@example.com \
  GIT_COMMITTER_NAME=dev GIT_COMMITTER_EMAIL=dev@example.com
c() { GIT_AUTHOR_DATE="$1" GIT_COMMITTER_DATE="$1" git -C "$r" commit -qm "$2"; }
git -C "$r" init -q -b main
printf 'def first_function(alpha):\n    return alpha + 1\n' > "$r/old_name.py"
git -C "$r" add -A && c 1790000000 base
git -C "$r" mv old_name.py new_name.py
printf 'def second_function(beta):\n    return beta * 2\n' >> "$r/new_name.py"
git -C "$r" add -A && c 1790000100 rename
# rev first then path: "blame --end-of-options <rev> -- <path>" fails on git 2.54 (see docs/adr/0019)
b() { git -C "$r" blame --porcelain -w -M -C --end-of-options -- "$3" "$1"; }
b HEAD -- new_name.py > "$out/blame_rename.txt"
printf 'spaced_and_quoted = "value one"\n' > "$r/my \"odd\" file.py"
printf 'line_with_crlf_ending = 1\r\nsecond_crlf_line_here = 2\r\n' > "$r/crlf.txt"
printf 'caf\351_latin1_bytes = 1\nplain_ascii_line_here = 2\n' > "$r/bytes.txt"
git -C "$r" add -A && c 1790000200 more
b HEAD -- 'my "odd" file.py' > "$out/blame_quoted_path.txt"
b HEAD -- crlf.txt > "$out/blame_crlf.txt"
b HEAD -- bytes.txt > "$out/blame_bytes.txt"
b HEAD~1..HEAD -- new_name.py > "$out/blame_boundary.txt"
printf 'first_interleaved_line = 1\nsecond_interleaved_line = 2\nthird_interleaved_line = 3\n' > "$r/inter.py"
git -C "$r" add -A && c 1790000300 inter
printf 'first_interleaved_line = 1\nsecond_line_changed_later = 2\nthird_interleaved_line = 3\n' > "$r/inter.py"
git -C "$r" add -A && c 1790000400 middle
b HEAD -- inter.py > "$out/blame_interleaved.txt"
