import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { S } from "../api/client";
import { useAudit, useVerify } from "../api/hooks";
import { ExportButton } from "../components/ExportButton";
import { Badge, Card, ErrorBox, Loading, Seal } from "../components/ui";
import { short, when } from "../lib/format";
import { usePid } from "../lib/nav";

const TYPES = ["session.start", "session.end", "session.incomplete", "capture.gap", "turn.start", "turn.end", "memory.injected", "gate.decision",
  "file.changed", "tool.call", "skill.invoked", "policy.result", "pii.finding", "approval.*", "config.changed", "lockfile.changed", "policies.changed", "export.created"];

export function Audit() {
  const pid = usePid();
  const [sp, setSp] = useSearchParams();
  const set = (k: string, v?: string) => setSp((p) => { if (v) p.set(k, v); else p.delete(k); if (k !== "page") p.delete("page"); return p; }, { replace: true });
  const f = { type: sp.get("type") || undefined, actor: sp.get("actor") || undefined, session: sp.get("session") || undefined,
    from: sp.get("from") || undefined, to: sp.get("to") || undefined, q: sp.get("q") || undefined, page: Number(sp.get("page") || 1) };
  const { data, error, isLoading } = useAudit(pid, f);
  const { data: v } = useVerify();
  const [open, setOpen] = useState<S["AuditEventOut"] | null>(null);
  return (
    <main className="page reveal">
      <div className="page-head">
        <div>
          <div className="eyebrow">Append-only, hash-chained</div>
          <h1>Audit trail</h1>
        </div>
        <div style={{ display: "flex", gap: ".6rem", alignItems: "center", flexWrap: "wrap" }}>
          {v && <Seal ok={v.ok} count={v.count} at={when(v.verified_at)} />}
          <ExportButton pid={pid} from={f.from} to={f.to} />
        </div>
      </div>
      {v && (
        <div className={`banner ${v.ok ? "info" : "critical"}`} data-testid="anchor-note">
          <span aria-hidden="true">⚓</span>
          <span>
            {!v.ok && <strong>Break at seq {v.break_seq}: {v.reason}. </strong>}
            {v.anchor_note}
          </span>
        </div>
      )}
      <Card>
        <div style={{ display: "flex", flexWrap: "wrap", gap: ".5rem" }}>
          <select className="select" aria-label="Event type" value={f.type ?? ""} onChange={(e) => set("type", e.target.value || undefined)}>
            <option value="">All event types</option>
            {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
          <input className="input" aria-label="Actor" placeholder="Actor id" defaultValue={f.actor} onChange={(e) => set("actor", e.target.value || undefined)} />
          <input className="input" aria-label="Session" placeholder="Session id" defaultValue={f.session} onChange={(e) => set("session", e.target.value || undefined)} />
          <input className="input" type="date" aria-label="From" value={f.from ?? ""} onChange={(e) => set("from", e.target.value || undefined)} />
          <input className="input" type="date" aria-label="To" value={f.to ?? ""} onChange={(e) => set("to", e.target.value || undefined)} />
          <input className="input" type="search" aria-label="Search events" placeholder="Search" defaultValue={f.q} onChange={(e) => set("q", e.target.value || undefined)} style={{ flex: "1 1 160px" }} />
        </div>
      </Card>
      {isLoading && <Loading />}
      {error && <ErrorBox error={error} />}
      {data && (
        <Card>
          {data.items.length === 0 ? <div className="empty">No events match. No events does not prove no activity: gaps are recorded as capture.gap and session.incomplete.</div> : (
            <div className="table-wrap">
              <table className="ledger" data-testid="audit-table">
                <thead><tr><th>Seq</th><th>When</th><th>Type</th><th>Subject</th><th>Actor</th><th>Outcome</th><th>Hash</th></tr></thead>
                <tbody>
                  {data.items.map((e) => (
                    <tr key={e.seq} tabIndex={0} onClick={() => setOpen(e)} onKeyDown={(k) => k.key === "Enter" && setOpen(e)} data-testid="audit-row">
                      <td className="seq">{e.seq}</td>
                      <td className="mono muted">{when(e.occurred_at)}</td>
                      <td className="mono">{e.type}</td>
                      <td className="path">{e.subject ?? ""}</td>
                      <td className="mono muted">{e.actor_kind}:{short(e.actor_id, 10)}</td>
                      <td>{e.outcome === "ok" ? <Badge tone="good">ok</Badge> : e.outcome === "blocked" ? <Badge tone="warning">blocked</Badge> : <Badge tone="critical">{e.outcome}</Badge>}</td>
                      <td className="mono muted">{short(e.hash, 10)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div style={{ display: "flex", justifyContent: "space-between", marginTop: ".75rem" }}>
            <button type="button" className="btn" disabled={f.page <= 1} onClick={() => set("page", String(f.page - 1))}>← Newer</button>
            <span className="mono muted">page {data.page}</span>
            <button type="button" className="btn" disabled={data.items.length < data.page_size} onClick={() => set("page", String(f.page + 1))}>Older →</button>
          </div>
        </Card>
      )}
      {open && (
        <aside className="drawer" aria-label={`Event ${open.seq}`} data-testid="audit-detail">
          <div className="card-head"><h2>Event {open.seq}</h2><button type="button" className="btn" onClick={() => setOpen(null)} aria-label="Close">✕</button></div>
          <div className="card-body">
            <dl className="kv">
              <dt>Type</dt><dd className="mono">{open.type}</dd>
              <dt>Occurred</dt><dd className="mono">{open.occurred_at}</dd>
              <dt>Recorded</dt><dd className="mono">{open.recorded_at}</dd>
              <dt>Actor</dt><dd className="mono">{open.actor_kind} {open.actor_id}</dd>
              <dt>Session</dt><dd className="mono">{open.session_id ?? "—"}</dd>
              <dt>Change</dt><dd className="mono">{open.change_id ?? "—"}</dd>
              <dt>Outcome</dt><dd>{open.outcome}</dd>
              <dt>Prev hash</dt><dd className="mono">{open.prev_hash}</dd>
              <dt>Hash</dt><dd className="mono">{open.hash}</dd>
            </dl>
            <div className="eyebrow" style={{ marginTop: "1rem" }}>Detail (no content, by design)</div>
            <pre className="snippet">{JSON.stringify(open.detail, null, 2)}</pre>
          </div>
        </aside>
      )}
    </main>
  );
}
