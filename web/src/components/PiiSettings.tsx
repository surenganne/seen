import { Check } from "lucide-react";
import { useState } from "react";
import { api, unwrap } from "../api/client";
import { useWrite } from "../api/hooks";
import { Badge, Card, Note } from "./ui";

const TYPES = ["email", "phone", "aadhaar", "pan", "card", "iban", "ssn", "upi", "dob", "gstin", "passport", "secret"];

export function PiiSettings({ pii }: { pii: Record<string, unknown> }) {
  const [mode, setMode] = useState(String(pii.mode));
  const [store, setStore] = useState(String(pii.store_prompt_text));
  const [minConf, setMinConf] = useState(String(pii.min_confidence));
  const [types, setTypes] = useState<string[]>((pii.types as string[]) ?? []);
  const save = useWrite(() => unwrap(api.PUT("/api/settings", {
    body: { pii: { mode, store_prompt_text: store, min_confidence: minConf, types } },
  })));
  const toggle = (t: string) => setTypes((ts) => (ts.includes(t) ? ts.filter((x) => x !== t) : [...ts, t]));
  return (
    <Card title="PII detection" aside={<Badge tone={mode === "block" ? "accent" : "neutral"}>{mode}</Badge>}>
      <div className="form" data-testid="pii-settings">
        <label className="field">
          <span className="label">Mode</span>
          <select className="select" value={mode} onChange={(e) => setMode(e.target.value)} aria-label="PII mode">
            <option value="off">off</option>
            <option value="report">report: record only</option>
            <option value="warn">warn: tell the user, prompt still sent</option>
            <option value="block">block: stop the prompt or read</option>
          </select>
        </label>
        <label className="field">
          <span className="label">Prompt storage</span>
          <select className="select" value={store} onChange={(e) => setStore(e.target.value)} aria-label="Prompt storage">
            <option value="redacted">redacted (default)</option>
            <option value="full">full text</option>
            <option value="off">off</option>
          </select>
        </label>
        <label className="field">
          <span className="label">Show findings from</span>
          <select className="select" value={minConf} onChange={(e) => setMinConf(e.target.value)} aria-label="Minimum confidence">
            <option value="low">low confidence</option>
            <option value="medium">medium confidence</option>
            <option value="high">high confidence</option>
          </select>
        </label>
        <fieldset className="field">
          <legend className="label">Types</legend>
          <div className="checks">
            {TYPES.map((t) => <button key={t} type="button" className="chip" aria-pressed={types.includes(t)} onClick={() => toggle(t)}>{types.includes(t) && <Check aria-hidden="true" />}{t}</button>)}
          </div>
        </fieldset>
        <div className="checks">
          <button type="button" className="btn primary" disabled={save.isPending} onClick={() => save.mutate(undefined)}>Save</button>
          {save.isSuccess && <span className="muted small" role="status">Saved. Every change is in the audit trail.</span>}
        </div>
        {save.error && <Note tone="critical">{save.error.message}</Note>}
        <p className="muted tiny prose" style={{ margin: 0 }}>
          Allowlists and custom rules live in each repo's <span className="mono">.seen/pii.yaml</span>, reviewed in pull requests.
          Regex finds structured identifiers; it misses names, addresses and free-text health details. This is evidence for a privacy review, not a compliance control.
        </p>
      </div>
    </Card>
  );
}
