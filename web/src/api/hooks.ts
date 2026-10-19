import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrap } from "./client";

export type Range = 7 | 14 | 28;

export interface ChangeFilters {
  tool?: string;
  status?: string;
  q?: string;
  file?: string;
  skill?: string;
  policy_missed?: boolean;
  mem?: "loaded" | "missed" | "none";
  pii?: boolean;
  days?: number;
  sort?: string;
  dir?: "asc" | "desc";
  session?: string;
  page?: number;
  page_size?: number;
}

export const useProjects = () =>
  useQuery({ queryKey: ["projects"], queryFn: () => unwrap(api.GET("/api/projects")) });

export const useOverview = (pid: string, range: Range) =>
  useQuery({
    queryKey: ["overview", pid, range],
    queryFn: () => unwrap(api.GET("/api/projects/{pid}/overview", { params: { path: { pid }, query: { range } } })),
    placeholderData: keepPreviousData,
  });

export const useChanges = (pid: string, f: ChangeFilters) =>
  useQuery({
    queryKey: ["changes", pid, f],
    queryFn: () => unwrap(api.GET("/api/projects/{pid}/changes", { params: { path: { pid }, query: f } })),
    placeholderData: keepPreviousData,
  });

export const useChange = (cid: string) =>
  useQuery({ queryKey: ["change", cid], queryFn: () => unwrap(api.GET("/api/changes/{cid}", { params: { path: { cid } } })) });

export const useSkills = (project: string | undefined, f: { kind?: string; status?: string; q?: string; unused?: boolean } = {}) =>
  useQuery({
    queryKey: ["skills", project, f],
    queryFn: () => unwrap(api.GET("/api/skills", { params: { query: { project, ...f } } })),
    placeholderData: keepPreviousData,
  });

export const useSkill = (sid: string | undefined, project: string | undefined) =>
  useQuery({
    queryKey: ["skill", sid, project],
    enabled: !!sid,
    queryFn: () => unwrap(api.GET("/api/skills/{sid}", { params: { path: { sid: sid ?? "" }, query: { project } } })),
  });

export const usePolicies = (pid: string) =>
  useQuery({ queryKey: ["policies", pid], queryFn: () => unwrap(api.GET("/api/projects/{pid}/policies", { params: { path: { pid } } })) });

export interface AuditFilters {
  type?: string;
  actor?: string;
  session?: string;
  from?: string;
  to?: string;
  q?: string;
  page?: number;
}

export const useAudit = (pid: string, f: AuditFilters) =>
  useQuery({
    queryKey: ["audit", pid, f],
    queryFn: () => unwrap(api.GET("/api/projects/{pid}/audit", { params: { path: { pid }, query: f } })),
    placeholderData: keepPreviousData,
  });

/** Polls so a running session's activity shows up without a reload. */
export const useSessions = (pid: string, page = 1, page_size = 50) =>
  useQuery({
    queryKey: ["sessions", pid, page, page_size],
    queryFn: () => unwrap(api.GET("/api/projects/{pid}/sessions", { params: { path: { pid }, query: { page, page_size } } })),
    refetchInterval: 10_000,
    placeholderData: keepPreviousData,
  });

export const useSessionActivity = (pid: string, session: string) =>
  useQuery({
    queryKey: ["audit", pid, { session }],
    queryFn: () => unwrap(api.GET("/api/projects/{pid}/audit", { params: { path: { pid }, query: { session } } })),
    refetchInterval: 10_000,
  });

export const useVerify = () => useQuery({ queryKey: ["verify"], queryFn: () => unwrap(api.GET("/api/audit/verify")) });

export const useSettings = () => useQuery({ queryKey: ["settings"], queryFn: () => unwrap(api.GET("/api/settings")) });

/** Invalidate everything after a write: the ledger is small and every page reads it. */
export function useWrite<TArgs, TOut>(fn: (a: TArgs) => Promise<TOut>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => qc.invalidateQueries() });
}

export const useMemory = (pid: string, f: { type?: string; status?: string; q?: string }) =>
  useQuery({
    queryKey: ["memory", pid, f],
    queryFn: () => unwrap(api.GET("/api/projects/{pid}/memory", { params: { path: { pid }, query: f } })),
    placeholderData: keepPreviousData,
  });
