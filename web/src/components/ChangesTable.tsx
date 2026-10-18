import { useNavigate } from "react-router-dom";
import type { S } from "../api/client";
import { money, tokens, when } from "../lib/format";
import { useRange, withRange } from "../lib/nav";
import { Badge, GitStatus, PiiChip } from "./ui";

type Sort = { sort: string; dir: "asc" | "desc"; onSort?: (s: string) => void };

function Th({ id, label, num, s }: { id?: string; label: string; num?: boolean; s?: Sort }) {
  if (!id || !s?.onSort) return <th className={num ? "num" : ""}>{label}</th>;
  const active = s.sort === id;
  return (
    <th className={num ? "num" : ""} aria-sort={active ? (s.dir === "asc" ? "ascending" : "descending") : "none"}>
      <button type="button" onClick={() => s.onSort?.(id)}>
        {label} <span aria-hidden="true">{active ? (s.dir === "asc" ? "↑" : "↓") : "↕"}</span>
      </button>
    </th>
  );
}

export function ChangesTable({ rows, pid, sort, compact }: { rows: S["ChangeRow"][]; pid: string; sort?: Sort; compact?: boolean }) {
  const nav = useNavigate();
  const [range] = useRange();
  if (!rows.length) return <div className="empty">No changes match.</div>;
  return (
    <div className="table-wrap">
      <table className="ledger" data-testid="changes-table">
        <thead>
          <tr>
            <Th id="time" label="When" s={sort} />
            <th>Change</th>
            {!compact && <Th id="files" label="Files" num s={sort} />}
            <Th id="lines" label="Lines" num s={sort} />
            {!compact && <Th id="tokens" label="Tokens" num s={sort} />}
            <Th id="cost" label="Cost" num s={sort} />
            {!compact && <th>Git</th>}
            <th>Checks</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => (
            <tr
              key={c.id}
              tabIndex={0}
              onClick={() => nav(withRange(`/p/${pid}/changes/${c.id}`, range))}
              onKeyDown={(e) => e.key === "Enter" && nav(withRange(`/p/${pid}/changes/${c.id}`, range))}
              data-testid="change-row"
            >
              <td className="seq">{when(c.started_at)}<br />#{c.seq}</td>
              <td style={{ minWidth: 220 }}>
                <div style={{ fontWeight: 500 }}>{c.summary ?? <span className="muted">(no summary)</span>}</div>
                <div className="muted mono" style={{ fontSize: ".76rem" }}>
                  {c.model ?? "—"}{c.skills.length ? ` · ${c.skills.join(", ")}` : ""}
                </div>
              </td>
              {!compact && <td className="num">{c.files.length}</td>}
              <td className="num"><span className="plus">+{c.added}</span> <span className="minus">−{c.removed}</span></td>
              {!compact && <td className="num">{tokens(c.tokens)}</td>}
              <td className="num">{money(c.cost_usd)}</td>
              {!compact && <td><GitStatus status={c.git_status} /></td>}
              <td><div className="checks">
                {c.mem_state === "missed" && <Badge tone="critical">no memory</Badge>}
                {c.policy_missed && <Badge tone="warning">policy missed</Badge>}
                {c.unapproved_skill && <Badge tone="warning">unapproved skill</Badge>}
                {c.pii_count > 0 && <PiiChip count={c.pii_count} high={c.pii_high} />}
              </div></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
