import { ArrowRight, CircleDollarSign, FileCode2, FileStack, GitCommitHorizontal, ShieldAlert, ShieldCheck, Sparkles } from "lucide-react";
import { useNavigate } from "react-router-dom";
import type { S } from "../api/client";
import { useOverview } from "../api/hooks";
import { ActivityChart, MagnitudeBars, Rhythm, SpendChart, Split } from "../components/charts";
import { DenySnippet } from "../components/DenySnippet";
import { Badge, Card, Delta, Empty, ErrorBox, Loading, PageHead, SkillStatus, Spark, Tile } from "../components/ui";
import { int, money, pct, tokens } from "../lib/format";
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

const lines = (t: S["Tiles"]) => t.lines_added + t.lines_removed;
const cacheShare = (t: S["Tiles"]) => {
  const input = t.tok_in + t.tok_cache_read + t.tok_cache_write;
  return input ? t.tok_cache_read / input : null;
};

export function Overview() {
  const pid = usePid();
  const [range] = useRange();
  const nav = useNavigate();
  const { data: o, error, isLoading } = useOverview(pid, range);
  if (isLoading) return <div className="page"><Loading what="Loading overview" /></div>;
  if (error || !o) return <div className="page"><ErrorBox error={error} /></div>;
  const t = o.tiles, p = o.prev;
  const goChanges = (q: Record<string, string>) => nav(withRange(`/p/${pid}/changes`, range, q));
  const rows = (q: Record<string, string> = {}) => withRange(`/p/${pid}/changes`, range, q); // the evidence behind a tile
  const items = attention(o);
  const cache = cacheShare(t);
  const day = o.by_day;
  const rulesMet = t.policy_checks ? t.policy_met / t.policy_checks : null;
  const gitTotal = o.git.committed + o.git.uncommitted + o.git.reverted;
  const skillRuns = Object.values(o.skill_status).reduce((a, n) => a + n, 0);
  return (
    <div className="page">
      <PageHead
        title="Overview"
        description={`Your requests in the last ${range} days, compared with the ${range} days before. Figures are API-equivalent estimates; prices are unverified until confirmed. PII counts cover every session, including plugins' background ones.`}
        actions={<button type="button" className="btn" onClick={() => goChanges({})}>All changes →</button>}
      />

      <div className="strip" role="group" aria-label="Summary">
        <Tile label="Requests" icon={FileStack} to={rows()} value={int(t.changes)} sub={`${int(t.changed)} changed files`}
          delta={<Delta now={t.changes} prev={p.changes} days={range} />} spark={<Spark values={day.map((d) => d.requests)} />} />
        <Tile label="Code changed" icon={FileCode2} to={withRange(`/p/${pid}/timeline`, range)} value={<>{int(t.files_changed)} <span className="unit">files</span></>}
          sub={<><span className="plus">+{int(t.lines_added)}</span> <span className="minus">−{int(t.lines_removed)}</span> · {t.commits} {t.commits === 1 ? "commit" : "commits"}</>}
          delta={<Delta now={lines(t)} prev={lines(p)} days={range} />} spark={<Spark values={day.map((d) => d.added + d.removed)} />} />
        <Tile label="Cost" icon={CircleDollarSign} to={rows({ view: "list", sort: "cost", dir: "desc" })} value={money(t.cost_usd)} sub={t.background_changes
          ? <span data-testid="background-spend">API-equivalent · plus {money(t.background_cost_usd)} in {int(t.background_changes)} background {t.background_changes === 1 ? "turn" : "turns"}</span>
          : "API-equivalent"}
          delta={<Delta now={t.cost_usd} prev={p.cost_usd} days={range} />} spark={<Spark values={day.map((d) => d.cost_usd)} />} />
        <Tile label="Rules met" icon={Sparkles} to={rows({ policy_missed: "true" })} value={rulesMet === null ? "—" : pct(rulesMet)}
          sub={t.policy_checks ? `${t.policy_met} of ${t.policy_checks} required-skill checks` : "no required-skill rule applied"} alert={t.policy_missed > 0} />
        <Tile label="PII exposure" icon={ShieldAlert} to={rows({ pii: "true" })} value={int(t.pii_changes)}
          sub={t.pii_high ? `${t.pii_high} high-confidence` : "changes with structured identifiers"} alert={t.pii_high > 0}
          delta={<Delta now={t.pii_changes} prev={p.pii_changes} days={range} />} spark={<Spark values={day.map((d) => d.pii_changes)} />} />
      </div>

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
                <div className="muted small">Checked: required-skill rules and structured PII. Names and free text are not detected.</div>
              </div>
              <span />
            </li>
          </ul>
        )}
      </Card>

      <div className="grid two top">
        <Card title="Activity" aside={<span className="hint">requests per day</span>}>
          <ActivityChart days={day} />
        </Card>
        <Card title="Spend" aside={<span className="hint">API-equivalent, by model</span>}>
          <SpendChart days={day} />
          <p className="muted small" style={{ marginTop: 8 }} data-testid="token-line">
            {tokens(t.tok_out)} output tokens{cache !== null && <> · {pct(cache)} of input served from cache</>} · {tokens(t.tokens)} tokens in all
          </p>
        </Card>
      </div>

      <div className="grid cols3 top">
        <Card title="Where the work happened" aside={<span className="hint">requests touching each folder</span>}>
          {o.areas.length === 0 ? <Empty icon={FileCode2} title="No files changed" /> : (
            <MagnitudeBars items={o.areas.map((a) => ({ label: a.area, value: a.changes, sub: `+${int(a.added)} −${int(a.removed)}`,
              to: a.area === "(root)" ? undefined : rows({ q: a.area }) }))} />
          )}
        </Card>
        <Card title="What happened to it" aside={<span className="hint">requests that changed files</span>}>
          {gitTotal === 0 ? <Empty icon={GitCommitHorizontal} title="No file changes" /> : (
            <Split parts={[
              { label: "Committed", value: o.git.committed, color: "var(--series-1)", note: `${t.commits} ${t.commits === 1 ? "commit" : "commits"}` },
              { label: "Not committed", value: o.git.uncommitted, color: "var(--border-strong)" },
              { label: "Reverted", value: o.git.reverted, color: "var(--series-2)" },
            ]} />
          )}
        </Card>
        <Card title="When the work happens" aside={<span className="hint">weekday and hour, IST</span>}>
          <Rhythm cells={o.rhythm} />
        </Card>
      </div>

      <div className="grid cols3 top">
        <Card title="Required-skill rules" aside={<span className="hint">checks met in this period</span>}>
          {o.policies.length === 0 ? <Empty icon={Sparkles} title="No rule applied">A rule in <code>.seen/policies.yaml</code> says which skill a change to certain files must run.</Empty> : (
            <ul className="rules" data-testid="rule-list">
              {o.policies.map((r) => (
                <li key={r.policy_id}>
                  <div className="rule-head">
                    <span>{r.title ?? r.policy_id.split(":").pop()}</span>
                    {r.met === r.checks ? <Badge tone="good">all met</Badge> : <Badge tone="warning">{r.checks - r.met} missed</Badge>}
                  </div>
                  <div className="rule-bar">
                    <span className="meter" aria-hidden="true"><span style={{ width: `${(100 * r.met) / r.checks}%` }} /></span>
                    <span className="mono tiny muted">{r.met} of {r.checks}</span>
                  </div>
                  <div className="tiny muted">requires <span className="mono">{r.require_skill ?? "a skill"}</span>{r.mode ? ` · ${r.mode}` : ""}</div>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Skills" aside={<span className="hint">{skillRuns} {skillRuns === 1 ? "run" : "runs"}</span>}>
          {o.top_skills.length === 0 ? <Empty title="No skills ran" /> : (
            <>
              <ul className="rows flush-in" data-testid="top-skills">
                {o.top_skills.slice(0, 6).map((s) => (
                  <li key={s.skill_id}>
                    <button type="button" className="link mono" onClick={() => goChanges({ skill: s.skill_id })}>{s.skill_id}</button>
                    <span className="mono tiny muted">{s.runs} {s.runs === 1 ? "run" : "runs"}</span>
                  </li>
                ))}
              </ul>
              <h3 className="subhead">By approval status</h3>
              <ul className="rows flush-in" data-testid="skill-status">
                {["approved", "unreviewed", "changed", "blocked"].filter((k) => o.skill_status[k]).map((k) => (
                  <li key={k}><SkillStatus status={k} /><span className="mono tiny muted">{o.skill_status[k]} {o.skill_status[k] === 1 ? "run" : "runs"}</span></li>
                ))}
              </ul>
            </>
          )}
        </Card>
        <Card title="PII exposure by type" aside={<span className="hint">open findings, counts only</span>}>
          {o.pii_by_type.length === 0 ? (
            <p className="muted small">No structured identifiers found in prompts, file reads, tool output or diffs. Names and free text are not detected.</p>
          ) : (
            <>
              <MagnitudeBars items={o.pii_by_type.slice(0, 6).map((x) => ({ label: x.type, value: x.count, sub: `${x.changes} ${x.changes === 1 ? "change" : "changes"}` }))} />
              {o.pii_by_type.length > 6 && <p className="muted tiny" style={{ marginTop: 8 }}>and {o.pii_by_type.length - 6} more types, {int(o.pii_by_type.slice(6).reduce((a, x) => a + x.count, 0))} findings, in Top PII sources below</p>}
            </>
          )}
        </Card>
      </div>

      {o.pii_top_sources.length > 0 && (
        <Card title="Top PII sources" flush aside={<span className="hint">what keeps putting PII into context</span>}>
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
          <p className="muted tiny" style={{ padding: "0.6rem 1rem" }}>Seen shows exposure; it cannot recall what already reached the model provider.</p>
        </Card>
      )}
    </div>
  );
}
