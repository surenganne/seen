import { Activity, ListChecks, X } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import type { S } from "../api/client";
import { type SessionKind, useSessionActivity, useSessions } from "../api/hooks";
import { Badge, Empty, ErrorBox, Loading, PageHead, Pager, RowButton } from "../components/ui";
import { int, money, short, when } from "../lib/format";
import { usePid, useRange, withRange } from "../lib/nav";

const STATUS = {
  active: <Badge tone="good">active</Badge>,
  ended: <Badge tone="neutral">ended</Badge>,
  incomplete: <Badge tone="warning" title="No session end was recorded and nothing has happened for 30 minutes">incomplete</Badge>,
} as const;

export function Sessions() {
  const pid = usePid();
  const [sp, setSp] = useSearchParams();
  const open = sp.get("session") || undefined;
  const select = (id?: string) => setSp((p) => { if (id) p.set("session", id); else p.delete("session"); return p; }, { replace: true });
  const page = Math.max(1, Number(sp.get("page") || 1));
  const kind: SessionKind = (["yours", "background", "all"] as const).find((k) => k === sp.get("kind")) ?? "yours";
  const { data, error, isLoading } = useSessions(pid, page, kind);
  const goPage = (n: number) => setSp((p) => { p.set("page", String(n)); return p; }, { replace: true });
  const goKind = (k: SessionKind) => setSp((p) => { p.set("kind", k); p.delete("page"); p.delete("session"); return p; }, { replace: true });
  return (
    <div className="page">
      <PageHead
        title="Sessions"
        description="Claude Code sessions in this repo, newest first. Yours are the ones you started; background sessions were started by plugins through the Agent SDK (for example a reflector or summariser) and still cost tokens. Active means no session end yet and activity in the last 30 minutes. Refreshes every 10 seconds."
        actions={data && <span className="mono small muted" data-testid="sessions-count">{data.total} sessions · {data.active} active</span>}
      />
      {data && (
        <div className="seg" role="group" aria-label="Which sessions" style={{ alignSelf: "start" }} data-testid="session-kind">
          {(["yours", "background", "all"] as const).map((k) => (
            <button key={k} type="button" aria-pressed={kind === k} onClick={() => goKind(k)}>
              {k === "yours" ? "Yours" : k === "background" ? "Background" : "All"} <span className="mono">{data.counts[k]}</span>
            </button>
          ))}
        </div>
      )}
      {isLoading && <Loading what="Loading sessions" />}
      {error && <ErrorBox error={error} />}
      {data && (
        <section className="panel">
          {data.total === 0 ? (
            <Empty icon={Activity} title={kind === "background" ? "No background sessions" : kind === "yours" && data.counts.all > 0 ? "None of your sessions are recorded yet" : "No sessions recorded yet"}>Sessions appear here once Claude Code starts in this repo with the Seen plugin enabled. A session that was already running when the plugin was installed is not recorded.</Empty>
          ) : (
            <div className="table-wrap" tabIndex={0} role="region" aria-label="Sessions">
              <table className="data" data-testid="sessions-table">
                <thead><tr><th>Session</th><th>Status</th><th>Started</th><th>Last activity</th><th>Model</th><th className="num">Turns</th><th className="num">Tool calls</th><th className="num">Files</th><th className="num">Cost</th></tr></thead>
                <tbody>
                  {data.items.map((s) => (
                    <tr key={s.id} className="clickable" onClick={() => select(s.id)}
                      aria-selected={open === s.id} data-testid="session-row" data-status={s.status}>
                      <td className="mono"><RowButton onClick={() => select(s.id)}>{short(s.id, 8)}</RowButton><div className="meta">{s.tool}{s.tool_version ? ` ${s.tool_version}` : ""}</div></td>
                      <td><span className="checks">{STATUS[s.status]}{s.source === "imported" && <span className="tag" title="Recorded afterwards from the Claude Code transcript">imported</span>}{s.background && <span className="tag" title={`Started by a plugin through the Agent SDK (entrypoint ${s.entrypoint})`}>background</span>}</span></td>
                      <td className="when">{when(s.started_at)}</td>
                      <td className="when">{when(s.last_event_at)}</td>
                      <td className="mono small">{s.models.join(", ") || "—"}</td>
                      <td className="num">{s.turns}</td>
                      <td className="num">{int(s.tool_calls)}</td>
                      <td className="num">{s.files}</td>
                      <td className="num">{money(s.cost_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <Pager page={data.page} pageSize={data.page_size} total={data.total} onPage={goPage} what="sessions" />
        </section>
      )}
      {open && data && <SessionDrawer pid={pid} s={data.items.find((x) => x.id === open)} id={open} onClose={() => select()} />}
    </div>
  );
}

function SessionDrawer({ pid, id, s, onClose }: { pid: string; id: string; s?: S["SessionOut"]; onClose: () => void }) {
  const { data, error, isLoading } = useSessionActivity(pid, id);
  const [range] = useRange();
  const events = data?.items.slice().reverse();
  return (
    <aside className="drawer" aria-label={`Session ${short(id, 8)}`} data-testid="session-activity">
      <div className="drawer-head">
        <h2 className="mono" style={{ fontWeight: 500 }}>Session {short(id, 8)}</h2>
        <button type="button" className="btn ghost icon-btn" onClick={onClose} aria-label="Close"><X aria-hidden="true" /></button>
      </div>
      <div className="drawer-body">
        {s && (
          <dl className="kv">
            <dt>Status</dt><dd className="checks">{STATUS[s.status]}{s.source === "imported" && <span className="tag">imported</span>}{s.background && <span className="tag" title={`Started by a plugin through the Agent SDK (entrypoint ${s.entrypoint})`}>background</span>}</dd>
            <dt>Started by</dt><dd className="mono">{s.entrypoint ?? "not recorded"}</dd>
            <dt>Started</dt><dd className="mono">{when(s.started_at)}</dd>
            <dt>Ended</dt><dd className="mono">{s.ended_at ? when(s.ended_at) : "—"}</dd>
            <dt>Model</dt><dd className="mono">{s.models.join(", ") || "—"}</dd>
            <dt>Events</dt><dd className="mono">{s.events}</dd>
          </dl>
        )}
        <Link className="btn sm" style={{ alignSelf: "start" }} to={withRange(`/p/${pid}/changes`, range, { session: id })} data-testid="session-changes">
          <ListChecks aria-hidden="true" />{s ? `View ${s.turns} ${s.turns === 1 ? "change" : "changes"}` : "View changes"}
        </Link>
        <section>
          <h3 style={{ marginBottom: 6 }}>Activity{data && data.items.length >= data.page_size ? <span className="muted small" style={{ fontWeight: 400 }}> · latest {data.page_size}, full history in Audit</span> : null}</h3>
          {isLoading && <Loading what="Loading activity" rows={4} />}
          {error && <ErrorBox error={error} />}
          {events && (events.length === 0 ? <Empty icon={Activity} title="No events" /> : (
            <div className="panel">
              <ul className="rows" data-testid="activity-list">
                {events.map((e) => (
                  <li key={e.seq}>
                    <span style={{ minWidth: 0 }}>
                      <span className="mono">{e.type}</span>
                      {e.subject && <span className="path muted small"> {e.subject}</span>}
                    </span>
                    <span className="mono tiny muted" style={{ whiteSpace: "nowrap" }}>{when(e.occurred_at)}{e.outcome !== "ok" ? ` · ${e.outcome}` : ""}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
          <p className="muted tiny" style={{ marginTop: 6 }}>Tool names, paths, counts and hashes only. Command arguments, prompts and file contents are never logged.</p>
        </section>
      </div>
    </aside>
  );
}
