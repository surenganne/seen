import { ArrowLeft, Brain, Bot, FileCode2, History, Lock, ShieldAlert, Sparkles } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useChange } from "../api/hooks";
import { MarkTestData } from "../components/PiiActions";
import { Badge, Card, Empty, ErrorBox, GitStatus, Loading, MemState, Note, SkillStatus } from "../components/ui";
import { int, money, pct, short, tokens, when } from "../lib/format";
import { usePid, useRange, withRange } from "../lib/nav";

const SOURCE: Record<string, string> = { prompt: "Prompt", file_read: "File read", tool_output: "Tool output", mcp: "MCP tool", injected_memory: "Injected memory", diff_added: "Added lines" };
const DEST: Record<string, string> = { model: "Model", network: "Network", repo: "Repo", memory: "Memory" };
const KIND: Record<string, string> = { input: "Input", output: "Output", cache_read: "Cache read", cache_write: "Cache write" };

export function ChangeDetail() {
  const pid = usePid();
  const { cid = "" } = useParams();
  const [range] = useRange();
  const nav = useNavigate();
  const { data: c, error, isLoading } = useChange(cid);
  if (isLoading) return <main className="page"><Loading what="Loading change" /></main>;
  if (error || !c) return <main className="page"><ErrorBox error={error} /></main>;
  const high = c.pii.some((p) => p.status === "open" && p.confidence === "high");
  return (
    <main className="page" data-testid="change-detail">
      <div>
        <button type="button" className="btn ghost sm" onClick={() => nav(-1)} data-testid="back"><ArrowLeft aria-hidden="true" />Back</button>
      </div>
      <div className="page-head">
        <div style={{ minWidth: 0 }}>
          <h1 className="clamp-2">{c.prompt_text ? c.prompt_text.split(/\s+/).join(" ").slice(0, 240) : c.summary ?? "(no summary)"}</h1>
          {c.prompt_text && c.summary && <p className="small">{c.summary}</p>}
          <p className="mono small">Change #{c.seq} · {when(c.started_at)} · {c.tool} · {c.model ?? "unknown model"}{c.duration_s != null ? ` · ${c.duration_s}s` : ""}</p>
        </div>
        <div className="checks">
          <GitStatus status={c.git_status} />
          <MemState state={c.mem_state} />
          {c.policies.some((p) => !p.met) && <Badge tone="warning">policy missed</Badge>}
          {c.skills.some((s) => s.status && s.status !== "approved") && <Badge tone="warning">unapproved skill</Badge>}
        </div>
      </div>

      {c.source === "imported" && (
        <Note tone="info" icon={History} testId="imported-note">
          Imported from the Claude Code transcript with <span className="mono">seen import</span>. Tokens, cost, tools, skills and prompt PII are exact;
          line counts come from the edit inputs, and git status and memory state were not observed.
        </Note>
      )}

      {high && (
        <div data-testid="pii-banner">
          <Note tone="critical" icon={ShieldAlert}>
            <strong>High-confidence personal data or secrets reached the model in this change.</strong> Seen records exposure; it cannot recall what was sent.
          </Note>
        </div>
      )}

      <div className="grid split">
        <Card title="Files" flush aside={<span className="hint">{c.files.length} {c.files.length === 1 ? "file" : "files"}</span>}>
          {c.files.length === 0 ? <Empty icon={FileCode2} title="No file changes in this turn" /> : (
            <ul className="rows" data-testid="change-files">
              {c.files.map((f) => (
                <li key={f.path}>
                  <Link className="path" to={withRange(`/p/${pid}/changes`, range, { file: f.path })}>{f.path}</Link>
                  <span className="mono small" style={{ whiteSpace: "nowrap" }}><span className="plus">+{f.added}</span> <span className="minus">−{f.removed}</span></span>
                </li>
              ))}
            </ul>
          )}
          <dl className="kv" style={{ padding: "0.8rem 1rem", borderTop: "1px solid var(--border)" }}>
            <dt>HEAD before</dt><dd className="mono">{short(c.git_head_before, 12)}</dd>
            <dt>HEAD after</dt><dd className="mono">{short(c.git_head_after, 12)}</dd>
          </dl>
        </Card>
        <Card title="Tokens and cost" flush aside={<span className="mono small">{money(c.cost_usd)}</span>}>
          <div className="table-wrap">
            <table className="data">
              <thead><tr><th>Kind</th><th className="num">Tokens</th><th className="num">Cost</th><th style={{ width: "36%" }}>Share of cost</th></tr></thead>
              <tbody>
                {c.cost_breakdown.map((p) => (
                  <tr key={p.kind}>
                    <td>{KIND[p.kind] ?? p.kind}</td>
                    <td className="num">{int(p.tokens)}</td>
                    <td className="num">{money(p.cost_usd)}</td>
                    <td>
                      <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                        <span className="meter" style={{ flex: 1 }} aria-hidden="true"><span style={{ width: pct(p.share) }} /></span>
                        <span className="mono tiny muted" style={{ minWidth: "3ch", textAlign: "right" }}>{pct(p.share)}</span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted tiny" style={{ padding: "0.6rem 1rem" }}>
            Price table <span className="mono">{c.price_version}</span>{c.prices_verified ? "" : " (unverified)"} · {tokens(c.tokens.out)} output tokens
          </p>
        </Card>
      </div>

      <Card title="Prompt" aside={<span className="hint">storage: {c.prompt_storage}</span>}>
        {c.prompt_text ? <pre className="snippet" style={{ whiteSpace: "pre-wrap" }}>{c.prompt_text}</pre> : (
          <p className="muted small prose">
            <Lock size={13} aria-hidden="true" style={{ verticalAlign: "-2px", marginRight: 4 }} />
            Not stored (prompt storage is <span className="mono">{c.prompt_storage}</span>). Claude Code's own transcript under ~/.claude still holds the raw text.
          </p>
        )}
      </Card>

      <div className="grid cols3">
        <Card title="Memory read" flush aside={<span className="hint">{c.mem_injected_tokens} tokens</span>}>
          {c.memories.length === 0 ? <Empty icon={Brain} title="No memory injected" /> : (
            <ul className="rows">{c.memories.map((m) => <li key={m.memory_id}><span className="mono">{m.memory_id}</span><span className="muted tiny">{m.type ?? ""}</span></li>)}</ul>
          )}
          {c.memory_saved.length > 0 && (
            <div style={{ padding: "0.6rem 1rem", borderTop: "1px solid var(--border)" }}>
              <div className="label" style={{ marginBottom: 4 }}>Memory saved from this change</div>
              {c.memory_saved.map((m) => <Link key={m} className="mono small" to={withRange(`/p/${pid}/memory`, range)} style={{ marginRight: 8 }}>{m}</Link>)}
            </div>
          )}
        </Card>
        <Card title="Skills used" flush>
          {c.skills.length === 0 ? <Empty icon={Bot} title="No skills ran" /> : (
            <ul className="rows" data-testid="change-skills">
              {c.skills.map((s) => (
                <li key={s.ordinal}>
                  <span style={{ minWidth: 0 }}>
                    <span className="mono muted tiny">{s.ordinal}. </span>
                    <Link className="mono" to={withRange(`/p/${pid}/skills`, range, { skill: s.skill_id })}>{s.skill_id}</Link>
                    <span className="mono muted tiny"> @{s.hash_short ?? "?"}</span>
                  </span>
                  <span className="checks"><span className="tag">{s.trigger ?? "?"}</span><SkillStatus status={s.status} /></span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Required-skill checks" flush>
          {c.policies.length === 0 ? <Empty icon={Sparkles} title="No policy covers these files" /> : (
            <ul className="rows">
              {c.policies.map((p) => (
                <li key={p.policy_id}>
                  <span style={{ minWidth: 0 }}>{p.title} <span className="mono muted tiny">needs {p.require_skill}</span></span>
                  {p.met ? <Badge tone="good">met</Badge> : <Badge tone="warning">missed</Badge>}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card title="PII exposure" flush aside={<span className="hint">types and counts only, never values</span>}>
        {c.pii.length === 0 ? (
          <p className="muted small prose" style={{ padding: "1rem" }} data-testid="pii-none">No structured identifiers found. Checked: {c.pii_checked}</p>
        ) : (
          <div data-testid="pii-panel">
            <div className="table-wrap">
              <table className="data">
                <thead><tr><th>Type</th><th className="num">Count</th><th>Confidence</th><th>Source</th><th>Destination</th><th>Status</th></tr></thead>
                <tbody>
                  {c.pii.map((p) => (
                    <tr key={p.id}>
                      <td className="mono">{p.type}</td>
                      <td className="num">{p.count} <span className="muted tiny">({p.distinct_count} distinct)</span></td>
                      <td><Badge tone={p.confidence === "high" ? "critical" : p.confidence === "medium" ? "warning" : "neutral"}>{p.confidence}</Badge></td>
                      <td>{SOURCE[p.source_kind ?? ""] ?? p.source_kind}{p.source_ref && p.source_ref !== SOURCE[p.source_kind ?? ""] && <div className="path muted tiny">{p.source_ref}</div>}</td>
                      <td>{DEST[p.destination ?? ""] ?? p.destination}</td>
                      <td>{p.status === "open" ? <span className="checks"><Badge tone="warning">open</Badge><MarkTestData id={p.id} /></span>
                        : <Badge tone="neutral">{p.status?.replace("_", " ")}</Badge>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="muted tiny prose" style={{ padding: "0.6rem 1rem" }}>Checked: {c.pii_checked}</p>
          </div>
        )}
      </Card>
    </main>
  );
}
