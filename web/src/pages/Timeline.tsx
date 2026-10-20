import { History } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import type { S } from "../api/client";
import { useTimeline } from "../api/hooks";
import { Empty, ErrorBox, Loading, PageHead, Pager } from "../components/ui";
import { day, int, short } from "../lib/format";
import { usePid, useRange, withRange } from "../lib/nav";

const PAGE = 50;
const GAP_MIN = 120; // a quiet stretch this long gets a marker, so the spine does not pretend time was even
const clock = (iso: string | null) =>
  iso ? new Date(iso).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false }) : "—";

function quiet(newer: string | null, older: string | null): string | null {
  if (!newer || !older) return null;
  const min = Math.round((Date.parse(newer) - Date.parse(older)) / 60000);
  if (min < GAP_MIN) return null;
  const h = Math.floor(min / 60);
  return `${h} h${min % 60 ? ` ${min % 60} min` : ""}`;
}

const STATE = { committed: "committed", uncommitted: "not committed", reverted: "reverted" } as const;

function Node({ e, pid, range, max }: { e: S["TimelineEntry"]; pid: string; range: 7 | 14 | 28; max: number }) {
  const size = e.added + e.removed;
  const state = e.git_status ? STATE[e.git_status as keyof typeof STATE] ?? e.git_status : e.files.length ? "no git state" : "no file changes";
  return (
    <li className="tl-node" data-testid="timeline-entry" data-status={e.git_status ?? "none"}>
      <span className="tl-dot" aria-hidden="true" />
      <div className="tl-body">
        <Link className="tl-headline" to={withRange(`/p/${pid}/changes/${e.id}`, range)}>{e.headline}</Link>
        <div className="tl-meta">
          <span className="mono">{clock(e.started_at)}</span>
          <span className="mono">{e.actor ?? "unknown user"}</span>
          {e.areas.length > 0 && e.files.length > 0 && <span className="tl-areas">{e.areas.map((a) => <span key={a} className="tag mono">{a}</span>)}</span>}
          <span>{e.files.length} {e.files.length === 1 ? "file" : "files"}</span>
          <span>{e.git_status === "committed" && e.commit ? <>committed <span className="mono">{short(e.commit)}</span></> : state}</span>
        </div>
      </div>
      <div className="tl-mag" title={`${e.added} lines added, ${e.removed} removed`}>
        <span className="mono small">+{int(e.added)} −{int(e.removed)}</span>
        <span className="meter" aria-hidden="true" title="Bar length is the square root of lines changed, so one huge change does not flatten the rest"><span style={{ width: `${size ? Math.max(4, Math.round(100 * Math.sqrt(size / max))) : 0}%` }} /></span>
      </div>
    </li>
  );
}

function Day({ d, pid, range, max }: { d: S["TimelineDay"]; pid: string; range: 7 | 14 | 28; max: number }) {
  return (
    <section className="tl-day" aria-label={day(d.day)} data-testid="timeline-day">
      <header className="tl-day-head">
        <h2>{day(d.day)}</h2>
        <p className="mono small muted">
          {d.changes} {d.changes === 1 ? "change" : "changes"} · {d.files} {d.files === 1 ? "file" : "files"} · +{int(d.added)} −{int(d.removed)} · {d.commits} {d.commits === 1 ? "commit" : "commits"}
        </p>
      </header>
      <ol className="tl">
        {d.entries.map((e, i) => {
          const gap = i > 0 ? quiet(d.entries[i - 1]!.started_at, e.started_at) : null;
          return [
            gap && <li key={`${e.id}-gap`} className="tl-gap muted small">no file changes for {gap}</li>,
            <Node key={e.id} e={e} pid={pid} range={range} max={max} />,
          ];
        })}
      </ol>
    </section>
  );
}

export function Timeline() {
  const pid = usePid();
  const [range] = useRange();
  const [sp, setSp] = useSearchParams();
  const page = Math.max(1, Number(sp.get("page") || 1));
  const actor = sp.get("actor") || undefined;
  const all = sp.get("turns") === "all";
  const set = (k: string, v: string | undefined) =>
    setSp((p) => { if (v) p.set(k, v); else p.delete(k); if (k !== "page") p.delete("page"); return p; }, { replace: true });
  const { data, error, isLoading } = useTimeline(pid, { actor, days: range, all_turns: all || undefined, page, page_size: PAGE });
  const max = Math.max(1, ...(data?.days.flatMap((d) => d.entries.map((e) => e.added + e.removed)) ?? [1]));

  return (
    <div className="page">
      <PageHead
        title="Timeline"
        description="What changed in this repo, newest first. Each point is a request that changed files, with one line on what it did, who asked, where, and the commit it ended on. Turns that only talked are hidden here; Changes lists every request. Users are pseudonymous ids."
        actions={data && <span className="mono small muted" data-testid="timeline-count">{data.total} {data.total === 1 ? "change" : "changes"}</span>}
      />
      <div className="toolbar">
        {data && data.actors.length > 0 && (
          <select className="select" aria-label="User" value={actor ?? ""} onChange={(e) => set("actor", e.target.value || undefined)}>
            <option value="">All users</option>
            {data.actors.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        )}
        <button type="button" className="chip" aria-pressed={all} onClick={() => set("turns", all ? undefined : "all")}>Include turns without file changes</button>
        {data && !all && data.quiet_hidden > 0 && <span className="muted small" data-testid="timeline-hidden">{int(data.quiet_hidden)} turns without file changes hidden</span>}
      </div>
      {isLoading && <Loading what="Loading timeline" />}
      {error && <ErrorBox error={error} />}
      {data && (data.total === 0 ? (
        <section className="panel"><Empty icon={History} title="No changes in this period">Changes appear here once Claude Code edits files in this repo with the Seen plugin enabled.</Empty></section>
      ) : (
        <>
          {data.days.map((d) => <Day key={d.day} d={d} pid={pid} range={range} max={max} />)}
          <Pager page={data.page} pageSize={data.page_size} total={data.total} onPage={(n) => set("page", String(n))} what="changes" />
        </>
      ))}
    </div>
  );
}
