import { useSearchParams } from "react-router-dom";
import { type ChangeFilters, useChanges, useSkills } from "../api/hooks";
import { ChangesTable } from "../components/ChangesTable";
import { Card, ErrorBox, Loading } from "../components/ui";
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
  const tools = ["claude-code"];
  const total = data?.items.reduce((a, c) => a + c.cost_usd, 0) ?? 0;

  return (
    <main className="page reveal">
      <div className="page-head">
        <div>
          <div className="eyebrow">Last {range} days</div>
          <h1>Changes</h1>
        </div>
        <span className="mono muted" data-testid="changes-count">{data ? `${data.total} changes · ${money(total)}` : ""}</span>
      </div>
      <Card>
        <div style={{ display: "flex", flexWrap: "wrap", gap: ".5rem", alignItems: "center" }}>
          <input
            className="input"
            type="search"
            placeholder="Search summaries and files"
            aria-label="Search changes"
            defaultValue={f.q}
            onChange={(e) => set("q", e.target.value || undefined)}
            style={{ flex: "1 1 220px" }}
          />
          {tools.map((t) => (
            <button key={t} type="button" className="chip" aria-pressed={f.tool === t} onClick={() => toggle("tool", t)}>{t}</button>
          ))}
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
          <button type="button" className="chip" aria-pressed={f.mem === "missed"} onClick={() => toggle("mem", "missed")}>Memory not loaded</button>
          <button type="button" className="chip" aria-pressed={!!f.policy_missed} onClick={() => toggle("policy_missed", "true")}>Skill policy missed</button>
          <button type="button" className="chip" aria-pressed={!!f.pii} onClick={() => toggle("pii", "true")}>PII exposed</button>
          {f.file && (
            <button type="button" className="chip" aria-pressed onClick={() => set("file", undefined)}>
              file: <span className="mono">{f.file}</span> ✕
            </button>
          )}
        </div>
      </Card>
      {isLoading && <Loading />}
      {error && <ErrorBox error={error} />}
      {data && (
        <Card>
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
        </Card>
      )}
    </main>
  );
}
