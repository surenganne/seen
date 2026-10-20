import { Bot, EyeOff, Fingerprint, type LucideIcon, Search, User } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import type { S } from "../api/client";
import { ApiError } from "../api/client";
import { useProvenanceFile, useProvenanceFiles } from "../api/hooks";
import { Card, Empty, ErrorBox, Loading, Note, PageHead, Pager, RowButton } from "../components/ui";
import { int, when } from "../lib/format";
import { usePid, useRange, withRange } from "../lib/nav";

type Who = "agent" | "human" | "not_observed";
/** Word and icon together: who wrote a line is never colour alone. */
const WHO: Record<Who, { label: string; icon: LucideIcon; tone: string; meaning: string }> = {
  agent: { label: "Agent", icon: Bot, tone: "accent", meaning: "an agent request" },
  human: { label: "Human", icon: User, tone: "neutral", meaning: "not an agent request" },
  not_observed: { label: "Not observed", icon: EyeOff, tone: "neutral", meaning: "Seen could not have seen this" },
};
const WHOS = Object.keys(WHO) as Who[];

const lines = (b: S["ProvenanceBlock"]) => (b.start === b.end ? `Line ${b.start}` : `Lines ${b.start}–${b.end}`);

function WhoBadge({ who }: { who: Who }) {
  const { label, icon: I, tone } = WHO[who];
  return <span className={`badge ${tone}`}><I aria-hidden="true" strokeWidth={2.25} />{label}</span>;
}

function Block({ b, pid, range }: { b: S["ProvenanceBlock"]; pid: string; range: 7 | 14 | 28 }) {
  const who = b.who as Who;
  return (
    <li className="prov-block" data-testid="prov-block" data-who={who}>
      <WhoBadge who={who} />
      <span className="mono small">{lines(b)}</span>
      {who === "agent" ? (
        <div className="prov-main">
          {b.change_id ? <Link to={withRange(`/p/${pid}/changes/${b.change_id}`, range)}>{b.headline ?? "(no summary)"}<span className="sr-only">, {lines(b).toLowerCase()}</span></Link> : (b.headline ?? "(no summary)")}
          <div className="prov-meta">
            <span className="mono">{when(b.started_at)}</span>
            {b.model && <span className="mono">{b.model}</span>}
            {b.skills.map((s) => <span key={s} className="tag mono">{s}</span>)}
          </div>
        </div>
      ) : <span className="prov-main muted small">{WHO[who].meaning}</span>}
    </li>
  );
}

function BlockTable({ blocks, pid, range, path }: { blocks: S["ProvenanceBlock"][]; pid: string; range: 7 | 14 | 28; path: string }) {
  return (
    <table className="data" aria-label={`Line blocks of ${path}`}>
      <thead><tr><th>Lines</th><th>Who</th><th>Headline</th><th>Time (IST)</th><th>Model</th><th>Change</th></tr></thead>
      <tbody>
        {blocks.map((b) => (
          <tr key={`${b.start}-${b.end}`}>
            <td className="mono">{b.start === b.end ? b.start : `${b.start}–${b.end}`}</td>
            <td><WhoBadge who={b.who as Who} /></td>
            <td>{b.headline ?? <span className="muted">—</span>}</td>
            <td className="mono">{when(b.started_at)}</td>
            <td className="mono">{b.model ?? "—"}</td>
            <td>{b.change_id ? <Link to={withRange(`/p/${pid}/changes/${b.change_id}`, range)} aria-label={`Open change: ${b.headline ?? "no summary"}, ${lines(b).toLowerCase()}`}>Open change</Link> : <span className="muted">—</span>}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Result({ f, pid, range }: { f: S["ProvenanceFile"]; pid: string; range: 7 | 14 | 28 }) {
  const [asTable, setAsTable] = useState(false);
  const blocks = f.blocks.filter((b) => b.who !== "neutral");
  if (f.reason) return <Note tone="info" testId="prov-note">No lines attributed: {f.reason}</Note>;
  const n = (k: string) => f.counts[k] ?? 0;
  return (
    <>
      <Card title="Summary" aside={<span className="hint mono">{f.path} @ {f.rev}</span>}>
        <ul className="prov-counts" data-testid="prov-count">
          {WHOS.map((w) => {
            const I = WHO[w].icon;
            return <li key={w}><I aria-hidden="true" /><strong>{WHO[w].label}</strong><span className="mono">{int(n(w))} {n(w) === 1 ? "line" : "lines"}</span></li>;
          })}
        </ul>
        {n("neutral") > 0 && <p className="muted small" style={{ marginTop: 8 }}>{int(n("neutral"))} blank {n("neutral") === 1 ? "line" : "lines"} left out.</p>}
        <p className="small prose" style={{ marginTop: 8 }}>Not observed means Seen could not have seen it; it is not a claim that a person wrote it.</p>
        <p className="muted small prose">Attribution follows line content recorded when an agent edited a file; edits made through Bash are not attributed.</p>
      </Card>
      {f.truncated && <Note tone="warning" testId="prov-note">This result is partial: blame ran out of time, so lines after the last block shown are not attributed.</Note>}
      <Card title="Blocks" flush aside={<button type="button" className="btn ghost sm" aria-pressed={asTable} onClick={() => setAsTable(!asTable)}>Table view</button>}>
        {blocks.length === 0 ? <Empty icon={Fingerprint} title="No line blocks returned for this file" /> : (
          asTable ? (
            <div className="table-wrap" tabIndex={0} role="region" aria-label={`Line blocks of ${f.path}, as a table`}>
              <BlockTable blocks={blocks} pid={pid} range={range} path={f.path} />
            </div>
          ) : (
            <div className="prov-scroll" tabIndex={0} role="region" aria-label={`Line blocks of ${f.path}`}>
              <ul className="prov-list">{blocks.map((b) => <Block key={`${b.start}-${b.end}`} b={b} pid={pid} range={range} />)}</ul>
            </div>
          )
        )}
      </Card>
    </>
  );
}

const SORTS = [["recent", "Most recent"], ["requests", "Most requests"], ["lines", "Most lines"]] as const;
const PAGE = 50;

/** Files your requests changed, ranked. Built from the ledger, so it works with no repo on this machine. */
function FileList({ pid, path }: { pid: string; path?: string }) {
  const [range] = useRange();
  const nav = useNavigate();
  const [sp, setSp] = useSearchParams();
  const q = sp.get("q") ?? "";
  const sort = SORTS.some(([k]) => k === sp.get("sort")) ? sp.get("sort")! : "recent";
  const page = Math.max(1, Number(sp.get("page")) || 1);
  const [draft, setDraft] = useState(q);
  useEffect(() => setDraft(q), [q]);
  const { data, error, isLoading } = useProvenanceFiles(pid, { q: q || undefined, sort, page, days: range, page_size: PAGE });
  const set = (k: string, v: string | undefined) =>
    setSp((p) => { if (v) p.set(k, v); else p.delete(k); if (k !== "page") p.delete("page"); return p; }, { replace: true });
  const open = (f: string) => nav({ search: (() => { const p = new URLSearchParams(sp); p.set("path", f); return p.toString(); })() });
  const submit = (e: FormEvent) => { e.preventDefault(); set("q", draft.trim() || undefined); };
  return (
    <>
      <div className="toolbar">
        <form className="toolbar" role="search" aria-label="Search files" onSubmit={submit} style={{ flex: "1 1 18rem" }}>
          <input className="input mono" style={{ flex: "1 1 12rem" }} aria-label="Filter files" data-testid="prov-filter" value={draft} onChange={(e) => setDraft(e.target.value)}
            placeholder="Part of a path, e.g. payments" autoComplete="off" spellCheck={false} />
          <button type="submit" className="btn"><Search aria-hidden="true" />Filter</button>
          {q && data?.total !== 0 && <button type="button" className="btn ghost" onClick={() => set("q", undefined)}>Clear filter</button>}
        </form>
        <div className="seg" role="group" aria-label="Sort files" data-testid="prov-sort">
          {SORTS.map(([k, label]) => <button key={k} type="button" aria-pressed={sort === k} onClick={() => set("sort", k === "recent" ? undefined : k)}>{label}</button>)}
        </div>
      </div>
      {isLoading && <Loading what="Loading files" rows={3} />}
      {error && <ErrorBox error={error} />}
      {data && (data.total === 0 ? (
        <Empty icon={Fingerprint} title="No files changed by requests in this period">
          Checked: files edited by your requests in the last {range} days{q ? <>, whose path contains <span className="mono">{q.slice(0, 60)}</span></> : ""}. Background sessions are left out.
          {q && <> <button type="button" className="btn sm" onClick={() => set("q", undefined)}>Clear filter</button></>}
        </Empty>
      ) : (
        <>
          <div className="table-wrap" tabIndex={0} role="region" aria-label="Files agents changed">
            <table className="data" aria-label="Files agents changed" data-testid="prov-files">
              <thead><tr><th>File</th><th className="num">Requests</th><th className="num">Lines</th><th>Last changed (IST)</th></tr></thead>
              <tbody>
                {data.items.map((f) => (
                  <tr key={f.path} className="clickable" data-testid="prov-file-row" aria-current={f.path === path ? "true" : undefined} onClick={() => open(f.path)}>
                    <td className="mono" style={{ minWidth: "16rem" }}><RowButton onClick={() => open(f.path)}>{f.path}</RowButton></td>
                    <td className="num">{int(f.requests)}</td>
                    <td className="num"><span className="plus">+{int(f.added)}</span> <span className="minus">−{int(f.removed)}</span></td>
                    <td className="when">{when(f.last_changed_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pager page={data.page} pageSize={data.page_size} total={data.total} onPage={(n) => set("page", String(n))} what="files" />
        </>
      ))}
    </>
  );
}

export function Provenance() {
  const pid = usePid();
  const [range] = useRange();
  const [sp] = useSearchParams();
  const path = sp.get("path")?.trim() || undefined;
  const [listOpen, setListOpen] = useState(false);
  useEffect(() => setListOpen(false), [path]);
  const notebook = !!path && path.toLowerCase().endsWith(".ipynb");
  const { data, error, isLoading } = useProvenanceFile(pid, notebook ? undefined : path);
  const missing = error instanceof ApiError && error.status === 404;

  return (
    <div className="page" data-testid="provenance">
      <PageHead
        title="Provenance"
        description="Who wrote each line of a file: an agent request Seen recorded, a person, or not observed. Blame finds the commit for every line, then matches each line to what an agent wrote in a request."
      />
      {!path ? (
        <Card title="Files agents changed" aside={<span className="hint">your requests, last {range} days</span>}>
          <p className="small prose" style={{ marginBottom: 12 }}>Pick a file to see which lines an agent wrote.</p>
          <FileList pid={pid} />
        </Card>
      ) : (
        <details className="panel" open={listOpen} onToggle={(e) => setListOpen(e.currentTarget.open)}>
          <summary className="panel-head"><h2>Choose another file</h2></summary>
          <div className="panel-body">{listOpen && <FileList pid={pid} path={path} />}</div>
        </details>
      )}
      {notebook && <Note tone="info" testId="prov-note">Notebook files are not line-attributed: a .ipynb file is JSON, so its lines do not map to the cells an agent edited.</Note>}
      {isLoading && <Loading what="Loading provenance" />}
      {error && (missing ? <Note tone="info" testId="prov-note">{error.message}</Note> : <ErrorBox error={error} />)}
      {data && <Result f={data} pid={pid} range={range} />}
    </div>
  );
}
