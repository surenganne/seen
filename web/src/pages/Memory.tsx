import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, type S, unwrap } from "../api/client";
import { useMemory, useWrite } from "../api/hooks";
import { Badge, Card, ErrorBox, Loading } from "../components/ui";
import { short, when } from "../lib/format";
import { usePid, useRange, withRange } from "../lib/nav";

const TYPES = ["decision", "convention", "gotcha", "context"] as const;
const STATUS_TONE = { verified: "good", unverified: "neutral", stale: "warning", invalid: "critical" } as const;

export function Memory() {
  const pid = usePid();
  const [sp, setSp] = useSearchParams();
  const set = (k: string, v?: string) => setSp((p) => { if (v) p.set(k, v); else p.delete(k); return p; }, { replace: true });
  const f = { type: sp.get("type") || undefined, status: sp.get("status") || undefined, q: sp.get("q") || undefined };
  const { data, error, isLoading } = useMemory(pid, f);
  return (
    <main className="page reveal">
      <div className="page-head">
        <div>
          <div className="eyebrow">.seen/memory · loaded into every session</div>
          <h1>Memory</h1>
        </div>
        {data && (
          <div style={{ display: "flex", gap: ".4rem", flexWrap: "wrap" }} data-testid="memory-counts">
            {Object.entries(data.counts).map(([k, n]) => (
              <Badge key={k} tone={STATUS_TONE[k as keyof typeof STATUS_TONE] ?? "neutral"}>{n} {k}</Badge>
            ))}
          </div>
        )}
      </div>
      <Card>
        <div style={{ display: "flex", flexWrap: "wrap", gap: ".5rem", alignItems: "center" }}>
          <input className="input" type="search" aria-label="Search memory" placeholder="Search memory" defaultValue={f.q}
            onChange={(e) => set("q", e.target.value || undefined)} style={{ flex: "1 1 200px" }} />
          {TYPES.map((t) => (
            <button key={t} type="button" className="chip" aria-pressed={f.type === t} onClick={() => set("type", f.type === t ? undefined : t)}>{t}</button>
          ))}
          <select className="select" aria-label="Freshness" value={f.status ?? ""} onChange={(e) => set("status", e.target.value || undefined)}>
            <option value="">Any freshness</option>
            <option value="verified">Verified</option>
            <option value="unverified">Unverified</option>
            <option value="stale">Stale</option>
          </select>
        </div>
      </Card>
      <div className="banner info">
        <span aria-hidden="true">⚠</span>
        <span>Memory is text the model treats as guidance. Review <span className="mono">.seen/memory/</span> like code (a CODEOWNERS rule helps) and never store secrets or client data there.</span>
      </div>
      {isLoading && <Loading />}
      {error && <ErrorBox error={error} />}
      {data && data.items.length === 0 && <div className="card empty">No memory matches.</div>}
      <div className="grid grid-even" data-testid="memory-list">
        {data?.items.map((m) => <MemoryCard key={m.id} m={m} pid={pid} />)}
      </div>
      {data && data.invalid.length > 0 && (
        <Card title="Files Seen could not read" aside={<Badge tone="critical">{data.invalid.length} invalid</Badge>}>
          <ul className="list">
            {data.invalid.map((m) => <li key={m.path}><span className="path">{m.path}</span><span className="muted">{m.error}</span></li>)}
          </ul>
        </Card>
      )}
    </main>
  );
}

function MemoryCard({ m, pid }: { m: S["MemoryOut"]; pid: string }) {
  const [open, setOpen] = useState(m.status === "stale");
  const [range] = useRange();
  const verify = useWrite(() => unwrap(api.POST("/api/memory/{mid}/verify", { params: { path: { mid: m.id }, query: { project: pid } } })));
  const archive = useWrite(() => unwrap(api.POST("/api/memory/{mid}/archive", { params: { path: { mid: m.id }, query: { project: pid } } })));
  return (
    <section className="card" data-testid="memory-card" data-status={m.status} data-id={m.id}>
      <div className="card-head">
        <div style={{ minWidth: 0 }}>
          <div className="eyebrow">{m.type} · {m.scope}</div>
          <h3 className="mono" style={{ fontFamily: "var(--font-mono)", fontWeight: 500, fontSize: ".95rem" }}>{m.id}</h3>
        </div>
        <Badge tone={STATUS_TONE[m.status]}>{m.status}</Badge>
      </div>
      <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: ".6rem" }}>
        <p style={{ margin: 0 }}>{m.body}</p>
        <button type="button" className="chip" aria-expanded={open} onClick={() => setOpen(!open)} style={{ alignSelf: "start" }}>
          {open ? "Less" : "Details"}
        </button>
        {open && (
          <dl className="kv">
            <dt>File</dt><dd className="path">{m.file_ref ? <Link to={withRange(`/p/${pid}/changes`, range, { file: m.file_ref })}>{m.file_ref}</Link> : "—"}</dd>
            <dt>Verified</dt><dd className="mono">{m.verified_at ? when(m.verified_at) : "never"}</dd>
            <dt>Source change</dt><dd className="mono">{m.source_change ? <Link to={withRange(`/p/${pid}/changes/${m.source_change}`, range)}>{short(m.source_change, 14)}</Link> : "—"}</dd>
            {m.stale_reason && (<><dt>Why stale</dt><dd data-testid="stale-reason">{m.stale_reason}</dd></>)}
            <dt>Loaded in</dt><dd className="mono">{m.used_in} changes</dd>
            <dt>File</dt><dd className="path muted">{m.path}</dd>
          </dl>
        )}
        <div style={{ display: "flex", gap: ".4rem", flexWrap: "wrap" }}>
          <button type="button" className="btn primary" disabled={verify.isPending} onClick={() => verify.mutate(undefined)}>
            {m.status === "verified" ? "Verify again" : "Re-verify"}
          </button>
          <button type="button" className="btn danger" disabled={archive.isPending} onClick={() => archive.mutate(undefined)}>Archive</button>
        </div>
        {(verify.error || archive.error) && <span className="badge critical" role="alert">{(verify.error ?? archive.error)?.message}</span>}
      </div>
    </section>
  );
}
