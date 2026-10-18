import { Link, useNavigate, useParams } from "react-router-dom";
import { useChange } from "../api/hooks";
import { MarkTestData } from "../components/PiiActions";
import { Badge, Card, ErrorBox, GitStatus, Loading, MemState, SkillStatus } from "../components/ui";
import { int, money, pct, short, tokens, when } from "../lib/format";
import { usePid, useRange, withRange } from "../lib/nav";

const SOURCE: Record<string, string> = { prompt: "Prompt", file_read: "File read", tool_output: "Tool output", mcp: "MCP tool", injected_memory: "Injected memory", diff_added: "Added lines" };
const DEST: Record<string, string> = { model: "Model", network: "Network", repo: "Repo", memory: "Memory" };

export function ChangeDetail() {
  const pid = usePid();
  const { cid = "" } = useParams();
  const [range] = useRange();
  const nav = useNavigate();
  const { data: c, error, isLoading } = useChange(cid);
  if (isLoading) return <main className="page"><Loading /></main>;
  if (error || !c) return <main className="page"><ErrorBox error={error} /></main>;
  const openPii = c.pii.filter((p) => p.status === "open");
  const high = openPii.some((p) => p.confidence === "high");
  return (
    <main className="page reveal" data-testid="change-detail">
      <div className="page-head">
        <div style={{ minWidth: 0 }}>
          <button type="button" className="btn" onClick={() => nav(-1)} style={{ marginBottom: ".6rem" }} data-testid="back">← Back</button>
          <div className="eyebrow">Change #{c.seq} · {when(c.started_at)} · {c.tool}</div>
          <h1>{c.summary ?? "(no summary)"}</h1>
        </div>
        <div style={{ display: "flex", gap: ".4rem", flexWrap: "wrap" }}>
          <GitStatus status={c.git_status} />
          <MemState state={c.mem_state} />
          {c.policies.some((p) => !p.met) && <Badge tone="warning">policy missed</Badge>}
        </div>
      </div>
      {high && (
        <div className="banner critical" role="alert" data-testid="pii-banner">
          <strong>High-confidence personal data or secrets reached the model in this change.</strong> Seen records exposure; it cannot recall what was sent.
        </div>
      )}
      <div className="grid grid-2">
        <Card title="Files" aside={<span className="mono muted">{c.files.length} files</span>}>
          {c.files.length === 0 ? <p className="muted" style={{ margin: 0 }}>No file changes in this turn.</p> : (
            <ul className="list" data-testid="change-files">
              {c.files.map((f) => (
                <li key={f.path}>
                  <Link className="path" to={withRange(`/p/${pid}/changes`, range, { file: f.path })}>{f.path}</Link>
                  <span className="mono"><span className="plus">+{f.added}</span> <span className="minus">−{f.removed}</span></span>
                </li>
              ))}
            </ul>
          )}
          <dl className="kv" style={{ marginTop: ".8rem" }}>
            <dt>HEAD before</dt><dd className="mono">{short(c.git_head_before, 12)}</dd>
            <dt>HEAD after</dt><dd className="mono">{short(c.git_head_after, 12)}</dd>
            <dt>Duration</dt><dd className="mono">{c.duration_s != null ? `${c.duration_s}s` : "—"}</dd>
          </dl>
        </Card>
        <Card title="Tokens and cost" aside={<span className="mono">{money(c.cost_usd)}</span>}>
          <div className="table-wrap">
            <table className="ledger">
              <thead><tr><th>Kind</th><th className="num">Tokens</th><th className="num">Cost</th><th style={{ width: "40%" }}>Share of cost</th></tr></thead>
              <tbody>
                {c.cost_breakdown.map((p) => (
                  <tr key={p.kind} style={{ cursor: "default" }}>
                    <td>{p.kind.replace("_", " ")}</td>
                    <td className="num">{int(p.tokens)}</td>
                    <td className="num">{money(p.cost_usd)}</td>
                    <td><div style={{ display: "flex", gap: ".4rem", alignItems: "center" }}><span className="bar" style={{ flex: 1 }}><span style={{ width: pct(p.share) }} /></span><span className="mono muted">{pct(p.share)}</span></div></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted" style={{ fontSize: ".78rem", marginBottom: 0 }}>
            {c.model} · price table <span className="mono">{c.price_version}</span>{c.prices_verified ? "" : " (unverified)"} · {tokens(c.tokens.out)} output tokens
          </p>
        </Card>
      </div>
      <Card title="Prompt">
        {c.prompt_text ? <pre className="snippet" style={{ whiteSpace: "pre-wrap" }}>{c.prompt_text}</pre> : (
          <p className="muted" style={{ margin: 0 }}>Not stored (prompt storage: <span className="mono">{c.prompt_storage}</span>). The transcript under ~/.claude still holds the raw text.</p>
        )}
      </Card>
      <div className="grid grid-even">
        <Card title="Memory read" aside={<span className="mono muted">{c.mem_injected_tokens} tokens</span>}>
          {c.memories.length === 0 ? <p className="muted" style={{ margin: 0 }}>No memory injected.</p> : (
            <ul className="list">{c.memories.map((m) => <li key={m.memory_id}><span className="mono">{m.memory_id}</span><span className="muted">{m.type ?? ""}</span></li>)}</ul>
          )}
          {c.memory_saved.length > 0 && (
            <>
              <div className="eyebrow" style={{ marginTop: ".8rem" }}>Memory saved from this change</div>
              <ul className="list">{c.memory_saved.map((m) => <li key={m}><Link className="mono" to={withRange(`/p/${pid}/memory`, range)}>{m}</Link></li>)}</ul>
            </>
          )}
        </Card>
        <Card title="Skills used">
          {c.skills.length === 0 ? <p className="muted" style={{ margin: 0 }}>No skills ran.</p> : (
            <ul className="list" data-testid="change-skills">
              {c.skills.map((s) => (
                <li key={s.ordinal}>
                  <span><span className="mono muted">{s.ordinal}.</span> <Link className="mono" to={withRange(`/p/${pid}/skills`, range, { skill: s.skill_id })}>{s.skill_id}</Link> <span className="mono muted">@{s.hash_short ?? "?"}</span></span>
                  <span style={{ display: "flex", gap: 4 }}><Badge tone="neutral">{s.trigger ?? "?"}</Badge><SkillStatus status={s.status} /></span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Required-skill checks">
          {c.policies.length === 0 ? <p className="muted" style={{ margin: 0 }}>No policy covers the files this change touched.</p> : (
            <ul className="list">
              {c.policies.map((p) => (
                <li key={p.policy_id}>
                  <span>{p.title} <span className="mono muted">needs {p.require_skill}</span></span>
                  {p.met ? <Badge tone="good">met</Badge> : <Badge tone="warning">missed</Badge>}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
      <Card title="PII exposure" aside={<span className="eyebrow">types and counts only, never values</span>}>
        {c.pii.length === 0 ? (
          <p className="muted" style={{ margin: 0 }} data-testid="pii-none">No structured identifiers found. Checked: {c.pii_checked}</p>
        ) : (
          <div className="table-wrap" data-testid="pii-panel">
            <table className="ledger">
              <thead><tr><th>Type</th><th className="num">Count</th><th>Confidence</th><th>Source</th><th>Destination</th><th>Status</th></tr></thead>
              <tbody>
                {c.pii.map((p) => (
                  <tr key={p.id} style={{ cursor: "default" }}>
                    <td className="mono">{p.type}</td>
                    <td className="num">{p.count} <span className="muted">({p.distinct_count} distinct)</span></td>
                    <td><Badge tone={p.confidence === "high" ? "critical" : p.confidence === "medium" ? "warning" : "neutral"}>{p.confidence}</Badge></td>
                    <td>{SOURCE[p.source_kind ?? ""] ?? p.source_kind} <span className="path muted">{p.source_ref}</span></td>
                    <td>{DEST[p.destination ?? ""] ?? p.destination}</td>
                    <td>{p.status === "open" ? <span style={{ display: "flex", gap: 4, flexWrap: "wrap" }}><Badge tone="warning">open</Badge><MarkTestData id={p.id} /></span> : <Badge tone="neutral">{p.status?.replace("_", " ")}</Badge>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted" style={{ fontSize: ".78rem" }}>Checked: {c.pii_checked}</p>
          </div>
        )}
      </Card>
    </main>
  );
}
