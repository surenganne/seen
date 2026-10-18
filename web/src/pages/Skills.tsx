import { Link, useSearchParams } from "react-router-dom";
import { usePolicies, useSkill, useSkills } from "../api/hooks";
import { ChangesTable } from "../components/ChangesTable";
import { SkillActions } from "../components/SkillActions";
import { Badge, Card, ErrorBox, Loading, SkillStatus } from "../components/ui";
import { pct, short, when } from "../lib/format";
import { usePid, useRange, withRange } from "../lib/nav";

export function Skills() {
  const pid = usePid();
  const [sp, setSp] = useSearchParams();
  const tab = sp.get("tab") === "required" ? "required" : "installed";
  const set = (k: string, v?: string) => setSp((p) => { if (v) p.set(k, v); else p.delete(k); return p; }, { replace: true });
  return (
    <main className="page reveal">
      <div className="page-head">
        <div>
          <div className="eyebrow">Inventory and rules</div>
          <h1>Skills</h1>
        </div>
      </div>
      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={tab === "installed"} onClick={() => set("tab")}>Installed skills</button>
        <button role="tab" aria-selected={tab === "required"} onClick={() => set("tab", "required")}>Required skills</button>
      </div>
      {tab === "installed" ? <Installed pid={pid} /> : <Required pid={pid} />}
    </main>
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
      <Card>
        <div style={{ display: "flex", flexWrap: "wrap", gap: ".5rem" }}>
          <input className="input" type="search" aria-label="Search skills" placeholder="Search skills" defaultValue={f.q} onChange={(e) => set("q", e.target.value || undefined)} style={{ flex: "1 1 200px" }} />
          <select className="select" aria-label="Kind" value={f.kind ?? ""} onChange={(e) => set("kind", e.target.value || undefined)}>
            <option value="">Any kind</option>
            {["plugin", "user", "project", "org", "builtin", "sideload"].map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
          <select className="select" aria-label="Status" value={f.status ?? ""} onChange={(e) => set("status", e.target.value || undefined)}>
            <option value="">Any status</option>
            {["approved", "changed", "unreviewed", "blocked"].map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
          <button type="button" className="chip" aria-pressed={!!f.unused} onClick={() => set("unused", f.unused ? undefined : "true")}>Never used</button>
        </div>
      </Card>
      {isLoading && <Loading />}
      {error && <ErrorBox error={error} />}
      {data && (
        <Card>
          <div className="table-wrap">
            <table className="ledger" data-testid="skills-table">
              <thead><tr><th>Skill</th><th>Kind</th><th>Version</th><th>Status</th><th className="num">Runs</th><th>Last used</th></tr></thead>
              <tbody>
                {data.map((s) => (
                  <tr key={s.id} tabIndex={0} onClick={() => set("skill", s.id)} onKeyDown={(e) => e.key === "Enter" && set("skill", s.id)} aria-selected={selected === s.id} data-testid="skill-row">
                    <td><div className="mono">{s.id}</div><div className="muted" style={{ fontSize: ".78rem" }}>{s.description}</div></td>
                    <td><Badge tone="neutral">{s.kind ?? "?"}</Badge></td>
                    <td className="mono">{short(s.hash)}</td>
                    <td><SkillStatus status={s.status} /></td>
                    <td className="num">{s.runs}</td>
                    <td className="mono muted">{when(s.last_used)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
      {selected && <SkillPanel sid={selected} pid={pid} onClose={() => set("skill")} />}
    </>
  );
}

function SkillPanel({ sid, pid, onClose }: { sid: string; pid: string; onClose: () => void }) {
  const { data: s, error, isLoading } = useSkill(sid, pid);
  return (
    <aside className="drawer" aria-label={`Skill ${sid}`} data-testid="skill-panel">
      <div className="card-head" style={{ position: "sticky", top: 0, background: "var(--surface)" }}>
        <h2 className="mono" style={{ fontFamily: "var(--font-mono)", fontSize: "1rem" }}>{sid}</h2>
        <button type="button" className="btn" onClick={onClose} aria-label="Close">✕</button>
      </div>
      <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
        {isLoading && <Loading />}
        {error && <ErrorBox error={error} />}
        {s && (
          <>
            <div style={{ display: "flex", gap: ".4rem", flexWrap: "wrap" }}><SkillStatus status={s.status} /><Badge tone="neutral">{s.kind ?? "?"}</Badge>{s.origin && <span className="mono muted">{s.origin}</span>}</div>
            <p style={{ margin: 0 }}>{s.description}</p>
            <dl className="kv">
              <dt>Current hash</dt><dd className="mono">{short(s.hash, 12)}</dd>
              <dt>Path</dt><dd className="path">{s.path ?? "—"}</dd>
              <dt>Allowed tools</dt><dd className="mono">{s.allowed_tools ?? "any"}</dd>
              <dt>Runs</dt><dd className="mono">{s.runs}</dd>
              <dt>Required by</dt><dd>{s.required_by.length ? s.required_by.join(", ") : "—"}</dd>
            </dl>
            <SkillActions skill={s} pid={pid} />
            <div>
              <div className="eyebrow">Versions</div>
              <ul className="list">
                {s.versions.map((v) => (
                  <li key={v.hash}>
                    <span className="mono">{v.hash_short}</span>
                    <span className="muted mono" style={{ fontSize: ".78rem" }}>{when(v.first_seen)} · {v.runs} runs</span>
                    {v.approved ? <Badge tone="good">approved</Badge> : <Badge tone="neutral">not approved</Badge>}
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <div className="eyebrow">Recent changes</div>
              <ChangesTable rows={s.recent_changes} pid={pid} compact />
            </div>
          </>
        )}
      </div>
    </aside>
  );
}

function Required({ pid }: { pid: string }) {
  const { data, error, isLoading } = usePolicies(pid);
  const [range] = useRange();
  if (isLoading) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  if (!data?.length) return <div className="card empty">No required-skill rules. Add them to <span className="mono">.seen/policies.yaml</span>.</div>;
  return (
    <div className="grid grid-even" data-testid="policies">
      {data.map((p) => (
        <Card key={p.id} title={p.title ?? p.id} aside={<Badge tone={p.mode === "enforce" ? "accent" : "neutral"}>{p.mode}</Badge>}>
          <dl className="kv">
            <dt>Requires</dt><dd className="mono">{p.require_skill}</dd>
            <dt>Paths</dt><dd className="mono">{p.paths.join(", ")}</dd>
          </dl>
          <div style={{ marginTop: ".9rem" }}>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span className="label muted">Compliance</span><span className="mono">{pct(p.compliance)}</span>
            </div>
            <div className="bar" style={{ marginTop: ".3rem" }} role="img" aria-label={`${pct(p.compliance)} compliant`}><span style={{ width: pct(p.compliance) }} /></div>
            <p className="muted" style={{ fontSize: ".8rem", marginBottom: 0 }}>
              {p.met} of {p.applicable} matching changes ran it.{" "}
              {p.missed > 0 && <Link to={withRange(`/p/${pid}/changes`, range, { policy_missed: "true" })}>{p.missed} missed →</Link>}
            </p>
          </div>
        </Card>
      ))}
    </div>
  );
}
