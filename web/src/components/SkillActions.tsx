import { api, type S, unwrap } from "../api/client";
import { useWrite } from "../api/hooks";

/** Approve writes the current hash to .seen/skills.lock.json; Block lists the skill as blocked. Both are audited. */
export function SkillActions({ skill, pid }: { skill: S["SkillDetail"]; pid: string }) {
  const approve = useWrite(() => unwrap(api.POST("/api/skills/{sid}/approve", { params: { path: { sid: skill.id }, query: { project: pid } } })));
  const block = useWrite(() => unwrap(api.POST("/api/skills/{sid}/block", { params: { path: { sid: skill.id }, query: { project: pid } } })));
  const err = approve.error ?? block.error;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: ".4rem" }} data-testid="skill-actions">
      <div style={{ display: "flex", gap: ".4rem", flexWrap: "wrap" }}>
        <button type="button" className="btn primary" disabled={approve.isPending || skill.status === "approved"} onClick={() => approve.mutate(undefined)}>
          {skill.status === "blocked" ? "Unblock and approve" : skill.status === "approved" ? "Version approved" : `Approve ${skill.hash_short ?? "version"}`}
        </button>
        <button type="button" className="btn danger" disabled={block.isPending || skill.status === "blocked"} onClick={() => block.mutate(undefined)}>
          {skill.status === "blocked" ? "Blocked" : "Block"}
        </button>
      </div>
      <p className="muted" style={{ fontSize: ".76rem", margin: 0 }}>
        Writes <span className="mono">.seen/skills.lock.json</span> in the repo; commit it so the team shares the decision.
      </p>
      {err && <span className="badge critical" role="alert">{err.message}</span>}
    </div>
  );
}
