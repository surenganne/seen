import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export type S = components["schemas"];

// X-Seen-Request: the server refuses state-changing calls without it (CSRF / DNS rebinding guard).
export const api = createClient<paths>({ baseUrl: "", headers: { "X-Seen-Request": "1" } });

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function unwrap<T>(p: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const { data, error, response } = await p;
  if (error !== undefined || data === undefined) {
    const detail = (error as { detail?: unknown } | undefined)?.detail;
    throw new ApiError(response.status, typeof detail === "string" ? detail : `Request failed (${response.status})`);
  }
  return data;
}
