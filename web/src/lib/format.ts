const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 });
const usdSmall = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 3, maximumFractionDigits: 4 });
const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });
const whole = new Intl.NumberFormat("en-US");

export const money = (n: number | null | undefined) =>
  n == null ? "—" : n !== 0 && Math.abs(n) < 1 ? usdSmall.format(n) : usd.format(n);
export const tokens = (n: number | null | undefined) => (n == null ? "—" : compact.format(n));
export const int = (n: number | null | undefined) => (n == null ? "—" : whole.format(n));
export const pct = (n: number | null | undefined) => (n == null ? "—" : `${Math.round(n * 100)}%`);

/** Dates are shown in IST (UTC+5:30). */
const IST = "Asia/Kolkata";
export const when = (iso: string | null | undefined) =>
  iso
    ? new Date(iso).toLocaleString("en-IN", { timeZone: IST, day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false })
    : "—";
export const day = (isoDate: string) =>
  new Date(`${isoDate}T12:00:00Z`).toLocaleDateString("en-IN", { timeZone: IST, day: "2-digit", month: "short" });
export const short = (h: string | null | undefined, n = 7) => (h ? h.slice(0, n) : "—");

/** Collapse whitespace and cut at a word boundary with an ellipsis, never mid-word (a request shown as a page heading). */
export function truncateWords(text: string, max: number): string {
  const t = text.split(/\s+/).filter(Boolean).join(" ");
  if (t.length <= max) return t;
  const cut = t.slice(0, max);
  const at = cut.lastIndexOf(" ");
  return `${(at >= max * 0.6 ? cut.slice(0, at) : cut).replace(/[\s.,;:!?-]+$/, "")}…`;
}
