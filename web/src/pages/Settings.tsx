import { useSettings } from "../api/hooks";
import { PiiSettings } from "../components/PiiSettings";
import { Badge, Card, ErrorBox, Loading, PageHead } from "../components/ui";

function KV({ obj }: { obj: Record<string, unknown> }) {
  return (
    <dl className="kv">
      {Object.entries(obj).map(([k, v]) => (
        <div key={k} style={{ display: "contents" }}>
          <dt>{k.replace(/_/g, " ")}</dt>
          <dd className="mono">{Array.isArray(v) ? v.join(", ") : typeof v === "boolean" ? (v ? "on" : "off") : String(v ?? "—")}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Settings() {
  const { data: s, error, isLoading } = useSettings();
  if (isLoading) return <div className="page"><Loading what="Loading settings" /></div>;
  if (error || !s) return <div className="page"><ErrorBox error={error} /></div>;
  return (
    <div className="page" data-testid="settings">
      <PageHead title="Settings" description="Read from ~/.seen/config.toml. PII detection is editable here; every change is written to the audit trail." />
      <div className="grid split">
        <PiiSettings pii={s.pii} />
        <div className="stack">
          <Card title="Connected tools" flush>
            <ul className="rows">
              {s.tools.map((t) => (
                <li key={String(t.id)}>
                  <span>{String(t.name)}</span>
                  {t.connected ? <Badge tone="good">{(t.versions as string[]).join(", ")}</Badge> : <Badge tone="neutral">no sessions yet</Badge>}
                </li>
              ))}
            </ul>
          </Card>
          <Card title="Team sync" aside={<Badge tone="neutral">{s.sync.enabled ? "on" : "off"}</Badge>}>
            <KV obj={s.sync} />
            <p className="muted tiny" style={{ marginTop: 8 }}>Prompts, diffs, file contents and PII values never sync.</p>
          </Card>
        </div>
      </div>
      <div className="grid cols3">
        <Card title="Memory behaviour"><KV obj={s.memory} /></Card>
        <Card title="Skill auditing"><KV obj={s.skills} /></Card>
        <Card title="Audit retention"><KV obj={s.audit} /></Card>
      </div>
      <div className="grid split">
        <Card title="Price table" flush aside={s.prices.verified ? <Badge tone="good">verified</Badge> : <Badge tone="warning">unverified</Badge>}>
          <div className="table-wrap" tabIndex={0} role="region" aria-label="Price table">
            <table className="data">
              <thead><tr><th>Model</th><th className="num">Input</th><th className="num">Output</th><th className="num">Cache read</th><th className="num">Cache write</th></tr></thead>
              <tbody>
                {Object.entries(s.prices.models as Record<string, Record<string, number>>).map(([m, p]) => (
                  <tr key={m}><td className="mono">{m}</td><td className="num">${p.input}</td><td className="num">${p.output}</td><td className="num">${p.cache_read}</td><td className="num">${p.cache_write_5m}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted tiny" style={{ padding: "0.6rem 1rem" }}>
            Table <span className="mono">{String(s.prices.version)}</span>. USD per million tokens; API-equivalent figures, not your bill.
          </p>
        </Card>
        <Card title="Local data"><KV obj={s.local_data} /></Card>
      </div>
    </div>
  );
}
