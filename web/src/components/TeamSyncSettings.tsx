import { useState } from "react";
import { api, unwrap } from "../api/client";
import { useWrite } from "../api/hooks";
import { Badge, Card, Note } from "./ui";

const SEND: [string, string][] = [
  ["send_paths", "File paths"], ["send_tokens", "Token counts"], ["send_cost", "Cost"],
  ["send_skills", "Skills run"], ["send_pii_counts", "PII types and counts"], ["send_audit", "Audit events"],
];

/** Editable [sync] settings. The server checks the URL (https, or http on localhost) and writes an audit event per change. */
export function TeamSyncSettings({ sync }: { sync: Record<string, unknown> }) {
  const [enabled, setEnabled] = useState(sync.enabled === true);
  const [server, setServer] = useState(String(sync.server ?? ""));
  const [send, setSend] = useState<Record<string, boolean>>(Object.fromEntries(SEND.map(([k]) => [k, sync[k] === true])));
  const save = useWrite(() => unwrap(api.PUT("/api/settings", { body: { sync: { enabled, server: server.trim(), ...send } } })));
  return (
    <Card title="Team sync" aside={<Badge tone="neutral">{enabled ? "on" : "off"}</Badge>}>
      <div className="form" data-testid="team-sync-settings">
        <label className="check">
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          <span>Send metadata to the team server</span>
        </label>
        <label className="field">
          <span className="label">Team server URL</span>
          <input className="input" type="text" inputMode="url" autoComplete="off" spellCheck={false} placeholder="https://team.example.com"
            value={server} onChange={(e) => setServer(e.target.value)} aria-describedby="sync-server-hint" />
          <span id="sync-server-hint" className="muted tiny">https only; plain http is accepted for localhost. No credentials in the URL.</span>
        </label>
        <fieldset className="field">
          <legend className="label">What is sent</legend>
          <div className="checklist">
            {SEND.map(([k, label]) => (
              <label key={k} className="check">
                <input type="checkbox" checked={send[k] ?? false} onChange={(e) => setSend((s) => ({ ...s, [k]: e.target.checked }))} />
                <span>{label}</span>
              </label>
            ))}
          </div>
        </fieldset>
        <p className="muted tiny" style={{ margin: 0 }}>
          The key is read from the environment variable <span className="mono">{String(sync.api_key_env ?? "SEEN_TEAM_API_KEY")}</span>, or from the
          sign-in on the Team page. It is never shown or stored here. Prompts, diffs, file contents and PII values never sync.
        </p>
        <div className="checks">
          <button type="button" className="btn primary" disabled={save.isPending} onClick={() => save.mutate(undefined)}>Save team sync</button>
          {save.isSuccess && <span className="muted small" role="status">Saved. Every change is in the audit trail.</span>}
        </div>
        {save.error && <Note tone="critical">{save.error.message}</Note>}
      </div>
    </Card>
  );
}
