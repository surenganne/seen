import { Link } from "react-router-dom";
import { AlertTriangle, ArrowDown, ArrowUp, CheckCircle2, Circle, Info, Minus, type LucideIcon, ShieldAlert, ShieldCheck, XCircle } from "lucide-react";
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

/** A summary number. With `to`, the label is a link to the rows behind the number and the whole tile is its click target. */
/** Change against the period just before: an arrow and a word as well as a number, never colour. Volume is neither good nor bad, so it is not tinted. */
export function Delta({ now, prev, days }: { now: number; prev: number; days: number }) {
  if (now === 0 && prev === 0) return null;
  const vs = `vs the previous ${days} days`;
  if (prev === 0) return <div className="delta" data-testid="delta"><ArrowUp aria-hidden="true" />new<span className="sr-only"> {vs}</span><span aria-hidden="true" className="muted"> {vs}</span></div>;
  const pct = Math.round(((now - prev) / prev) * 100);
  const I = pct > 0 ? ArrowUp : pct < 0 ? ArrowDown : Minus;
  const word = pct > 0 ? "up" : pct < 0 ? "down" : "no change";
  return (
    <div className="delta" data-testid="delta">
      <I aria-hidden="true" />
      <span aria-hidden="true">{pct === 0 ? "no change" : `${Math.abs(pct)}%`}</span>
      <span className="sr-only">{pct === 0 ? "no change" : `${word} ${Math.abs(pct)}%`} {vs}</span>
      <span aria-hidden="true" className="muted"> {vs}</span>
    </div>
  );
}

/** A trend with no axes: the numbers sit beside it, so it is decoration for the eye and hidden from screen readers. */
export function Spark({ values }: { values: number[] }) {
  if (values.length < 2 || Math.max(...values) === 0) return null;
  const W = 96, H = 28, max = Math.max(...values);
  const pts = values.map((v, i) => [(i / (values.length - 1)) * (W - 4) + 2, H - 3 - (v / max) * (H - 8)] as const);
  const last = pts[pts.length - 1]!;
  return (
    <svg className="spark" viewBox={`0 0 ${W} ${H}`} width={W} height={H} aria-hidden="true" focusable="false">
      <polyline points={pts.map((p) => p.join(",")).join(" ")} fill="none" stroke="var(--magnitude)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={last[0]} cy={last[1]} r="3" fill="var(--magnitude)" stroke="var(--surface)" strokeWidth="2" />
    </svg>
  );
}

export function Tile({ label, value, sub, alert, icon: I, to, delta, spark }: {
  label: string; value: ReactNode; sub?: ReactNode; alert?: boolean; icon?: LucideIcon; to?: string; delta?: ReactNode; spark?: ReactNode;
}) {
  return (
    <div className="stat" data-testid={`tile-${label}`} data-alert={alert ? "true" : undefined}>
      <div className="label">{I && <I aria-hidden="true" />}{to ? <Link className="stat-link" to={to}>{label}</Link> : label}</div>
      <div className="stat-main">
        <div className="value">{value}</div>
        {spark}
      </div>
      {sub && <div className="sub">{sub}</div>}
      {delta}
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

/** The keyboard and screen-reader way into a clickable table row: a real button named by the row's main text.
 *  The row's own click handler stays as a convenience for the mouse. */
export function RowButton({ onClick, children }: { onClick: () => void; children: ReactNode }) {
  return <button type="button" className="rowbtn" onClick={(e) => { e.stopPropagation(); onClick(); }}>{children}</button>;
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
