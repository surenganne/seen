import { AlertTriangle, CheckCircle2, Circle, Info, type LucideIcon, ShieldAlert, ShieldCheck, XCircle } from "lucide-react";
import type { ReactNode } from "react";

type Tone = "good" | "warning" | "critical" | "neutral" | "accent" | "info";

const ICON: Record<Tone, LucideIcon> = { good: CheckCircle2, warning: AlertTriangle, critical: XCircle, neutral: Circle, accent: Circle, info: Info };

/** Status always carries an icon and a label; colour is never the only signal. */
export function Badge({ tone, children, title }: { tone: Tone; children: ReactNode; title?: string }) {
  const I = ICON[tone];
  return (
    <span className={`badge ${tone}`} title={title}>
      <I aria-hidden="true" strokeWidth={2.25} />
      {children}
    </span>
  );
}

const SKILL_TONE: Record<string, Tone> = { approved: "good", changed: "warning", unreviewed: "neutral", blocked: "critical" };
export const SkillStatus = ({ status }: { status: string | null | undefined }) =>
  status ? <Badge tone={SKILL_TONE[status] ?? "neutral"}>{status}</Badge> : <span className="muted">—</span>;

const GIT_TONE: Record<string, Tone> = { committed: "good", uncommitted: "warning", reverted: "neutral" };
export const GitStatus = ({ status }: { status: string | null | undefined }) =>
  status ? <Badge tone={GIT_TONE[status] ?? "neutral"}>{status}</Badge> : <span className="muted small">no files</span>;

export const MemState = ({ state }: { state: string | null | undefined }) =>
  state === "missed" ? <Badge tone="critical">memory not loaded</Badge> : state === "loaded" ? <Badge tone="good">memory loaded</Badge> : null;

/** Never a bare "clean": say what was checked. */
export function PiiChip({ count, high }: { count: number; high?: boolean }) {
  if (count > 0) return <Badge tone={high ? "critical" : "warning"}>PII ×{count}</Badge>;
  return <span className="muted small" title="No structured identifiers found. Names and free text are not detected.">none found</span>;
}

export function Card({ title, aside, children, className = "", flush, id }: {
  title?: ReactNode; aside?: ReactNode; children: ReactNode; className?: string; flush?: boolean; id?: string;
}) {
  return (
    <section className={`panel ${className}`} aria-labelledby={title !== undefined && id ? id : undefined}>
      {title !== undefined && (
        <div className="panel-head">
          <h2 id={id}>{title}</h2>
          {aside}
        </div>
      )}
      <div className={`panel-body${flush ? " flush" : ""}`}>{children}</div>
    </section>
  );
}

export function Tile({ label, value, sub, alert, icon: I }: { label: string; value: ReactNode; sub?: ReactNode; alert?: boolean; icon?: LucideIcon }) {
  return (
    <div className="stat" data-testid={`tile-${label}`} data-alert={alert ? "true" : undefined}>
      <div className="label">{I && <I aria-hidden="true" />}{label}</div>
      <div className="value">{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
}

export function Loading({ what = "Loading", rows = 4 }: { what?: string; rows?: number }) {
  return (
    <div role="status" aria-label={what} style={{ display: "grid", gap: "0.6rem" }}>
      <div className="skeleton" style={{ height: 28, width: "38%" }} />
      {Array.from({ length: rows }, (_, i) => <div key={i} className="skeleton" style={{ height: 44 }} />)}
      <span className="sr-only">{what}…</span>
    </div>
  );
}

export function Empty({ icon: I = Info, title, children }: { icon?: LucideIcon; title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <I aria-hidden="true" />
      <strong>{title}</strong>
      {children && <div className="small prose">{children}</div>}
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  return (
    <div className="note critical" role="alert">
      <XCircle aria-hidden="true" />
      <span>{error instanceof Error ? error.message : "Something went wrong loading this page."}</span>
    </div>
  );
}

export function Note({ tone = "info", icon, children, testId }: { tone?: "info" | "warning" | "critical"; icon?: LucideIcon; children: ReactNode; testId?: string }) {
  const I = icon ?? (tone === "critical" ? XCircle : tone === "warning" ? AlertTriangle : Info);
  return (
    <div className={`note ${tone}`} data-testid={testId} role={tone === "critical" ? "alert" : undefined}>
      <I aria-hidden="true" />
      <div>{children}</div>
    </div>
  );
}

export function Seal({ ok, count, at }: { ok: boolean; count: number; at: string }) {
  const I = ok ? ShieldCheck : ShieldAlert;
  return (
    <span className={`seal ${ok ? "ok" : "bad"}`} data-testid="chain-seal" title={`Verified ${at}`}>
      <I aria-hidden="true" />
      {ok ? `Chain verified · ${count.toLocaleString()} events` : "Chain verification failed"}
    </span>
  );
}

export function PageHead({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  );
}

/** Previous / next pager with "a–b of n". Hidden when everything fits on one page. */
export function Pager({ page, pageSize, total, onPage, what = "items" }: { page: number; pageSize: number; total: number; onPage: (p: number) => void; what?: string }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (total <= pageSize && page === 1) return null;
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  return (
    <nav className="pager" aria-label={`${what} pages`} data-testid="pager">
      <button type="button" className="btn sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>← Previous</button>
      <span className="mono tiny muted">{from}–{Math.min(page * pageSize, total)} of {total} {what} · page {page} of {pages}</span>
      <button type="button" className="btn sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next →</button>
    </nav>
  );
}
