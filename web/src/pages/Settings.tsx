import { useSettings } from "../api/hooks";
import { PiiSettings } from "../components/PiiSettings";
import { Badge, Card, ErrorBox, Loading } from "../components/ui";

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
  if (isLoading) return <main className="page"><Loading /></main>;
  if (error || !s) return <main className="page"><ErrorBox error={error} /></main>;
  return (
    <main className="page reveal" data-testid="settings">
      <div className="page-head">
        <div>
          <div className="eyebrow">~/.seen/config.toml</div>
          <h1>Settings</h1>
        </div>
      </div>
      <div className="grid grid-even">
        <Card title="Connected tools">
          <ul className="list">
            {s.tools.map((t) => (
              <li key={String(t.id)}>
                <span>{String(t.name)}</span>
                {t.connected ? <Badge tone="good">{(t.versions as string[]).join(", ")}</Badge> : <Badge tone="neutral">no sessions yet</Badge>}
              </li>
            ))}
          </ul>
        </Card>
        <Card title="Memory behaviour"><KV obj={s.memory} /></Card>
        <Card title="Skill auditing"><KV obj={s.skills} /></Card>
        <PiiSettings pii={s.pii} />
        <Card title="Audit retention"><KV obj={s.audit} /></Card>
        <Card title="Team sync" aside={<Badge tone="neutral">{s.sync.enabled ? "on" : "off"}</Badge>}>
          <KV obj={s.sync} />
          <p className="muted" style={{ fontSize: ".78rem", marginBottom: 0 }}>Prompts, diffs, file contents and PII values never sync.</p>
        </Card>
        <Card title="Price table" aside={s.prices.verified ? <Badge tone="good">verified</Badge> : <Badge tone="warning">unverified</Badge>}>
          <p className="mono" style={{ marginTop: 0 }}>{String(s.prices.version)}</p>
          <div className="table-wrap">
            <table className="ledger">
              <thead><tr><th>Model</th><th className="num">In</th><th className="num">Out</th><th className="num">Cache r</th><th className="num">Cache w</th></tr></thead>
              <tbody>
                {Object.entries(s.prices.models as Record<string, Record<string, number>>).map(([m, p]) => (
                  <tr key={m} style={{ cursor: "default" }}><td className="mono">{m}</td><td className="num">${p.input}</td><td className="num">${p.output}</td><td className="num">${p.cache_read}</td><td className="num">${p.cache_write_5m}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted" style={{ fontSize: ".78rem", marginBottom: 0 }}>USD per million tokens. API-equivalent figures, not your bill.</p>
        </Card>
        <Card title="Local data"><KV obj={s.local_data} /></Card>
      </div>
    </main>
  );
}
