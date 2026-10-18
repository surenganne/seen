import type { S } from "../api/client";

/** Approve / Block arrive with P4-2 (they write skills.lock.json and an approval.skill audit event). */
export function SkillActions(_: { skill: S["SkillDetail"]; pid: string }) {
  return null;
}
