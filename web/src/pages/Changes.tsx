import { Activity, FileCode2, Search, ShieldAlert, Sparkles, X } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import type { S } from "../api/client";
import { type ChangeFilters, useChanges, useSkills } from "../api/hooks";
import { ChangesTable } from "../components/ChangesTable";
import { ErrorBox, Loading, PageHead, Pager } from "../components/ui";
import { money, short, when } from "../lib/format";
import { usePid, useRange, withRange } from "../lib/nav";

const bool = (v: string | null) => (v === "true" ? true : undefined);
const PAGE = 50;

/** Consecutive changes of the same session, in the order the page returned them. */
function bySession(rows: S["ChangeRow"][]) {
  const groups: { sid: string; rows: S["ChangeRow"][] }[] = [];
  for (const r of rows) {
    const sid = r.session_id ?? "";
    const g = groups.find((x) => x.sid === sid);
    if (g) g.rows.push(r);
    else groups.push({ sid, rows: [r] });
  }
  return groups;
}

export function Changes() {
  const pid = usePid();
  const [range] = useRange();
  const [sp, setSp] = useSearchParams();
  const grouped = sp.get("view") !== "list";
  const page = Math.max(1, Number(sp.get("page") || 1));
  const f: ChangeFilters = {
    kind: (["yours", "background", "all"] as const).find((k) => k === sp.get("kind")) ?? "yours",
    q: sp.get("q") || undefined,
    tool: sp.get("tool") || undefined,
    status: sp.get("status") || undefined,
    file: sp.get("file") || undefined,
    skill: sp.get("skill") || undefined,
    session: sp.get("session") || undefined,
    policy_missed: bool(sp.get("policy_missed")),
    pii: bool(sp.get("pii")),
    days: range,
    sort: grouped ? "time" : sp.get("sort") || "time",
    dir: grouped ? "desc" : (sp.get("dir") as "asc" | "desc") || "desc",
    page,
    page_size: PAGE,
  };
  // any filter change goes back to page 1
  const set = (k: string, v: string | undefined) =>
    setSp((p) => {
      if (v) p.set(k, v);
      else p.delete(k);
      if (k !== "page") p.delete("page");
      return p;
    }, { replace: true });
  const toggle = (k: string, v: string) => set(k, sp.get(k) === v ? undefined : v);
  const { data, error, isLoading } = useChanges(pid, f);
  const { data: skills } = useSkills(pid);

  return (
    <div className="page">
      <PageHead
        title="Changes"
        description="One row per request you made, with what it changed, grouped by session. Background shows turns that plugins ran through the Agent SDK. Open a row for files, tokens, memory, skills and PII."
        actions={<span className="mono small muted" data-testid="changes-count">{data ? `${data.total} changes · ${money(data.cost_usd)}` : ""}</span>}
      />
      <div className="toolbar" role="search">
        <label className="search">
          <Search aria-hidden="true" />
          <input className="input" type="search" placeholder="Search requests, results and files" aria-label="Search changes"
            defaultValue={f.q} onChange={(e) => set("q", e.target.value || undefined)} />
        </label>
        <select className="select" aria-label="Git status" value={f.status ?? ""} onChange={(e) => set("status", e.target.value || undefined)}>
          <option value="">Any git status</option>
          <option value="committed">Committed</option>
          <option value="uncommitted">Uncommitted</option>
          <option value="reverted">Reverted</option>
        </select>
        <select className="select" aria-label="Skill" value={f.skill ?? ""} onChange={(e) => set("skill", e.target.value || undefined)}>
          <option value="">Any skill</option>
          {skills?.filter((s) => s.runs > 0).map((s) => <option key={s.id} value={s.id}>{s.id}</option>)}
        </select>
        <div className="seg" role="group" aria-label="View">
          <button type="button" aria-pressed={grouped} onClick={() => set("view", undefined)}>By session</button>
          <button type="button" aria-pressed={!grouped} onClick={() => set("view", "list")}>All changes</button>
        </div>
      </div>
      <div className="toolbar" aria-label="Filters">
        {data && (
          <div className="seg" role="group" aria-label="Whose requests" data-testid="change-kind">
            {(["yours", "background", "all"] as const).map((k) => (
              <button key={k} type="button" aria-pressed={f.kind === k} onClick={() => set("kind", k)}>
                {k === "yours" ? "Yours" : k === "background" ? "Background" : "All"} <span className="mono">{data.counts[k]}</span>
              </button>
            ))}
          </div>
        )}
        <button type="button" className="chip" aria-pressed={f.tool === "claude-code"} onClick={() => toggle("tool", "claude-code")}>claude-code</button>
        <button type="button" className="chip" aria-pressed={!!f.policy_missed} onClick={() => toggle("policy_missed", "true")}><Sparkles aria-hidden="true" />Skill policy missed</button>
        <button type="button" className="chip" aria-pressed={!!f.pii} onClick={() => toggle("pii", "true")}><ShieldAlert aria-hidden="true" />PII exposed</button>
        {f.file && (
          <button type="button" className="chip" aria-pressed onClick={() => set("file", undefined)} aria-label={`Clear file filter ${f.file}`}>
            <FileCode2 aria-hidden="true" /><span className="mono">{f.file}</span><X aria-hidden="true" />
          </button>
        )}
        {f.session && (
          <button type="button" className="chip" aria-pressed onClick={() => set("session", undefined)} aria-label={`Clear session filter ${short(f.session, 8)}`}>
            <Activity aria-hidden="true" /><span className="mono">session {short(f.session, 8)}</span><X aria-hidden="true" />
          </button>
        )}
      </div>
      {isLoading && <Loading what="Loading changes" />}
      {error && <ErrorBox error={error} />}
      {data && !grouped && (
        <section className="panel">
          <ChangesTable
            rows={data.items}
            pid={pid}
            sort={{
              sort: f.sort ?? "time",
              dir: f.dir ?? "desc",
              onSort: (s) => {
                const dir = f.sort === s && f.dir === "desc" ? "asc" : "desc";
                setSp((p) => { p.set("sort", s); p.set("dir", dir); p.delete("page"); return p; }, { replace: true });
              },
            }}
          />
          <Pager page={data.page} pageSize={data.page_size} total={data.total} onPage={(p) => set("page", String(p))} what="changes" />
        </section>
      )}
      {data && grouped && (
        <>
          {data.items.length === 0 && <section className="panel"><ChangesTable rows={[]} pid={pid} /></section>}
          {bySession(data.items).map((g) => {
            const first = g.rows[g.rows.length - 1]!;  // groups are never empty
            const cost = g.rows.reduce((a, c) => a + c.cost_usd, 0);
            return (
              <section key={g.sid} className="panel" data-testid="session-group">
                <div className="panel-head group-head">
                  <span>
                    <span className="title mono">Session {short(g.sid, 8)}</span>
                    <span className="muted small"> · {g.rows.length} {g.rows.length === 1 ? "change" : "changes"} on this page, from {when(first.started_at)} · {money(cost)}</span>
                  </span>
                  <span className="checks">
                    {!f.session && <Link className="btn ghost sm" to={withRange(`/p/${pid}/changes`, range, { session: g.sid })}>Only this session</Link>}
                    <Link className="btn ghost sm" to={withRange(`/p/${pid}/sessions`, range, { session: g.sid })}><Activity aria-hidden="true" />Activity</Link>
                  </span>
                </div>
                <ChangesTable rows={g.rows} pid={pid} compact />
              </section>
            );
          })}
          {(data.total > data.page_size || data.page > 1) && <div className="panel"><Pager page={data.page} pageSize={data.page_size} total={data.total} onPage={(p) => set("page", String(p))} what="changes" /></div>}
        </>
      )}
    </div>
  );
}
