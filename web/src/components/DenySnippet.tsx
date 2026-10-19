import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";

/** Shows the permissions.deny entry to add to .claude/settings.json. Seen never writes it for you. */
export function DenySnippet({ rule }: { rule: string }) {
  const [open, setOpen] = useState(false);
  const snippet = JSON.stringify({ permissions: { deny: [rule] } }, null, 2);
  return (
    <div>
      <button type="button" className="btn ghost sm" aria-expanded={open} onClick={() => setOpen(!open)} style={{ marginLeft: "-0.5rem" }}>
        {open ? <ChevronDown aria-hidden="true" /> : <ChevronRight aria-hidden="true" />}{open ? "Hide" : "Show"} deny rule
      </button>
      {open && (
        <div style={{ marginTop: "0.4rem" }} data-testid="deny-snippet">
          <pre className="snippet">{snippet}</pre>
          <p className="muted tiny" style={{ marginTop: 6 }}>
            Add to the repo's <span className="mono">.claude/settings.json</span>. It blocks the Read tool only; <span className="mono">cat</span> through Bash is not covered.
          </p>
        </div>
      )}
    </div>
  );
}
