import { useMutation, useQueryClient } from "@tanstack/react-query";
import { LogIn, LogOut, Users } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { S } from "../api/client";
import { teamLogin, teamLogout, useTeamMembers, useTeamOverview, useTeamProjects, useTeamSession } from "../api/hooks";
import { MagnitudeBars } from "../components/charts";
import { Badge, Card, Empty, ErrorBox, Loading, Note, PageHead, RowButton, Tile } from "../components/ui";
import { int, money, when } from "../lib/format";
import { useRange } from "../lib/nav";

const STALE_AFTER_H = 24;
const LOGIN_REASON = { not_configured: "Team server is not configured.", unavailable: "Sign-in is unavailable right now. Try again later." } as const;

/** Only absolute web URLs: javascript:, data:, relative and protocol-relative strings from the server are never navigated to. */
function safeUrl(u: string): string | null {
  try {
    const p = new URL(u); // no base: a relative or protocol-relative string throws
    return p.protocol === "https:" || p.protocol === "http:" ? p.href : null;
  } catch {
    return null;
  }
}

function Status({ m }: { m: S["TeamMemberOut"] }) {
  if (m.key_expired) return <Badge tone="critical">Key expired</Badge>;
  if (!m.last_synced_at) return <Badge tone="neutral">Never synced</Badge>;
  const at = Date.parse(m.last_synced_at);
  if (Number.isNaN(at)) return <Badge tone="neutral">Unknown</Badge>;
  const hours = (Date.now() - at) / 3_600_000; // a future time counts as fresh
  return hours <= STALE_AFTER_H ? <Badge tone="good">Synced</Badge> : <Badge tone="warning">Stale</Badge>;
}

function Members({ pid }: { pid: string }) {
  const { data: m, error, isLoading } = useTeamMembers(pid);
  return (
    <Card title="Last synced" flush>
      {isLoading ? <div style={{ padding: "1rem" }}><Loading what="Loading members" rows={2} /></div>
        : error || !m ? <ErrorBox error={error} />
        : m.state === "forbidden" ? <p className="muted small" style={{ padding: "0.6rem 1rem" }}>Only leads and admins can see who has synced.</p>
        : m.state !== "ok" ? <p className="muted small" style={{ padding: "0.6rem 1rem" }}>{m.reason || "Members could not be loaded."}</p>
        : (
          <div className="table-wrap" tabIndex={0} role="region" aria-label="Last synced">
            <table className="data">
              <thead><tr><th>Member</th><th>Last sync</th><th className="num">Changes</th><th>Status</th></tr></thead>
              <tbody>
                {m.members.map((x) => (
                  <tr key={x.user_id} data-testid="team-member-row">
                    <td className="mono">{x.email ?? x.user_id}</td>
                    <td title={x.last_synced_at ?? undefined}>{Number.isNaN(Date.parse(x.last_synced_at ?? "")) ? "—" : when(x.last_synced_at)}</td>
                    <td className="num">{int(x.changes)}</td>
                    <td><Status m={x} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      <p className="muted tiny" style={{ padding: "0.6rem 1rem" }}>
        Last time the team server accepted data from each member's machine. A member who has not synced is missing from the totals above.
      </p>
    </Card>
  );
}

function OverviewBlock({ pid }: { pid: string }) {
  const [range] = useRange();
  const { data: o, error, isLoading } = useTeamOverview(pid, range);
  if (isLoading) return <Loading what="Loading project" />;
  if (error || !o) return <ErrorBox error={error} />;
  const t = o.tiles;
  return (
    <>
      {o.state !== "ok" || !t ? <Note tone="warning" testId="team-state">{o.reason || "The team server did not return this project."}</Note> : (
        <>
          <div className="strip strip-6" role="group" aria-label="Team summary">
            {([["Changes", int(t.changes)], ["Cost", money(t.cost_usd)], ["Lines added", int(t.lines_added)], ["Lines removed", int(t.lines_removed)],
              ["PII changes", int(t.pii_changes)], ["Rules missed", int(t.policy_missed)]] as const).map(([label, value]) => (
              <div key={label} data-testid="team-tile" style={{ display: "contents" }}><Tile label={label} value={value} /></div>
            ))}
          </div>
          <div className="grid cols">
            <Card title="Top skills"><MagnitudeBars items={o.top_skills.map((s) => ({ label: s.skill_id, value: s.runs }))} unit=" runs" /></Card>
            <Card title="Models"><MagnitudeBars items={o.by_model.map((s) => ({ label: s.model, value: s.changes, sub: money(s.cost_usd) }))} unit=" changes" /></Card>
            <Card title="PII by type">
              <MagnitudeBars items={o.pii_by_type.map((s) => ({ label: s.type, value: s.count }))} />
              <p className="muted tiny" style={{ marginTop: 8 }}>PII types and counts only, from machines where PII counts sync is on.</p>
            </Card>
          </div>
          <Card title="Cost by day" flush>
            <div className="table-wrap" tabIndex={0} role="region" aria-label="Cost by day">
              <table className="data">
                <thead><tr><th>Day</th><th className="num">Cost</th></tr></thead>
                <tbody>
                  {o.cost_by_day.map((d) => (
                    <tr key={d.date}><td>{d.date}</td><td className="num">{money(Object.values(d.by_tool).reduce((a, n) => a + n, 0))}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </>
  );
}

const Detail = ({ pid }: { pid: string }) => <><OverviewBlock pid={pid} /><Members pid={pid} /></>;

function SessionBar({ showSignIn }: { showSignIn: boolean }) {
  const qc = useQueryClient();
  const { data: s } = useTeamSession();
  const [msg, setMsg] = useState<string | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["team"] });
  const out = useMutation({ mutationFn: teamLogout, onSuccess: refresh });
  const login = useMutation({
    mutationFn: teamLogin,
    onSuccess: (r) => {
      const to = r.url ? safeUrl(r.url) : null;
      if (to) window.location.assign(to);
      else setMsg(LOGIN_REASON[r.url ? "unavailable" : r.reason ?? "unavailable"]);
    },
    onError: () => setMsg(LOGIN_REASON.unavailable),
  });
  return (
    <>
      {s?.state === "signed_in" && (
        <>
          <span className="small" data-testid="team-session">Signed in as {s.email} ({s.role})</span>
          <button type="button" className="btn" data-testid="team-signout" disabled={out.isPending} onClick={() => out.mutate()}><LogOut aria-hidden="true" />Sign out</button>
        </>
      )}
      {showSignIn && s?.state !== "not_configured" && (
        <button type="button" className="btn primary" data-testid="team-signin" disabled={login.isPending} onClick={() => login.mutate()}><LogIn aria-hidden="true" />Sign in with SSO</button>
      )}
      {msg && <span className="small" role="status">{msg}</span>}
    </>
  );
}

export function Team() {
  const [sp, setSp] = useSearchParams();
  const { data: p, error, isLoading } = useTeamProjects();
  const { data: s } = useTeamSession();
  if (isLoading) return <div className="page"><Loading what="Loading team" /></div>;
  if (error || !p) return <div className="page"><ErrorBox error={error} /></div>;
  const pid = p.projects.find((x) => x.id === sp.get("project"))?.id ?? p.projects[0]?.id ?? "";
  const needsLogin = p.state === "login_required" || p.state === "unauthorized";
  const showSignIn = needsLogin || (s?.state === "signed_out" && p.state !== "ok" && p.state !== "not_configured");
  const select = (id: string) => setSp((q) => { q.set("project", id); return q; });
  return (
    <div className="page">
      <PageHead title="Team" description="Metadata synced from team members' machines. Prompts, diffs and PII values are never synced." actions={<SessionBar showSignIn={showSignIn} />} />
      {p.state === "not_configured" ? (
        <div data-testid="team-state"><Empty icon={Users} title="Team sync is not configured">
          {p.reason && <>{p.reason} </>}Set <span className="mono">sync.server</span> in the Seen config and put the team key in the environment variable named by the key setting. The key is never shown here.
        </Empty></div>
      ) : p.state !== "ok" ? (
        <Note tone="warning" testId="team-state">{p.reason || "The team server did not answer."}</Note>
      ) : p.projects.length === 0 ? (
        <Note tone="info">No projects are visible to this account. Leads and admins see every project; members see only their own.</Note>
      ) : (
        <>
          <Card title="Projects" flush>
            <div className="table-wrap" tabIndex={0} role="region" aria-label="Team projects">
              <table className="data">
                <thead><tr><th>Project</th><th className="num">Changes</th><th className="num">Cost 7 d</th><th>Last change</th></tr></thead>
                <tbody>
                  {p.projects.map((x) => (
                    <tr key={x.id} data-testid="team-project-row" aria-selected={x.id === pid} onClick={() => select(x.id)}>
                      <td><RowButton onClick={() => select(x.id)}>{x.name}</RowButton></td>
                      <td className="num">{int(x.changes)}</td>
                      <td className="num">{money(x.cost_7d)}</td>
                      <td>{when(x.last_change_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <Detail pid={pid} />
        </>
      )}
    </div>
  );
}
