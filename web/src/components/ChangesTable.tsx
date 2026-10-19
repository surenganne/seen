import { ArrowDown, ArrowUp, ArrowUpDown, Inbox } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import type { S } from "../api/client";
import { money, tokens, when } from "../lib/format";
import { useRange, withRange } from "../lib/nav";
import { Badge, Empty, GitStatus, PiiChip } from "./ui";

type Sort = { sort: string; dir: "asc" | "desc"; onSort?: (s: string) => void };

function Th({ id, label, num, s }: { id?: string; label: string; num?: boolean; s?: Sort }) {
  if (!id || !s?.onSort) return <th className={num ? "num" : ""}>{label}</th>;
  const active = s.sort === id;
  const I = active ? (s.dir === "asc" ? ArrowUp : ArrowDown) : ArrowUpDown;
  return (
    <th className={num ? "num" : ""} aria-sort={active ? (s.dir === "asc" ? "ascending" : "descending") : "none"}>
      <button type="button" onClick={() => s.onSort?.(id)}>
        {label} <I aria-hidden="true" />
      </button>
    </th>
  );
}

export function ChangesTable({ rows, pid, sort, compact }: { rows: S["ChangeRow"][]; pid: string; sort?: Sort; compact?: boolean }) {
  const nav = useNavigate();
  const [range] = useRange();
  if (!rows.length) {
    return <Empty icon={Inbox} title="No changes match">Widen the date range or clear a filter. New agent turns appear here after each Stop.</Empty>;
  }
  const open = (id: string) => nav(withRange(`/p/${pid}/changes/${id}`, range));
  return (
    <div className="table-wrap" tabIndex={0} role="region" aria-label="Changes">
      <table className="data" data-testid="changes-table">
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
            <tr key={c.id} className="clickable" onClick={() => open(c.id)} data-testid="change-row">
              <td className="when">{when(c.started_at)}<div className="tiny">#{c.seq}</div></td>
              <td style={{ minWidth: 240 }}>
                <div className="title clamp-2" data-testid="change-request">
                  <Link className="rowbtn" to={withRange(`/p/${pid}/changes/${c.id}`, range)} onClick={(e) => e.stopPropagation()}>
                    {c.request ?? c.summary ?? <span className="muted">(no request text stored)</span>}
                  </Link>
                </div>
                {c.request && c.summary && <div className="meta clamp-2">{c.summary}</div>}
                <div className="meta mono">{c.background && <span className="tag" title="A plugin's background session (Agent SDK)">background</span>}{c.model ?? "—"}{c.skills.length ? ` · ${c.skills.join(", ")}` : ""}</div>
              </td>
              {!compact && <td className="num">{c.files.length}</td>}
              <td className="num"><span className="plus">+{c.added}</span> <span className="minus">−{c.removed}</span></td>
              {!compact && <td className="num">{tokens(c.tokens)}</td>}
              <td className="num">{money(c.cost_usd)}</td>
              {!compact && <td><GitStatus status={c.git_status} /></td>}
              <td>
                <div className="checks">
                  {c.mem_state === "missed" && <Badge tone="critical">no memory</Badge>}
                  {c.policy_missed && <Badge tone="warning">policy missed</Badge>}
                  {c.unapproved_skill && <Badge tone="warning">unapproved skill</Badge>}
                  {c.pii_count > 0 && <PiiChip count={c.pii_count} high={c.pii_high} />}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
