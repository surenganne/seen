import { Activity, X } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import type { S } from "../api/client";
import { useSessionActivity, useSessions } from "../api/hooks";
import { Badge, Empty, ErrorBox, Loading, PageHead } from "../components/ui";
import { int, money, short, when } from "../lib/format";
import { usePid } from "../lib/nav";

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
  const { data, error, isLoading } = useSessions(pid);
  const active = data?.filter((s) => s.status === "active").length ?? 0;
  return (
    <main className="page">
      <PageHead
        title="Sessions"
        description="Every Claude Code session in this repo, newest first. Active means no session end yet and activity in the last 30 minutes. Refreshes every 10 seconds."
        actions={data && <span className="mono small muted" data-testid="sessions-count">{data.length} sessions · {active} active</span>}
      />
      {isLoading && <Loading what="Loading sessions" />}
      {error && <ErrorBox error={error} />}
      {data && (
        <section className="panel">
          {data.length === 0 ? (
            <Empty icon={Activity} title="No sessions recorded yet">Sessions appear here once Claude Code starts in this repo with the Seen plugin enabled. A session that was already running when the plugin was installed is not recorded.</Empty>
          ) : (
            <div className="table-wrap">
              <table className="data" data-testid="sessions-table">
                <thead><tr><th>Session</th><th>Status</th><th>Started</th><th>Last activity</th><th>Model</th><th className="num">Turns</th><th className="num">Tool calls</th><th className="num">Files</th><th className="num">Cost</th></tr></thead>
                <tbody>
                  {data.map((s) => (
                    <tr key={s.id} className="clickable" tabIndex={0} onClick={() => select(s.id)} onKeyDown={(e) => e.key === "Enter" && select(s.id)}
                      aria-selected={open === s.id} data-testid="session-row" data-status={s.status}>
                      <td className="mono">{short(s.id, 8)}<div className="meta">{s.tool}{s.tool_version ? ` ${s.tool_version}` : ""}</div></td>
                      <td>{STATUS[s.status]}</td>
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
        </section>
      )}
      {open && data && <SessionDrawer pid={pid} s={data.find((x) => x.id === open)} id={open} onClose={() => select()} />}
    </main>
  );
}

function SessionDrawer({ pid, id, s, onClose }: { pid: string; id: string; s?: S["SessionOut"]; onClose: () => void }) {
  const { data, error, isLoading } = useSessionActivity(pid, id);
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
            <dt>Status</dt><dd>{STATUS[s.status]}</dd>
            <dt>Started</dt><dd className="mono">{when(s.started_at)}</dd>
            <dt>Ended</dt><dd className="mono">{s.ended_at ? when(s.ended_at) : "—"}</dd>
            <dt>Model</dt><dd className="mono">{s.models.join(", ") || "—"}</dd>
            <dt>Events</dt><dd className="mono">{s.events}</dd>
          </dl>
        )}
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
