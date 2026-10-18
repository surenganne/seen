import type { ReactNode } from "react";

type Tone = "good" | "warning" | "critical" | "neutral" | "accent";

const ICON: Record<Tone, string> = { good: "✓", warning: "!", critical: "✕", neutral: "•", accent: "◉" };

export function Badge({ tone, children, title }: { tone: Tone; children: ReactNode; title?: string }) {
  return (
    <span className={`badge ${tone}`} title={title}>
      <span aria-hidden="true">{ICON[tone]}</span>
      {children}
    </span>
  );
}

const SKILL_TONE: Record<string, Tone> = { approved: "good", changed: "warning", unreviewed: "neutral", blocked: "critical" };
export const SkillStatus = ({ status }: { status: string | null | undefined }) =>
  status ? <Badge tone={SKILL_TONE[status] ?? "neutral"}>{status}</Badge> : <span className="muted">—</span>;

const GIT_TONE: Record<string, Tone> = { committed: "good", uncommitted: "warning", reverted: "neutral" };
export const GitStatus = ({ status }: { status: string | null | undefined }) =>
  status ? <Badge tone={GIT_TONE[status] ?? "neutral"}>{status}</Badge> : <span className="muted">no files</span>;

export const MemState = ({ state }: { state: string | null | undefined }) =>
  state === "missed" ? <Badge tone="critical">memory not loaded</Badge> : state === "loaded" ? <Badge tone="good">loaded</Badge> : <span className="muted">—</span>;

/** Never a bare "clean": say what was checked. */
export function PiiChip({ count, high }: { count: number; high?: boolean }) {
  if (count > 0) return <Badge tone={high ? "critical" : "warning"}>PII ×{count}</Badge>;
  return <span className="muted" title="No structured identifiers found. Names and free text are not detected.">none found</span>;
}

export function Card({ title, aside, children, className = "" }: { title?: ReactNode; aside?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card ${className}`}>
      {title !== undefined && (
        <div className="card-head">
          <h2>{title}</h2>
          {aside}
        </div>
      )}
      <div className="card-body">{children}</div>
    </section>
  );
}

export function Tile({ label, value, sub, alert, children }: { label: string; value: ReactNode; sub?: ReactNode; alert?: boolean; children?: ReactNode }) {
  return (
    <div className={`card tile ${alert ? "alert" : ""}`} data-testid={`tile-${label}`}>
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {sub && <div className="sub">{sub}</div>}
      {children}
    </div>
  );
}

export function Loading({ what = "Loading" }: { what?: string }) {
  return <div className="empty" role="status">{what}…</div>;
}

export function ErrorBox({ error }: { error: unknown }) {
  return <div className="banner critical" role="alert">{error instanceof Error ? error.message : "Something went wrong."}</div>;
}

export function Seal({ ok, count, at }: { ok: boolean; count: number; at: string }) {
  return (
    <span className={`seal ${ok ? "ok" : "bad"}`} data-testid="chain-seal" title={`Verified ${at}`}>
      <span className="dot" aria-hidden="true">{ok ? "✓" : "✕"}</span>
      {ok ? `Chain verified · ${count.toLocaleString()} events` : "Chain verification failed"}
    </span>
  );
}
