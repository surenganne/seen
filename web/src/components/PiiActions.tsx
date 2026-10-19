import { api, unwrap } from "../api/client";
import { useWrite } from "../api/hooks";

export function MarkTestData({ id }: { id: string }) {
  const m = useWrite(() => unwrap(api.POST("/api/pii/{finding_id}/mark-test-data", { params: { path: { finding_id: id } } })));
  return (
    <button type="button" className="btn ghost sm" disabled={m.isPending} onClick={() => m.mutate(undefined)} title="Audited: records who marked it">
      {m.isPending ? "Marking…" : "Mark as test data"}
    </button>
  );
}
