import { Ban, Check } from "lucide-react";
import { api, type S, unwrap } from "../api/client";
import { useWrite } from "../api/hooks";
import { Note } from "./ui";

/** Approve writes the current hash to .seen/skills.lock.json; Block lists the skill as blocked. Both are audited. */
export function SkillActions({ skill, pid }: { skill: S["SkillDetail"]; pid: string }) {
  const approve = useWrite(() => unwrap(api.POST("/api/skills/{sid}/approve", { params: { path: { sid: skill.id }, query: { project: pid } } })));
  const block = useWrite(() => unwrap(api.POST("/api/skills/{sid}/block", { params: { path: { sid: skill.id }, query: { project: pid } } })));
  const err = approve.error ?? block.error;
  return (
    <div className="form" data-testid="skill-actions">
      <div className="checks">
        <button type="button" className="btn primary" disabled={approve.isPending || skill.status === "approved"} onClick={() => approve.mutate(undefined)}>
          <Check aria-hidden="true" />
          {skill.status === "blocked" ? "Unblock and approve" : skill.status === "approved" ? "Version approved" : `Approve ${skill.hash_short ?? "version"}`}
        </button>
        <button type="button" className="btn danger" disabled={block.isPending || skill.status === "blocked"} onClick={() => block.mutate(undefined)}>
          <Ban aria-hidden="true" />{skill.status === "blocked" ? "Blocked" : "Block"}
        </button>
      </div>
      <p className="muted tiny" style={{ margin: 0 }}>
        Writes <span className="mono">.seen/skills.lock.json</span> in the repo; commit it so the team shares the decision.
      </p>
      {err && <Note tone="critical">{err.message}</Note>}
    </div>
  );
}
