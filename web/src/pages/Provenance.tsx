import { Bot, EyeOff, Fingerprint, type LucideIcon, User } from "lucide-react";
import { type FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import type { S } from "../api/client";
import { ApiError } from "../api/client";
import { useChanges, useProvenanceFile } from "../api/hooks";
import { Card, Empty, ErrorBox, Loading, Note, PageHead } from "../components/ui";
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

export function Provenance() {
  const pid = usePid();
  const [range] = useRange();
  const [sp, setSp] = useSearchParams();
  const path = sp.get("path")?.trim() || undefined;
  const [draft, setDraft] = useState(path ?? "");
  useEffect(() => setDraft(path ?? ""), [path]);
  const notebook = !!path && path.toLowerCase().endsWith(".ipynb");
  const { data, error, isLoading } = useProvenanceFile(pid, notebook ? undefined : path);
  const { data: changes } = useChanges(pid, { page_size: 200 });
  const files = useMemo(() => Array.from(new Set(changes?.items.flatMap((c) => c.files) ?? [])).sort(), [changes]);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const v = draft.trim();
    setSp((p) => { if (v) p.set("path", v); else p.delete("path"); return p; });
  };
  const missing = error instanceof ApiError && error.status === 404;

  return (
    <div className="page" data-testid="provenance">
      <PageHead
        title="Provenance"
        description="Who wrote each line of a file: an agent request Seen recorded, a person, or not observed. Blame finds the commit for every line, then matches each line to what an agent wrote in a request."
      />
      <form className="toolbar" onSubmit={submit} role="search" aria-label="Choose a file">
        <label htmlFor="prov-path" className="small muted">File path</label>
        <input id="prov-path" className="input mono" style={{ flex: "1 1 18rem" }} data-testid="prov-path" list="prov-files" value={draft}
          onChange={(e) => setDraft(e.target.value)} placeholder="src/app.py" autoComplete="off" spellCheck={false} />
        <datalist id="prov-files">{files.map((f) => <option key={f} value={f} />)}</datalist>
        <button type="submit" className="btn primary">Show provenance</button>
      </form>
      {!path && (
        <section className="panel"><Empty icon={Fingerprint} title="Choose a file">
          Type a path relative to the repo, or pick one an agent recently changed. You will see each run of lines marked agent, human or not observed, with the request behind the agent ones.
        </Empty></section>
      )}
      {notebook && <Note tone="info" testId="prov-note">Notebook files are not line-attributed: a .ipynb file is JSON, so its lines do not map to the cells an agent edited.</Note>}
      {isLoading && <Loading what="Loading provenance" />}
      {error && (missing ? <Note tone="info" testId="prov-note">{error.message}</Note> : <ErrorBox error={error} />)}
      {data && <Result f={data} pid={pid} range={range} />}
    </div>
  );
}
