import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { S } from "../api/client";
import { day, money } from "../lib/format";

/** Fixed categorical order: color follows the tool, never its rank (dataviz rule). */
const TOOL_ORDER = ["claude-code", "codex", "cursor"];
const toolColor = (tool: string) => `var(--series-${Math.min(TOOL_ORDER.indexOf(tool) + 1 || 3, 3)})`;
const toolName: Record<string, string> = { "claude-code": "Claude Code", codex: "Codex", cursor: "Cursor" };

const axis = { stroke: "var(--ink-3)", fontSize: 11, fontFamily: "var(--font-mono)" };

function ChartTip({ active, payload, label }: { active?: boolean; payload?: { name: string; value: number; color: string }[]; label?: string }) {
  if (!active || !payload?.length) return null;
  const total = payload.reduce((a, p) => a + (p.value || 0), 0);
  return (
    <div className="chart-tip">
      <div className="label">{label ? day(label) : ""}</div>
      {payload.map((p) => (
        <div key={p.name} style={{ display: "flex", gap: ".5rem", alignItems: "center" }}>
          <span style={{ width: 8, height: 8, borderRadius: 2, background: p.color }} aria-hidden="true" />
          <span>{p.name}</span>
          <span className="mono" style={{ marginLeft: "auto", paddingLeft: 12 }}>{money(p.value)}</span>
        </div>
      ))}
      {payload.length > 1 && <div className="mono" style={{ borderTop: "1px solid var(--border)", marginTop: 4, paddingTop: 4 }}>Total {money(total)}</div>}
    </div>
  );
}

export function CostChart({ days }: { days: S["DayCost"][] }) {
  const [asTable, setAsTable] = useState(false);
  const tools = Array.from(new Set(days.flatMap((d) => Object.keys(d.by_tool)))).sort(
    (a, b) => (TOOL_ORDER.indexOf(a) + 99) % 100 - (TOOL_ORDER.indexOf(b) + 99) % 100,
  );
  const rows = days.map((d) => ({ date: d.date, ...d.by_tool }));
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: ".25rem" }}>
        <button type="button" className="btn ghost sm" aria-pressed={asTable} onClick={() => setAsTable(!asTable)}>
          {asTable ? "Chart" : "Table view"}
        </button>
      </div>
      {asTable ? (
        <div className="table-wrap" tabIndex={0} role="region" aria-label="Cost per day, as a table">
          <table className="data" aria-label="Cost per day">
            <thead><tr><th>Day</th>{tools.map((t) => <th key={t} className="num">{toolName[t] ?? t}</th>)}</tr></thead>
            <tbody>
              {days.map((d) => (
                <tr key={d.date}><td>{day(d.date)}</td>{tools.map((t) => <td key={t} className="num">{money(d.by_tool[t] ?? 0)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div style={{ height: 220 }} role="img" aria-label="API-equivalent cost per day, stacked by tool">
          <ResponsiveContainer>
            <BarChart data={rows} margin={{ top: 8, right: 4, left: -8, bottom: 0 }} barCategoryGap="22%">
              <CartesianGrid vertical={false} stroke="var(--grid)" />
              <XAxis dataKey="date" tickFormatter={day} tick={axis} tickLine={false} axisLine={{ stroke: "var(--border-strong)" }} minTickGap={14} />
              <YAxis tickFormatter={(v: number) => `$${v.toFixed(v >= 10 ? 0 : 2)}`} tick={axis} tickLine={false} axisLine={false} width={48} />
              <Tooltip content={<ChartTip />} cursor={{ fill: "var(--surface-2)" }} />
              {tools.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
              {tools.map((t, i) => (
                <Bar key={t} dataKey={t} name={toolName[t] ?? t} stackId="cost" fill={toolColor(t)} stroke="var(--surface)" strokeWidth={2}
                  radius={i === tools.length - 1 ? [4, 4, 0, 0] : 0} maxBarSize={28} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

/** Single-hue horizontal magnitude bars with direct value labels (no legend needed for one series). */
export function MagnitudeBars({ items, unit = "" }: { items: { label: string; value: number; sub?: string }[]; unit?: string }) {
  const max = Math.max(1, ...items.map((i) => i.value));
  return (
    <ul className="bars">
      {items.map((i) => (
        <li key={i.label}>
          <span className="mono">{i.label}</span>
          <span className="meter" aria-hidden="true"><span style={{ width: `${(i.value / max) * 100}%` }} /></span>
          <span className="mono" title={i.sub}>{i.value.toLocaleString()}{unit}</span>
          {i.sub && <span className="tiny muted bars-sub">{i.sub}</span>}
        </li>
      ))}
    </ul>
  );
}
