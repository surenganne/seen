import { Bot, Check, Search, Sparkles, X } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { usePolicies, useSkill, useSkills } from "../api/hooks";
import { ChangesTable } from "../components/ChangesTable";
import { SkillActions } from "../components/SkillActions";
import { Badge, Card, Empty, ErrorBox, Loading, PageHead, RowButton, SkillStatus } from "../components/ui";
import { pct, short, when } from "../lib/format";
import { usePid, useRange, withRange } from "../lib/nav";

export function Skills() {
  const pid = usePid();
  const [sp, setSp] = useSearchParams();
  const tab = sp.get("tab") === "required" ? "required" : "installed";
  const set = (k: string, v?: string) => setSp((p) => { if (v) p.set(k, v); else p.delete(k); return p; }, { replace: true });
  return (
    <div className="page">
      <PageHead title="Skills" description="Every installed skill, most recently used first, with its version hash and approval, and the rules that require them." />
      <div className="tabs" role="tablist" aria-label="Skills views">
        <button role="tab" aria-selected={tab === "installed"} onClick={() => set("tab")}>Installed skills</button>
        <button role="tab" aria-selected={tab === "required"} onClick={() => set("tab", "required")}>Required skills</button>
      </div>
      {tab === "installed" ? <Installed pid={pid} /> : <Required pid={pid} />}
    </div>
  );
}

function Installed({ pid }: { pid: string }) {
  const [sp, setSp] = useSearchParams();
  const set = (k: string, v?: string) => setSp((p) => { if (v) p.set(k, v); else p.delete(k); return p; }, { replace: true });
  const f = { kind: sp.get("kind") || undefined, status: sp.get("status") || undefined, q: sp.get("q") || undefined, unused: sp.get("unused") === "true" || undefined };
  const { data, error, isLoading } = useSkills(pid, f);
  const selected = sp.get("skill") || undefined;
  return (
    <>
      <div className="toolbar" role="search">
        <label className="search">
          <Search aria-hidden="true" />
          <input className="input" type="search" aria-label="Search skills" placeholder="Search skills" defaultValue={f.q} onChange={(e) => set("q", e.target.value || undefined)} />
        </label>
        <select className="select" aria-label="Kind" value={f.kind ?? ""} onChange={(e) => set("kind", e.target.value || undefined)}>
          <option value="">Any kind</option>
          {["plugin", "user", "project", "org", "builtin", "sideload"].map((k) => <option key={k} value={k}>{k}</option>)}
        </select>
        <select className="select" aria-label="Status" value={f.status ?? ""} onChange={(e) => set("status", e.target.value || undefined)}>
          <option value="">Any status</option>
          {["approved", "changed", "unreviewed", "blocked"].map((k) => <option key={k} value={k}>{k}</option>)}
        </select>
        <button type="button" className="chip" aria-pressed={!!f.unused} onClick={() => set("unused", f.unused ? undefined : "true")}>{f.unused && <Check aria-hidden="true" />}Never used</button>
      </div>
      {isLoading && <Loading what="Loading skills" />}
      {error && <ErrorBox error={error} />}
      {data && (
        <section className="panel">
          {data.length === 0 ? <Empty icon={Bot} title="No skills match">Clear a filter, or run <code>seen skills scan</code> to refresh the inventory.</Empty> : (
            <div className="table-wrap" tabIndex={0} role="region" aria-label="Skills">
              <table className="data" data-testid="skills-table">
                <thead><tr><th>Skill</th><th>Kind</th><th>Version</th><th>Status</th><th className="num">Runs</th><th>Last used</th></tr></thead>
                <tbody>
                  {data.map((s) => (
                    <tr key={s.id} className="clickable" onClick={() => set("skill", s.id)}
                      aria-selected={selected === s.id} data-testid="skill-row">
                      <td><div className="title mono"><RowButton onClick={() => set("skill", s.id)}>{s.id}</RowButton></div><div className="meta">{s.description}</div></td>
                      <td><span className="tag">{s.kind ?? "?"}</span></td>
                      <td className="mono">{short(s.hash)}</td>
                      <td><SkillStatus status={s.status} /></td>
                      <td className="num">{s.runs}</td>
                      <td className="when">{when(s.last_used)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
      {selected && <SkillPanel sid={selected} pid={pid} onClose={() => set("skill")} />}
    </>
  );
}

function SkillPanel({ sid, pid, onClose }: { sid: string; pid: string; onClose: () => void }) {
  const { data: s, error, isLoading } = useSkill(sid, pid);
  return (
    <aside className="drawer" aria-label={`Skill ${sid}`} data-testid="skill-panel">
      <div className="drawer-head">
        <h2 className="mono" style={{ fontWeight: 500 }}>{sid}</h2>
        <button type="button" className="btn ghost icon-btn" onClick={onClose} aria-label="Close"><X aria-hidden="true" /></button>
      </div>
      <div className="drawer-body">
        {isLoading && <Loading what="Loading skill" rows={3} />}
        {error && <ErrorBox error={error} />}
        {s && (
          <>
            <div className="checks"><SkillStatus status={s.status} /><span className="tag">{s.kind ?? "?"}</span>{s.origin && <span className="mono tiny muted">{s.origin}</span>}</div>
            {s.description && <p className="prose">{s.description}</p>}
            <dl className="kv">
              <dt>Current hash</dt><dd className="mono">{short(s.hash, 12)}</dd>
              <dt>Path</dt><dd className="path">{s.path ?? "—"}</dd>
              <dt>Allowed tools</dt><dd className="mono">{s.allowed_tools ?? "any"}</dd>
              <dt>Runs</dt><dd className="mono">{s.runs}</dd>
              <dt>Required by</dt><dd>{s.required_by.length ? s.required_by.join(", ") : "—"}</dd>
            </dl>
            <SkillActions skill={s} pid={pid} />
            <section>
              <h3 style={{ marginBottom: 6 }}>Versions</h3>
              <div className="panel">
                <ul className="rows">
                  {s.versions.map((v) => (
                    <li key={v.hash}>
                      <span className="mono">{v.hash_short}</span>
                      <span className="mono tiny muted">{when(v.first_seen)} · {v.runs} runs</span>
                      {v.approved ? <Badge tone="good">approved</Badge> : <Badge tone="neutral">not approved</Badge>}
                    </li>
                  ))}
                </ul>
              </div>
            </section>
            <section>
              <h3 style={{ marginBottom: 6 }}>Recent changes</h3>
              <div className="panel"><ChangesTable rows={s.recent_changes} pid={pid} compact /></div>
            </section>
          </>
        )}
      </div>
    </aside>
  );
}

function Required({ pid }: { pid: string }) {
  const { data, error, isLoading } = usePolicies(pid);
  const [range] = useRange();
  if (isLoading) return <Loading what="Loading rules" rows={2} />;
  if (error) return <ErrorBox error={error} />;
  if (!data?.length) {
    return <div className="panel"><Empty icon={Sparkles} title="No required-skill rules">Add rules to <code>.seen/policies.yaml</code> in the repo, for example: changes to <code>src/auth/**</code> must run <code>security-review</code>.</Empty></div>;
  }
  return (
    <div className="grid cols" data-testid="policies">
      {data.map((p) => (
        <Card key={p.id} title={p.title ?? p.id} aside={<Badge tone={p.mode === "enforce" ? "accent" : "neutral"}>{p.mode}</Badge>}>
          <dl className="kv">
            <dt>Requires</dt><dd className="mono">{p.require_skill}</dd>
            <dt>Paths</dt><dd className="mono">{p.paths.join(", ")}</dd>
          </dl>
          <div style={{ marginTop: "1rem" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
              <span className="label">Compliance</span><span className="mono" style={{ fontWeight: 600 }}>{pct(p.compliance)}</span>
            </div>
            <div className="meter" style={{ marginTop: 6 }} role="img" aria-label={`${pct(p.compliance)} compliant`}><span style={{ width: pct(p.compliance) }} /></div>
            <p className="muted small" style={{ marginTop: 8 }}>
              {p.met} of {p.applicable} matching changes ran it.{" "}
              {p.missed > 0 && <Link to={withRange(`/p/${pid}/changes`, range, { policy_missed: "true" })}>{p.missed} missed →</Link>}
            </p>
          </div>
        </Card>
      ))}
    </div>
  );
}
