import { useParams, useSearchParams } from "react-router-dom";
import type { Range } from "../api/hooks";

export function useRange(): [Range, (r: Range) => void] {
  const [sp, setSp] = useSearchParams();
  const raw = Number(sp.get("range"));
  const range: Range = raw === 14 || raw === 28 ? raw : 7;
  return [range, (r) => setSp((p) => { p.set("range", String(r)); return p; })];
}

export function usePid(): string {
  return useParams().pid ?? "";
}

/** Keep ?range across links. */
export function withRange(path: string, range: Range, extra?: Record<string, string>) {
  const q = new URLSearchParams({ range: String(range), ...extra });
  return `${path}?${q.toString()}`;
}
