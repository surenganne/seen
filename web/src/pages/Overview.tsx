import { useNavigate } from "react-router-dom";
import { useOverview } from "../api/hooks";
import { CostChart, MagnitudeBars } from "../components/charts";
import { ChangesTable } from "../components/ChangesTable";
import { DenySnippet } from "../components/DenySnippet";
import { Card, ErrorBox, Loading, Tile } from "../components/ui";
import { int, money, pct, tokens } from "../lib/format";
import { usePid, useRange, withRange } from "../lib/nav";

export function Overview() {
  const pid = usePid();
  const [range] = useRange();
  const nav = useNavigate();
  const { data: o, error, isLoading } = useOverview(pid, range);
  if (isLoading) return <main className="page"><Loading /></main>;
  if (error || !o) return <main className="page"><ErrorBox error={error} /></main>;
  const t = o.tiles;
  const goChanges = (q: Record<string, string>) => nav(withRange(`/p/${pid}/changes`, range, q));
  return (
    <main className="page reveal">
      <div className="page-head">
        <div>
          <div className="eyebrow">Last {range} days</div>
          <h1>Overview</h1>
        </div>
        {o.alert.on && (
          <div className="banner critical" role="status" data-testid="alert-banner">
            <strong>Needs attention:</strong> {o.alert.reasons.join(" · ")}
          </div>
        )}
      </div>
      <div className="grid grid-tiles">
        <Tile label="Changes" value={int(t.changes)} sub={`${int(t.files_changed)} files · +${int(t.lines_added)} −${int(t.lines_removed)}`} />
        <Tile label="Cost" value={money(t.cost_usd)} sub="API-equivalent, prices unverified" />
        <Tile label="Tokens" value={tokens(t.tokens)} sub="in + out + cache" />
        <Tile label="Memory loaded" value={pct(t.mem_loaded_pct)} sub="of turns with memory" alert={(t.mem_loaded_pct ?? 1) < 0.95} />
        <Tile label="Policy missed" value={int(t.policy_missed)} sub="required skill not run" alert={t.policy_missed > 0} />
        <Tile label="Changes with PII exposure" value={int(t.pii_changes)} sub={t.pii_high ? `${t.pii_high} high-confidence` : "structured identifiers only"} alert={t.pii_high > 0} />
      </div>
      <div className="grid grid-2">
        <Card title="Cost per day" aside={<span className="eyebrow">by tool</span>}>
          <CostChart days={o.cost_by_day} />
        </Card>
        <Card title="By model">
          <div className="table-wrap">
            <table className="ledger">
              <thead><tr><th>Model</th><th className="num">Changes</th><th className="num">Out</th><th className="num">Cost</th></tr></thead>
              <tbody>
                {o.by_model.map((m) => (
                  <tr key={m.model} style={{ cursor: "default" }}>
                    <td className="mono">{m.model}</td><td className="num">{m.changes}</td><td className="num">{tokens(m.tok_out)}</td><td className="num">{money(m.cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
      <Card title="Recent changes" aside={<button type="button" className="btn" onClick={() => goChanges({})}>All changes →</button>}>
        <ChangesTable rows={o.recent_changes} pid={pid} compact />
      </Card>
      <div className="grid grid-even">
        <Card title="Most edited files">
          <ul className="list" data-testid="top-files">
            {o.top_files.map((f) => (
              <li key={f.path}>
                <button type="button" className="linkish path" onClick={() => goChanges({ file: f.path })}>{f.path}</button>
                <span className="mono muted">{f.changes}× <span className="plus">+{f.added}</span> <span className="minus">−{f.removed}</span></span>
              </li>
            ))}
          </ul>
        </Card>
        <Card title="Top skills">
          <ul className="list" data-testid="top-skills">
            {o.top_skills.length === 0 && <li className="muted">No skills ran.</li>}
            {o.top_skills.map((s) => (
              <li key={s.skill_id}>
                <button type="button" className="linkish mono" onClick={() => goChanges({ skill: s.skill_id })}>{s.skill_id}</button>
                <span className="mono muted">{s.runs} runs</span>
              </li>
            ))}
          </ul>
        </Card>
      </div>
      <div className="grid grid-even">
        <Card title="PII exposure by type" aside={<span className="eyebrow">open findings</span>}>
          {o.pii_by_type.length === 0 ? (
            <p className="muted" style={{ margin: 0 }}>No structured identifiers found in prompts, file reads, tool output or diffs. Names and free text are not detected.</p>
          ) : (
            <MagnitudeBars items={o.pii_by_type.map((p) => ({ label: p.type, value: p.count, sub: `${p.changes} changes` }))} />
          )}
        </Card>
        <Card title="Top PII sources" aside={<span className="eyebrow">what keeps putting PII into context</span>}>
          {o.pii_top_sources.length === 0 ? (
            <p className="muted" style={{ margin: 0 }}>No repeat sources.</p>
          ) : (
            <ul className="list" data-testid="pii-sources">
              {o.pii_top_sources.map((s) => (
                <li key={s.source_kind + s.source_ref} style={{ flexDirection: "column", alignItems: "stretch" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: ".5rem" }}>
                    <span className="path">{s.source_ref}</span>
                    <span className="mono muted">{s.changes} {s.changes === 1 ? "change" : "changes"} · {s.types.join(", ")}</span>
                  </div>
                  {s.deny_rule && <DenySnippet rule={s.deny_rule} />}
                </li>
              ))}
            </ul>
          )}
          <p className="muted" style={{ fontSize: ".78rem", marginBottom: 0 }}>Seen shows exposure; it cannot un-send what already reached the model provider.</p>
        </Card>
      </div>
    </main>
  );
}
