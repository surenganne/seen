# 19: Blame takes `--end-of-options -- <path> <rev>`, not `--end-of-options <rev> -- <path>`

Status: proposed, 2026-10-20 (owner to confirm)

Spec section 6.1 and the PV-4 brief give `git blame --porcelain -w -M -C --end-of-options <rev> -- <path>`. On git 2.54
(Apple Git-157) that form fails with `fatal: bad revision '<path>'`: after `--end-of-options`, blame does not treat the
later `--` as the path separator. `git blame ... --end-of-options -- <path> <rev>` is blame's documented
"`blame -- <path> <rev>`" form. It works on the same git, so `--end-of-options` is kept and nothing after it is read as an
option. A rev such as `-n` in that position is rejected by git and does not become an option. `seen_core.provenance.blame` uses
this form and also refuses revs that start with `-`. The spec text should follow (Task 10).
