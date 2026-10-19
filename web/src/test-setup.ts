import { cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { mockFetch } from "./test/mock-api";

// Installed before any module builds the API client, which captures fetch when it is created.
globalThis.fetch = mockFetch as typeof fetch;
// The client uses relative URLs (the page's own origin); Node's Request needs an absolute one.
const NativeRequest = globalThis.Request;
globalThis.Request = class extends NativeRequest {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    super(typeof input === "string" && input.startsWith("/") ? new URL(input, "http://localhost").href : input, init);
  }
} as typeof Request;
afterEach(cleanup); // vitest has no globals here, so Testing Library cannot register its own cleanup
