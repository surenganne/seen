import { History } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { useTimeline } from "../api/hooks";
import { Empty, ErrorBox, GitStatus, Loading, PageHead, Pager } from "../components/ui";
import { day, short } from "../lib/format";
import { usePid, useRange, withRange } from "../lib/nav";

const PAGE = 50;
const clock = (iso: string | null) =>
  iso ? new Date(iso).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false }) : "—";

export function Timeline() {
  const pid = usePid();
  const [range] = useRange();
  const [sp, setSp] = useSearchParams();
  const page = Math.max(1, Number(sp.get("page") || 1));
  const actor = sp.get("actor") || undefined;
  const set = (k: string, v: string | undefined) =>
    setSp((p) => { if (v) p.set(k, v); else p.delete(k); if (k !== "page") p.delete("page"); return p; }, { replace: true });
  const { data, error, isLoading } = useTimeline(pid, { actor, days: range, page, page_size: PAGE });

  return (
    <div className="page">
      <PageHead
        title="Timeline"
        description="What changed in this repo, newest first, by day (IST): who asked, what it changed and which commit it ended on. Users are shown as pseudonymous ids, never logins or emails."
        actions={data && <span className="mono small muted" data-testid="timeline-count">{data.total} changes</span>}
      />
      {data && data.actors.length > 0 && (
        <div className="toolbar">
          <select className="select" aria-label="User" value={actor ?? ""} onChange={(e) => set("actor", e.target.value || undefined)}>
            <option value="">All users</option>
            {data.actors.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        </div>
      )}
      {isLoading && <Loading what="Loading timeline" />}
      {error && <ErrorBox error={error} />}
      {data && (data.total === 0 ? (
        <section className="panel"><Empty icon={History} title="No changes in this period">Changes appear here once Claude Code makes them in this repo with the Seen plugin enabled.</Empty></section>
      ) : (
        <>
          {data.days.map((d) => (
            <section key={d.day} className="panel" aria-label={day(d.day)} data-testid="timeline-day">
              <h2 className="small" style={{ padding: "10px 12px", margin: 0 }}>{day(d.day)} <span className="mono muted">{d.entries.length}</span></h2>
              <ul className="rows">
                {d.entries.map((e) => (
                  <li key={e.id} data-testid="timeline-entry">
                    <span style={{ minWidth: 0 }}>
                      <span className="mono small muted">{clock(e.started_at)}</span>{" "}
                      <Link to={withRange(`/p/${pid}/changes/${e.id}`, range)}>{e.request ?? e.summary ?? "Change"}</Link>
                      <div className="meta">
                        <span className="mono">{e.actor ?? "unknown user"}</span> · {e.files.length} {e.files.length === 1 ? "file" : "files"} · <span className="mono">+{e.added} −{e.removed}</span>
                        {e.commit && <> · <span className="mono">{short(e.commit)}</span></>}
                      </div>
                    </span>
                    <GitStatus status={e.git_status} />
                  </li>
                ))}
              </ul>
            </section>
          ))}
          <Pager page={data.page} pageSize={data.page_size} total={data.total} onPage={(n) => set("page", String(n))} what="changes" />
        </>
      ))}
    </div>
  );
}
