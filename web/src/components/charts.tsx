import { type ReactNode, useState } from "react";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, type TooltipContentProps, XAxis, YAxis } from "recharts";
import type { S } from "../api/client";
import { day, int, money } from "../lib/format";

const axis = { stroke: "var(--ink-3)", fontSize: 11, fontFamily: "var(--font-mono)" };
const GRAY = "var(--border-strong)"; // the de-emphasis colour: context next to the series that is the point

/** A chart and its table, one toggle. Every chart ships both (dataviz rule: a table view always exists). */
function Chartable({ label, chart, table }: { label: string; chart: ReactNode; table: ReactNode }) {
  const [asTable, setAsTable] = useState(false);
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: ".25rem" }}>
        <button type="button" className="btn ghost sm" aria-pressed={asTable} onClick={() => setAsTable(!asTable)}>{asTable ? "Chart" : "Table view"}</button>
      </div>
      {asTable ? <div className="table-wrap" tabIndex={0} role="region" aria-label={`${label}, as a table`}>{table}</div> : chart}
    </div>
  );
}

const Swatch = ({ color }: { color: string }) => <span style={{ width: 8, height: 8, borderRadius: 2, background: color, display: "inline-block" }} aria-hidden="true" />;

type Entry = { name: string; value: number | string; color: string };
function Tip({ active, label, entries, total, extra }: { active?: boolean; label?: string; entries: Entry[]; total?: string; extra?: ReactNode }) {
  if (!active || !entries.length) return null;
  return (
    <div className="chart-tip">
      <div className="label">{label ? day(label) : ""}</div>
      {entries.map((p) => (
        <div key={p.name} style={{ display: "flex", gap: ".5rem", alignItems: "center" }}>
          <Swatch color={p.color} /><span>{p.name}</span>
          <span className="mono" style={{ marginLeft: "auto", paddingLeft: 12 }}>{typeof p.value === "number" ? int(p.value) : p.value}</span>
        </div>
      ))}
      {total && <div className="mono" style={{ borderTop: "1px solid var(--border)", marginTop: 4, paddingTop: 4 }}>{total}</div>}
      {extra}
    </div>
  );
}

/** Requests per day: the ones that changed files are the point (accent), the talk-only rest is context (gray). */
export function ActivityChart({ days }: { days: S["DayStat"][] }) {
  const rows = days.map((d) => ({ ...d, quiet: d.requests - d.changed }));
  const tip = ({ active, payload, label }: TooltipContentProps) => {
    const r = payload?.[0]?.payload as (typeof rows)[number] | undefined;
    if (!r) return null;
    return (
      <Tip active={active} label={label as string | undefined} total={`${r.requests} ${r.requests === 1 ? "request" : "requests"}`}
        entries={[{ name: "Changed files", value: r.changed, color: "var(--series-1)" }, { name: "No file changes", value: r.quiet, color: GRAY }]}
        extra={r.changed > 0 ? <div className="mono tiny muted" style={{ marginTop: 4 }}>+{int(r.added)} −{int(r.removed)} · {r.commits} {r.commits === 1 ? "commit" : "commits"}</div> : null} />
    );
  };
  return (
    <Chartable label="Requests per day"
      chart={
        <>
          <div style={{ height: 200 }} role="img" aria-label="Requests per day, split into those that changed files and those that did not">
            <ResponsiveContainer>
              <BarChart data={rows} margin={{ top: 8, right: 16, left: -16, bottom: 0 }} barCategoryGap="22%">
                <CartesianGrid vertical={false} stroke="var(--grid)" />
                <XAxis dataKey="date" tickFormatter={day} tick={axis} tickLine={false} axisLine={{ stroke: "var(--border-strong)" }} minTickGap={14} />
                <YAxis allowDecimals={false} tick={axis} tickLine={false} axisLine={false} width={40} />
                <Tooltip content={tip} cursor={{ fill: "var(--surface-2)" }} />
                <Bar dataKey="changed" stackId="a" fill="var(--series-1)" stroke="var(--surface)" strokeWidth={2} maxBarSize={28} />
                <Bar dataKey="quiet" stackId="a" fill={GRAY} stroke="var(--surface)" strokeWidth={2} radius={[4, 4, 0, 0]} maxBarSize={28} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <ul className="legend">
            <li><Swatch color="var(--series-1)" />Changed files</li>
            <li><Swatch color={GRAY} />No file changes</li>
          </ul>
        </>
      }
      table={
        <table className="data" aria-label="Requests per day">
          <thead><tr><th>Day</th><th className="num">Changed files</th><th className="num">No file changes</th><th className="num">Lines</th><th className="num">Commits</th></tr></thead>
          <tbody>{rows.map((r) => <tr key={r.date}><td>{day(r.date)}</td><td className="num">{r.changed}</td><td className="num">{r.quiet}</td><td className="num">+{int(r.added)} −{int(r.removed)}</td><td className="num">{r.commits}</td></tr>)}</tbody>
        </table>
      } />
  );
}

/** Colour follows the model family, never its rank: a filter that changes the model count must not repaint the rest. */
const FAMILIES = ["opus", "sonnet", "haiku"];
const familyIndex = (m: string) => FAMILIES.findIndex((f) => m.toLowerCase().includes(f));
const modelColor = (m: string) => (familyIndex(m) < 0 ? GRAY : `var(--series-${familyIndex(m) + 1})`);
const modelKey = (m: string) => (familyIndex(m) < 0 ? "other" : m);
const modelName = (m: string) => (m === "other" ? "Other models" : m);

/** Cost per day, stacked by model; the legend carries each model's total, so identity never rests on colour alone. */
export function SpendChart({ days }: { days: S["DayStat"][] }) {
  const keys = Array.from(new Set(days.flatMap((d) => Object.keys(d.cost_by_model)).map(modelKey))).sort((a, b) => {
    const [ia, ib] = [familyIndex(a), familyIndex(b)];
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a.localeCompare(b);
  });
  const rows = days.map((d) => {
    const r: Record<string, number | string> = { date: d.date, total: d.cost_usd };
    for (const [m, v] of Object.entries(d.cost_by_model)) r[modelKey(m)] = ((r[modelKey(m)] as number) ?? 0) + v;
    return r;
  });
  const totals = keys.map((k) => rows.reduce((a, r) => a + ((r[k] as number) ?? 0), 0));
  const tip = ({ active, payload, label }: TooltipContentProps) => {
    const parts = (payload ?? []).filter((p) => p.value).map((p) => ({ key: String(p.dataKey), value: Number(p.value) }));
    return (
      <Tip active={active} label={label as string | undefined} total={parts.length > 1 ? `Total ${money(parts.reduce((a, p) => a + p.value, 0))}` : undefined}
        entries={parts.map((p) => ({ name: modelName(p.key), value: money(p.value), color: modelColor(p.key) }))} />
    );
  };
  return (
    <Chartable label="Cost per day"
      chart={
        <>
          <div style={{ height: 200 }} role="img" aria-label="API-equivalent cost per day, stacked by model">
            <ResponsiveContainer>
              <BarChart data={rows} margin={{ top: 8, right: 16, left: -8, bottom: 0 }} barCategoryGap="22%">
                <CartesianGrid vertical={false} stroke="var(--grid)" />
                <XAxis dataKey="date" tickFormatter={day} tick={axis} tickLine={false} axisLine={{ stroke: "var(--border-strong)" }} minTickGap={14} />
                <YAxis tickFormatter={(v: number) => `$${v.toFixed(v >= 10 ? 0 : 2)}`} tick={axis} tickLine={false} axisLine={false} width={48} />
                <Tooltip content={tip} cursor={{ fill: "var(--surface-2)" }} />
                {keys.map((k, i) => (
                  <Bar key={k} dataKey={k} stackId="cost" fill={modelColor(k)} stroke="var(--surface)" strokeWidth={2} radius={i === keys.length - 1 ? [4, 4, 0, 0] : 0} maxBarSize={28} />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
          <ul className="legend" data-testid="spend-legend">
            {keys.map((k, i) => <li key={k}><Swatch color={modelColor(k)} /><span className="mono">{modelName(k)}</span><span className="mono muted">{money(totals[i])}</span></li>)}
          </ul>
        </>
      }
      table={
        <table className="data" aria-label="Cost per day">
          <thead><tr><th>Day</th>{keys.map((k) => <th key={k} className="num">{modelName(k)}</th>)}<th className="num">Total</th></tr></thead>
          <tbody>{rows.map((r) => <tr key={r.date as string}><td>{day(r.date as string)}</td>{keys.map((k) => <td key={k} className="num">{money((r[k] as number) ?? 0)}</td>)}<td className="num">{money(r.total as number)}</td></tr>)}</tbody>
        </table>
      } />
  );
}

/** Single-hue horizontal magnitude bars with direct value labels (no legend needed for one series). */
export function MagnitudeBars({ items, unit = "" }: { items: { label: string; value: number; sub?: string; to?: string; more?: { to: string; text: string; name: string } }[]; unit?: string }) {
  const max = Math.max(1, ...items.map((i) => i.value));
  return (
    <ul className="bars">
      {items.map((i) => (
        <li key={i.label}>
          {i.to ? <Link className="mono bars-link" to={i.to}>{i.label}</Link> : <span className="mono">{i.label}</span>}
          <span className="meter" aria-hidden="true"><span style={{ width: `${(i.value / max) * 100}%` }} /></span>
          <span className="mono" title={i.sub}>{i.value.toLocaleString()}{unit}</span>
          {(i.sub || i.more) && (
            <span className="tiny muted bars-sub">{i.sub}{i.more && <>{i.sub && " · "}<Link to={i.more.to} aria-label={i.more.name}>{i.more.text}</Link></>}</span>
          )}
        </li>
      ))}
    </ul>
  );
}

/** One bar split into parts with 2px surface gaps, and every part named with its count beside the bar. */
export function Split({ parts }: { parts: { label: string; value: number; color: string; note?: string }[] }) {
  const total = parts.reduce((a, p) => a + p.value, 0);
  if (!total) return null;
  return (
    <div>
      <div className="split-bar" role="img" aria-label={parts.map((p) => `${p.label} ${p.value}`).join(", ")}>
        {parts.filter((p) => p.value > 0).map((p) => <span key={p.label} style={{ flex: p.value, background: p.color }} title={`${p.label}: ${p.value}`} />)}
      </div>
      <ul className="legend vertical">
        {parts.map((p) => (
          <li key={p.label}>
            <Swatch color={p.color} /><span>{p.label}</span>
            <span className="mono muted" style={{ marginLeft: "auto" }}>{p.value} · {Math.round((100 * p.value) / total)}%</span>
            {p.note && <span className="tiny muted" style={{ flexBasis: "100%", paddingLeft: 16 }}>{p.note}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const hh = (h: number) => `${String(h).padStart(2, "0")}:00`;

/** Weekday by hour (IST), one sequential hue: darker means more requests. The caption under the grid names the cell you point at. */
export function Rhythm({ cells }: { cells: S["RhythmCell"][] }) {
  const [hover, setHover] = useState<{ dow: number; hour: number } | null>(null);
  const grid = new Map(cells.map((c) => [`${c.dow}-${c.hour}`, c.changes]));
  const max = Math.max(1, ...cells.map((c) => c.changes));
  const peak = cells.reduce<S["RhythmCell"] | null>((a, c) => (!a || c.changes > a.changes ? c : a), null);
  const byDow = DOW.map((_, d) => cells.filter((c) => c.dow === d).reduce((a, c) => a + c.changes, 0));
  const text = (d: number, h: number) => { const n = grid.get(`${d}-${h}`) ?? 0; return `${DOW[d]} ${hh(h)} · ${n} ${n === 1 ? "request" : "requests"}`; };
  const [asTable, setAsTable] = useState(false);
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: ".25rem" }}>
        <button type="button" className="btn ghost sm" aria-pressed={asTable} onClick={() => setAsTable(!asTable)}>{asTable ? "Chart" : "Table view"}</button>
      </div>
      {asTable ? (
        <div className="table-wrap" tabIndex={0} role="region" aria-label="Requests by weekday, as a table">
          <table className="data" aria-label="Requests by weekday">
            <thead><tr><th>Weekday</th><th className="num">Requests</th></tr></thead>
            <tbody>{DOW.map((d, i) => <tr key={d}><td>{d}</td><td className="num">{byDow[i]}</td></tr>)}</tbody>
          </table>
        </div>
      ) : (
        <>
          <div className="heat-wrap" tabIndex={0} role="region" aria-label="Requests by weekday and hour, scrollable">
            <div className="heat" role="img" aria-label={peak ? `Requests by weekday and hour. Busiest: ${text(peak.dow, peak.hour)}` : "Requests by weekday and hour"} onMouseLeave={() => setHover(null)}>
              {DOW.map((d, di) => (
                <div key={d} className="heat-row">
                  <span className="heat-label mono tiny muted">{d}</span>
                  {Array.from({ length: 24 }, (_, h) => {
                    const n = grid.get(`${di}-${h}`) ?? 0;
                    return <span key={h} className="heat-cell" onMouseEnter={() => setHover({ dow: di, hour: h })}
                      style={{ background: n ? `color-mix(in oklch, var(--magnitude) ${Math.round(18 + 82 * Math.sqrt(n / max))}%, var(--surface-2))` : undefined }} />;
                  })}
                </div>
              ))}
              <div className="heat-row heat-axis" aria-hidden="true">
                <span className="heat-label" />
                {[0, 6, 12, 18].map((h) => <span key={h} className="mono tiny muted" style={{ gridColumn: `${h + 2} / span 6` }}>{hh(h)}</span>)}
              </div>
            </div>
          </div>
          <p className="muted small" style={{ marginTop: 6 }} aria-live="polite" data-testid="rhythm-caption">
            {hover ? text(hover.dow, hover.hour) : peak ? `Busiest: ${text(peak.dow, peak.hour)}` : "No requests in this period."}
          </p>
        </>
      )}
    </div>
  );
}
