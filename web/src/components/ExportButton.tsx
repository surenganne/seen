import { Download } from "lucide-react";
import { useState } from "react";
import { api, unwrap } from "../api/client";
import { useWrite } from "../api/hooks";

/** Exports this project's events plus a manifest to ~/.seen/exports (verification runs first). */
export function ExportButton({ pid, from, to }: { pid: string; from?: string; to?: string }) {
  const [format, setFormat] = useState<"ndjson" | "csv">("ndjson");
  const m = useWrite(() => unwrap(api.POST("/api/audit/export", { body: { project: pid, date_from: from, date_to: to, format } })));
  return (
    <span className="checks">
      <select className="select" aria-label="Export format" value={format} onChange={(e) => setFormat(e.target.value as "ndjson" | "csv")}>
        <option value="ndjson">NDJSON</option>
        <option value="csv">CSV</option>
      </select>
      <button type="button" className="btn primary" disabled={m.isPending} onClick={() => m.mutate(undefined)} data-testid="export">
        <Download aria-hidden="true" />{m.isPending ? "Exporting…" : "Export"}
      </button>
      {m.data && (
        <span className="mono tiny muted" role="status" data-testid="export-result" style={{ flexBasis: "100%", textAlign: "right" }}>
          {String(m.data.manifest.count)} events → {m.data.path} {m.data.manifest.verification && (m.data.manifest.verification as { ok: boolean }).ok ? "(verified)" : "(CHAIN NOT VERIFIED)"}
        </span>
      )}
      {m.error && <span className="badge critical" role="alert">{m.error.message}</span>}
    </span>
  );
}
