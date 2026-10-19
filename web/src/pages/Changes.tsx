import { Brain, FileCode2, Search, ShieldAlert, Sparkles, X } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { type ChangeFilters, useChanges, useSkills } from "../api/hooks";
import { ChangesTable } from "../components/ChangesTable";
import { ErrorBox, Loading, PageHead } from "../components/ui";
import { money } from "../lib/format";
import { usePid, useRange } from "../lib/nav";

const bool = (v: string | null) => (v === "true" ? true : undefined);

export function Changes() {
  const pid = usePid();
  const [range] = useRange();
  const [sp, setSp] = useSearchParams();
  const f: ChangeFilters = {
    q: sp.get("q") || undefined,
    tool: sp.get("tool") || undefined,
    status: sp.get("status") || undefined,
    file: sp.get("file") || undefined,
    skill: sp.get("skill") || undefined,
    mem: (sp.get("mem") as ChangeFilters["mem"]) || undefined,
    policy_missed: bool(sp.get("policy_missed")),
    pii: bool(sp.get("pii")),
    days: range,
    sort: sp.get("sort") || "time",
    dir: (sp.get("dir") as "asc" | "desc") || "desc",
  };
  const set = (k: string, v: string | undefined) =>
    setSp((p) => {
      if (v) p.set(k, v);
      else p.delete(k);
      return p;
    }, { replace: true });
  const toggle = (k: string, v: string) => set(k, sp.get(k) === v ? undefined : v);
  const { data, error, isLoading } = useChanges(pid, f);
  const { data: skills } = useSkills(pid);
  const total = data?.items.reduce((a, c) => a + c.cost_usd, 0) ?? 0;

  return (
    <main className="page">
      <PageHead
        title="Changes"
        description="One row per agent turn. Open a row for files, tokens, memory, skills and PII."
        actions={<span className="mono small muted" data-testid="changes-count">{data ? `${data.total} changes · ${money(total)}` : ""}</span>}
      />
      <div className="toolbar" role="search">
        <label className="search">
          <Search aria-hidden="true" />
          <input className="input" type="search" placeholder="Search summaries and files" aria-label="Search changes"
            defaultValue={f.q} onChange={(e) => set("q", e.target.value || undefined)} />
        </label>
        <select className="select" aria-label="Git status" value={f.status ?? ""} onChange={(e) => set("status", e.target.value || undefined)}>
          <option value="">Any git status</option>
          <option value="committed">Committed</option>
          <option value="uncommitted">Uncommitted</option>
          <option value="reverted">Reverted</option>
        </select>
        <select className="select" aria-label="Skill" value={f.skill ?? ""} onChange={(e) => set("skill", e.target.value || undefined)}>
          <option value="">Any skill</option>
          {skills?.filter((s) => s.runs > 0).map((s) => <option key={s.id} value={s.id}>{s.id}</option>)}
        </select>
      </div>
      <div className="toolbar" aria-label="Filters">
        <button type="button" className="chip" aria-pressed={f.tool === "claude-code"} onClick={() => toggle("tool", "claude-code")}>claude-code</button>
        <button type="button" className="chip" aria-pressed={f.mem === "missed"} onClick={() => toggle("mem", "missed")}><Brain aria-hidden="true" />Memory not loaded</button>
        <button type="button" className="chip" aria-pressed={!!f.policy_missed} onClick={() => toggle("policy_missed", "true")}><Sparkles aria-hidden="true" />Skill policy missed</button>
        <button type="button" className="chip" aria-pressed={!!f.pii} onClick={() => toggle("pii", "true")}><ShieldAlert aria-hidden="true" />PII exposed</button>
        {f.file && (
          <button type="button" className="chip" aria-pressed onClick={() => set("file", undefined)} aria-label={`Clear file filter ${f.file}`}>
            <FileCode2 aria-hidden="true" /><span className="mono">{f.file}</span><X aria-hidden="true" />
          </button>
        )}
      </div>
      {isLoading && <Loading what="Loading changes" />}
      {error && <ErrorBox error={error} />}
      {data && (
        <section className="panel">
          <ChangesTable
            rows={data.items}
            pid={pid}
            sort={{
              sort: f.sort ?? "time",
              dir: f.dir ?? "desc",
              onSort: (s) => {
                const dir = f.sort === s && f.dir === "desc" ? "asc" : "desc";
                setSp((p) => { p.set("sort", s); p.set("dir", dir); return p; }, { replace: true });
              },
            }}
          />
        </section>
      )}
    </main>
  );
}
