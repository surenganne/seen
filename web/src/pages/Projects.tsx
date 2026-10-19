import { FolderPlus } from "lucide-react";
import { Link } from "react-router-dom";
import { useProjects } from "../api/hooks";
import { Eyes } from "../components/Eyes";
import { Badge, Empty, ErrorBox, Loading, PageHead } from "../components/ui";
import { money, when } from "../lib/format";
import { useRange, withRange } from "../lib/nav";

export function Projects() {
  const { data, error, isLoading } = useProjects();
  const [range] = useRange();
  return (
    <div className="page">
      <PageHead title="Projects" description="Repositories Seen has recorded agent work in on this machine." />
      {isLoading && <Loading what="Loading projects" rows={3} />}
      {error && <ErrorBox error={error} />}
      {data?.length === 0 && (
        <div className="panel">
          <Empty icon={FolderPlus} title="No projects recorded yet">
            Install the plugin, run <code>seen init</code> in a repo and start a Claude Code session. To explore with sample data, run{" "}
            <code>seen dev-seed --home /tmp/seen-demo</code> and serve that folder.
          </Empty>
        </div>
      )}
      <div className="projects">
        {data?.map((p) => (
          <Link key={p.id} to={withRange(`/p/${p.id}/`, range)} className="project" data-testid="project-card">
            <div className="top">
              <div style={{ minWidth: 0 }}>
                <h2>{p.name ?? p.id}</h2>
                <div className="path muted tiny" style={{ marginTop: 2 }}>{p.remote ?? p.root_path}</div>
              </div>
              <Eyes size={26} label="Seen" />
            </div>
            <div className="facts">
              <div><div className="label">Changes</div><div className="value mono">{p.changes.toLocaleString()}</div></div>
              <div><div className="label">Cost, 7 days</div><div className="value mono">{money(p.cost_7d)}</div></div>
              <div><div className="label">Last change</div><div className="value mono small">{when(p.last_change_at)}</div></div>
            </div>
            {p.alert && <Badge tone="critical">Needs attention</Badge>}
          </Link>
        ))}
      </div>
    </div>
  );
}
