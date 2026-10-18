import { Link } from "react-router-dom";
import { useProjects } from "../api/hooks";
import { Eyes } from "../components/Eyes";
import { ErrorBox, Loading } from "../components/ui";
import { money, when } from "../lib/format";
import { useRange, withRange } from "../lib/nav";

export function Projects() {
  const { data, error, isLoading } = useProjects();
  const [range] = useRange();
  return (
    <main className="page reveal">
      <div className="page-head">
        <div>
          <div className="eyebrow">Ledger</div>
          <h1>Projects</h1>
        </div>
        <p className="muted" style={{ margin: 0, maxWidth: 440 }}>Every repository Seen has watched on this machine. Pick one to see what its agents changed.</p>
      </div>
      {isLoading && <Loading />}
      {error && <ErrorBox error={error} />}
      {data?.length === 0 && (
        <div className="card empty">
          No projects yet. Install the plugin and run a Claude Code session, or run <span className="mono">seen dev-seed</span> into a scratch SEEN_HOME.
        </div>
      )}
      <div className="grid grid-even">
        {data?.map((p, i) => (
          <Link key={p.id} to={withRange(`/p/${p.id}/`, range)} className="card" style={{ textDecoration: "none", padding: "1rem 1.1rem" }} data-testid="project-card">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start", gap: ".75rem" }}>
              <div style={{ minWidth: 0 }}>
                <div className="eyebrow">No. {String(i + 1).padStart(2, "0")}</div>
                <h2 style={{ fontSize: "1.35rem", marginTop: ".2rem" }}>{p.name ?? p.id}</h2>
                <div className="path muted" style={{ marginTop: ".2rem" }}>{p.remote ?? p.root_path}</div>
              </div>
              <Eyes state={p.alert ? "alert" : "idle"} size={34} label={p.alert ? "Needs attention" : "All quiet"} />
            </div>
            <dl className="kv" style={{ marginTop: ".9rem" }}>
              <dt>Changes</dt><dd className="mono">{p.changes.toLocaleString()}</dd>
              <dt>Cost, 7 days</dt><dd className="mono">{money(p.cost_7d)}</dd>
              <dt>Last change</dt><dd className="mono">{when(p.last_change_at)}</dd>
            </dl>
          </Link>
        ))}
      </div>
    </main>
  );
}
