import { useState } from "react";

/** Shows the permissions.deny entry to add to .claude/settings.json. Seen never writes it for you. */
export function DenySnippet({ rule }: { rule: string }) {
  const [open, setOpen] = useState(false);
  const snippet = JSON.stringify({ permissions: { deny: [rule] } }, null, 2);
  return (
    <div style={{ marginTop: ".4rem" }}>
      <button type="button" className="chip" aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? "Hide" : "Show"} deny rule
      </button>
      {open && (
        <div style={{ marginTop: ".4rem" }} data-testid="deny-snippet">
          <pre className="snippet">{snippet}</pre>
          <p className="muted" style={{ fontSize: ".76rem", margin: ".3rem 0 0" }}>
            Add to the repo's <span className="mono">.claude/settings.json</span>. It blocks the Read tool only; <span className="mono">cat</span> through Bash is not covered.
          </p>
        </div>
      )}
    </div>
  );
}
