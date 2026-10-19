import { Brain, ChevronDown, ChevronRight, FileWarning, Search, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, type S, unwrap } from "../api/client";
import { useMemory, useWrite } from "../api/hooks";
import { Badge, Card, Empty, ErrorBox, Loading, Note, PageHead } from "../components/ui";
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
    <div className="page">
      <PageHead
        title="Memory"
        description="Notes in .seen/memory, injected into every session. Stale means the file it describes changed after it was verified."
        actions={data && (
          <div className="checks" data-testid="memory-counts">
            {Object.entries(data.counts).map(([k, n]) => (
              <Badge key={k} tone={STATUS_TONE[k as keyof typeof STATUS_TONE] ?? "neutral"}>{n} {k}</Badge>
            ))}
          </div>
        )}
      />
      <div className="toolbar" role="search">
        <label className="search">
          <Search aria-hidden="true" />
          <input className="input" type="search" aria-label="Search memory" placeholder="Search memory" defaultValue={f.q}
            onChange={(e) => set("q", e.target.value || undefined)} />
        </label>
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
      <Note tone="info" icon={ShieldAlert}>
        The model treats memory as guidance. Review <span className="mono">.seen/memory/</span> like code (a CODEOWNERS rule helps) and never store secrets or client data there.
      </Note>
      {isLoading && <Loading what="Loading memory" />}
      {error && <ErrorBox error={error} />}
      {data && (
        <section className="panel">
          {data.items.length === 0 ? <Empty icon={Brain} title="No memory matches">Clear a filter, or add a note with <code>seen memory add</code>.</Empty> : (
            <ul className="memories" data-testid="memory-list">
              {data.items.map((m) => <MemoryItem key={m.id} m={m} pid={pid} />)}
            </ul>
          )}
        </section>
      )}
      {data && data.invalid.length > 0 && (
        <Card title="Files Seen could not read" flush aside={<Badge tone="critical">{data.invalid.length} invalid</Badge>}>
          <ul className="rows">
            {data.invalid.map((m) => (
              <li key={m.path}><span className="path"><FileWarning size={14} aria-hidden="true" style={{ verticalAlign: "-2px", marginRight: 6 }} />{m.path}</span><span className="muted small">{m.error}</span></li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

function MemoryItem({ m, pid }: { m: S["MemoryOut"]; pid: string }) {
  const [open, setOpen] = useState(m.status === "stale");
  const [range] = useRange();
  const verify = useWrite(() => unwrap(api.POST("/api/memory/{mid}/verify", { params: { path: { mid: m.id }, query: { project: pid } } })));
  const archive = useWrite(() => unwrap(api.POST("/api/memory/{mid}/archive", { params: { path: { mid: m.id }, query: { project: pid } } })));
  const err = verify.error ?? archive.error;
  return (
    <li className="memory" data-testid="memory-card" data-status={m.status} data-id={m.id}>
      <div className="memory-head">
        <span className="mono memory-id">{m.id}</span>
        <span className="checks">
          <span className="tag">{m.type}</span>
          <span className="mono tiny muted">{m.scope}</span>
          <Badge tone={STATUS_TONE[m.status]}>{m.status}</Badge>
        </span>
      </div>
      <p className="prose" style={{ margin: 0 }}>{m.body}</p>
      {open && (
        <dl className="kv">
          {m.stale_reason && (<><dt>Why stale</dt><dd data-testid="stale-reason">{m.stale_reason}</dd></>)}
          <dt>Describes</dt><dd className="path">{m.file_ref ? <Link to={withRange(`/p/${pid}/changes`, range, { file: m.file_ref })}>{m.file_ref}</Link> : "—"}</dd>
          <dt>Verified</dt><dd className="mono">{m.verified_at ? when(m.verified_at) : "never"}</dd>
          <dt>Source change</dt><dd className="mono">{m.source_change ? <Link to={withRange(`/p/${pid}/changes/${m.source_change}`, range)}>{short(m.source_change, 14)}</Link> : "—"}</dd>
          <dt>Loaded in</dt><dd className="mono">{m.used_in} changes</dd>
          <dt>Stored at</dt><dd className="path muted">{m.path}</dd>
        </dl>
      )}
      <div className="memory-actions">
        <button type="button" className="btn ghost sm" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? <ChevronDown aria-hidden="true" /> : <ChevronRight aria-hidden="true" />}{open ? "Less" : "Details"}
        </button>
        <span style={{ flex: 1 }} />
        <button type="button" className="btn sm" disabled={verify.isPending} onClick={() => verify.mutate(undefined)}>
          {m.status === "verified" ? "Verify again" : "Re-verify"}
        </button>
        <button type="button" className="btn danger sm" disabled={archive.isPending} onClick={() => archive.mutate(undefined)}>Archive</button>
      </div>
      {err && <Note tone="critical">{err.message}</Note>}
    </li>
  );
}
