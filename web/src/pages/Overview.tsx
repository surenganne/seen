import { ArrowRight, CircleDollarSign, Coins, FileStack, ShieldAlert, ShieldCheck, Sparkles } from "lucide-react";
import { useNavigate } from "react-router-dom";
import type { S } from "../api/client";
import { useOverview } from "../api/hooks";
import { CostChart, MagnitudeBars } from "../components/charts";
import { ChangesTable } from "../components/ChangesTable";
import { DenySnippet } from "../components/DenySnippet";
import { Card, Empty, ErrorBox, Loading, PageHead, Tile } from "../components/ui";
import { int, money, tokens } from "../lib/format";
import { usePid, useRange, withRange } from "../lib/nav";

type Item = { tone: "crit" | "warn"; title: string; detail: string; to: Record<string, string> };

function attention(o: S["Overview"]): Item[] {
  const t = o.tiles;
  const items: Item[] = [];
  if (t.pii_high) items.push({ tone: "crit", title: `${t.pii_high} ${t.pii_high === 1 ? "change" : "changes"} exposed high-confidence PII`,
    detail: "Aadhaar, card, IBAN or secrets reached the model or the repo.", to: { pii: "true" } });
  if (t.policy_missed) items.push({ tone: "warn", title: `${t.policy_missed} required-skill ${t.policy_missed === 1 ? "check" : "checks"} missed`,
    detail: "Files under a policy changed without the skill it requires.", to: { policy_missed: "true" } });
  if (t.pii_changes > t.pii_high) items.push({ tone: "warn", title: `${t.pii_changes - t.pii_high} more ${t.pii_changes - t.pii_high === 1 ? "change" : "changes"} with medium-confidence PII`,
    detail: "Emails, phone numbers or PAN. Review or mark as test data.", to: { pii: "true" } });
  return items;
}

export function Overview() {
  const pid = usePid();
  const [range] = useRange();
  const nav = useNavigate();
  const { data: o, error, isLoading } = useOverview(pid, range);
  if (isLoading) return <div className="page"><Loading what="Loading overview" /></div>;
  if (error || !o) return <div className="page"><ErrorBox error={error} /></div>;
  const t = o.tiles;
  const goChanges = (q: Record<string, string>) => nav(withRange(`/p/${pid}/changes`, range, q));
  const rows = (q: Record<string, string> = {}) => withRange(`/p/${pid}/changes`, range, q); // the evidence behind a tile
  const items = attention(o);
  return (
    <div className="page">
      <PageHead
        title="Overview"
        description={`Your requests in the last ${range} days. Figures are API-equivalent estimates; prices are unverified until confirmed. PII counts cover every session, including plugins' background ones.`}
        actions={<button type="button" className="btn" onClick={() => goChanges({})}>All changes →</button>}
      />
      <div className="strip" role="group" aria-label="Summary">
        <Tile label="Changes" icon={FileStack} to={rows()} value={int(t.changes)} sub={`${int(t.files_changed)} files · +${int(t.lines_added)} −${int(t.lines_removed)}`} />
        <Tile label="Cost" icon={CircleDollarSign} to={rows({ view: "list", sort: "cost", dir: "desc" })} value={money(t.cost_usd)} sub={t.background_changes
          ? <span data-testid="background-spend">API-equivalent · plus {money(t.background_cost_usd)} in {int(t.background_changes)} background {t.background_changes === 1 ? "turn" : "turns"}</span>
          : "API-equivalent"} />
        <Tile label="Tokens" icon={Coins} to={rows({ view: "list", sort: "tokens", dir: "desc" })} value={tokens(t.tokens)} sub="in, out and cache" />
        <Tile label="Policy missed" icon={Sparkles} to={rows({ policy_missed: "true" })} value={int(t.policy_missed)} sub="required skill not run" alert={t.policy_missed > 0} />
        <Tile label="Changes with PII exposure" icon={ShieldAlert} to={rows({ pii: "true" })} value={int(t.pii_changes)}
          sub={t.pii_high ? `${t.pii_high} high-confidence` : "structured identifiers"} alert={t.pii_high > 0} />
      </div>

      <div className="grid split">
        <Card title="Cost per day" aside={<span className="hint">stacked by tool</span>}>
          <CostChart days={o.cost_by_day} />
        </Card>
        <Card title="Needs attention" flush aside={<span className="hint">{items.length ? `${items.length} open` : "nothing open"}</span>}>
          {items.length ? (
            <ul className="attention" data-testid="alert-banner">
              {items.map((it) => (
                <li key={it.title} className={it.tone}>
                  <ShieldAlert aria-hidden="true" />
                  <div>
                    <div style={{ fontWeight: 500 }}>{it.title}</div>
                    <div className="muted small">{it.detail}</div>
                  </div>
                  <button type="button" className="btn ghost sm" onClick={() => goChanges(it.to)} aria-label={`Review: ${it.title}`}>
                    Review <ArrowRight aria-hidden="true" />
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <ul className="attention">
              <li className="ok">
                <ShieldCheck aria-hidden="true" />
                <div>
                  <div style={{ fontWeight: 500 }}>Nothing needs a human right now</div>
                  <div className="muted small">Checked: policies and structured PII. Names and free text are not detected.</div>
                </div>
                <span />
              </li>
            </ul>
          )}
        </Card>
      </div>

      <Card title="Recent changes" flush>
        <ChangesTable rows={o.recent_changes} pid={pid} compact />
      </Card>

      <div className="grid cols3">
        <Card title="Most edited files" flush>
          {o.top_files.length === 0 ? <Empty title="No files changed" /> : (
            <ul className="rows" data-testid="top-files">
              {o.top_files.map((f) => (
                <li key={f.path}>
                  <button type="button" className="link path" onClick={() => goChanges({ file: f.path })}>{f.path}</button>
                  <span className="mono tiny muted" style={{ whiteSpace: "nowrap" }}>{f.changes}× <span className="plus">+{f.added}</span> <span className="minus">−{f.removed}</span></span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Top skills" flush>
          {o.top_skills.length === 0 ? <Empty title="No skills ran" /> : (
            <ul className="rows" data-testid="top-skills">
              {o.top_skills.map((s) => (
                <li key={s.skill_id}>
                  <button type="button" className="link mono" onClick={() => goChanges({ skill: s.skill_id })}>{s.skill_id}</button>
                  <span className="mono tiny muted">{s.runs} {s.runs === 1 ? "run" : "runs"}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="By model" flush>
          <div className="table-wrap" tabIndex={0} role="region" aria-label="Cost by model">
            <table className="data">
              <thead><tr><th>Model</th><th className="num">Changes</th><th className="num">Output</th><th className="num">Cost</th></tr></thead>
              <tbody>
                {o.by_model.map((m) => (
                  <tr key={m.model}>
                    <td className="mono" style={{ whiteSpace: "nowrap" }}>{m.model === "unknown" ? <span className="muted" title="Turns with no model reply, for example interrupted ones">no reply</span> : m.model}</td><td className="num">{m.changes}</td>
                    <td className="num">{tokens(m.tok_out)}</td><td className="num">{money(m.cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>

      <div className="grid cols">
        <Card title="PII exposure by type" aside={<span className="hint">open findings, counts only</span>}>
          {o.pii_by_type.length === 0 ? (
            <p className="muted small">No structured identifiers found in prompts, file reads, tool output or diffs. Names and free text are not detected.</p>
          ) : (
            <MagnitudeBars items={o.pii_by_type.map((p) => ({ label: p.type, value: p.count, sub: `${p.changes} ${p.changes === 1 ? "change" : "changes"}` }))} />
          )}
        </Card>
        <Card title="Top PII sources" flush aside={<span className="hint">what keeps putting PII into context</span>}>
          {o.pii_top_sources.length === 0 ? <Empty title="No repeat sources" /> : (
            <ul className="rows" data-testid="pii-sources">
              {o.pii_top_sources.map((s) => (
                <li key={s.source_kind + s.source_ref} style={{ flexDirection: "column", alignItems: "stretch", gap: "0.35rem" }}>
                  <div className="source-row">
                    <span className="path">{s.source_ref}</span>
                    <span className="meta mono tiny muted">{s.changes} {s.changes === 1 ? "change" : "changes"} · {s.types.join(", ")}</span>
                  </div>
                  {s.deny_rule && <DenySnippet rule={s.deny_rule} />}
                </li>
              ))}
            </ul>
          )}
          <p className="muted tiny" style={{ padding: "0.6rem 1rem" }}>Seen shows exposure; it cannot recall what already reached the model provider.</p>
        </Card>
      </div>
    </div>
  );
}
