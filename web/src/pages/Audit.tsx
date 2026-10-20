import { Anchor, FileClock, Search, X } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { S } from "../api/client";
import { useAudit, useVerify } from "../api/hooks";
import { ExportButton } from "../components/ExportButton";
import { Badge, Empty, ErrorBox, Loading, Note, PageHead, RowButton, Seal } from "../components/ui";
import { short, when } from "../lib/format";
import { usePid } from "../lib/nav";

const TYPES = ["session.start", "session.end", "session.incomplete", "capture.gap", "turn.start", "turn.end", "gate.decision",
  "file.changed", "tool.call", "skill.invoked", "policy.result", "pii.finding", "pii.allowlisted", "approval.*", "config.changed", "lockfile.changed",
  "policies.changed", "export.created", "sync.batch"];

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
    <div className="page">
      <PageHead
        title="Audit trail"
        description="Append-only and hash-chained. Events hold ids, counts, hashes and paths, never content."
        actions={<>{v && <Seal ok={v.ok} count={v.count} at={when(v.verified_at)} />}<ExportButton pid={pid} from={f.from} to={f.to} /></>}
      />
      {v && (
        <Note tone={v.ok ? "info" : "critical"} icon={Anchor} testId="anchor-note">
          {!v.ok && <strong>Break at seq {v.break_seq}: {v.reason}. </strong>}
          {v.anchor_note}
        </Note>
      )}
      <div className="toolbar" role="search">
        <select className="select" aria-label="Event type" value={f.type ?? ""} onChange={(e) => set("type", e.target.value || undefined)}>
          <option value="">All event types</option>
          {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <input className="input" aria-label="Actor" placeholder="Actor id" defaultValue={f.actor} onChange={(e) => set("actor", e.target.value || undefined)} />
        <input className="input" aria-label="Session" placeholder="Session id" defaultValue={f.session} onChange={(e) => set("session", e.target.value || undefined)} />
        <input className="input" type="date" aria-label="From" value={f.from ?? ""} onChange={(e) => set("from", e.target.value || undefined)} />
        <input className="input" type="date" aria-label="To" value={f.to ?? ""} onChange={(e) => set("to", e.target.value || undefined)} />
        <label className="search" style={{ flexBasis: 180 }}>
          <Search aria-hidden="true" />
          <input className="input" type="search" aria-label="Search events" placeholder="Search" defaultValue={f.q} onChange={(e) => set("q", e.target.value || undefined)} />
        </label>
      </div>
      {isLoading && <Loading what="Loading events" />}
      {error && <ErrorBox error={error} />}
      {data && (
        <section className="panel">
          {data.items.length === 0 ? (
            <Empty icon={FileClock} title="No events match">No events does not prove no activity: gaps are recorded as capture.gap and session.incomplete.</Empty>
          ) : (
            <div className="table-wrap" tabIndex={0} role="region" aria-label="Audit events">
              <table className="data" data-testid="audit-table">
                <thead><tr><th>Seq</th><th>When</th><th>Type</th><th>Subject</th><th>Actor</th><th>Outcome</th><th>Hash</th></tr></thead>
                <tbody>
                  {data.items.map((e) => (
                    <tr key={e.seq} className="clickable" onClick={() => setOpen(e)}
                      aria-selected={open?.seq === e.seq} data-testid="audit-row">
                      <td className="num">{e.seq}</td>
                      <td className="when">{when(e.occurred_at)}</td>
                      <td className="mono"><RowButton onClick={() => setOpen(e)}>{e.type}</RowButton></td>
                      <td className="path">{e.subject ?? ""}</td>
                      <td className="mono tiny muted">{e.actor_kind}:{short(e.actor_id, 10)}</td>
                      <td>{e.outcome === "ok" ? <Badge tone="good">ok</Badge> : e.outcome === "blocked" ? <Badge tone="warning">blocked</Badge> : <Badge tone="critical">{e.outcome}</Badge>}</td>
                      <td className="mono tiny muted">{short(e.hash, 10)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "0.6rem 1rem", borderTop: "1px solid var(--border)" }}>
            <button type="button" className="btn sm" disabled={f.page <= 1} onClick={() => set("page", String(f.page - 1))}>← Newer</button>
            <span className="mono tiny muted">Page {data.page}</span>
            <button type="button" className="btn sm" disabled={data.items.length < data.page_size} onClick={() => set("page", String(f.page + 1))}>Older →</button>
          </div>
        </section>
      )}
      {open && (
        <aside className="drawer" aria-label={`Event ${open.seq}`} data-testid="audit-detail">
          <div className="drawer-head">
            <h2>Event {open.seq}</h2>
            <button type="button" className="btn ghost icon-btn" onClick={() => setOpen(null)} aria-label="Close"><X aria-hidden="true" /></button>
          </div>
          <div className="drawer-body">
            <dl className="kv">
              <dt>Type</dt><dd className="mono">{open.type}</dd>
              <dt>Occurred</dt><dd className="mono">{open.occurred_at}</dd>
              <dt>Recorded</dt><dd className="mono">{open.recorded_at}</dd>
              <dt>Actor</dt><dd className="mono">{open.actor_kind} {open.actor_id}</dd>
              <dt>Session</dt><dd className="mono">{open.session_id ?? "—"}</dd>
              <dt>Change</dt><dd className="mono">{open.change_id ?? "—"}</dd>
              <dt>Outcome</dt><dd>{open.outcome}</dd>
              <dt>Prev hash</dt><dd className="mono tiny">{open.prev_hash}</dd>
              <dt>Hash</dt><dd className="mono tiny">{open.hash}</dd>
            </dl>
            <section>
              <h3 style={{ marginBottom: 6 }}>Detail</h3>
              <pre className="snippet">{JSON.stringify(open.detail, null, 2)}</pre>
              <p className="muted tiny" style={{ marginTop: 6 }}>No prompt text, diffs, command arguments or PII values, by design.</p>
            </section>
          </div>
        </aside>
      )}
    </div>
  );
}
