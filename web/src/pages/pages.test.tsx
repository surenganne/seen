import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { ids, state } from "../test/mock-api";
import { Audit } from "./Audit";
import { ChangeDetail } from "./ChangeDetail";
import { Changes } from "./Changes";
import { Overview } from "./Overview";
import { Projects } from "./Projects";
import { Provenance } from "./Provenance";
import { Sessions } from "./Sessions";
import { Settings } from "./Settings";
import { Skills } from "./Skills";
import { Timeline } from "./Timeline";

const { pid, cid } = ids;
type Case = { name: string; route: string; at: string; page: ReactElement; heading: RegExp; rows?: string };
const CASES: Case[] = [
  { name: "Projects", route: "/projects", at: "/projects", page: <Projects />, heading: /projects/i, rows: "project-card" },
  { name: "Overview", route: "/p/:pid", at: `/p/${pid}`, page: <Overview />, heading: /overview/i },
  { name: "Changes", route: "/p/:pid/changes", at: `/p/${pid}/changes`, page: <Changes />, heading: /changes/i, rows: "change-row" },
  { name: "Change detail", route: "/p/:pid/changes/:cid", at: `/p/${pid}/changes/${cid}`, page: <ChangeDetail />, heading: /\S/ },
  { name: "Sessions", route: "/p/:pid/sessions", at: `/p/${pid}/sessions`, page: <Sessions />, heading: /sessions/i, rows: "session-row" },
  { name: "Skills", route: "/p/:pid/skills", at: `/p/${pid}/skills`, page: <Skills />, heading: /skills/i, rows: "skill-row" },
  { name: "Audit", route: "/p/:pid/audit", at: `/p/${pid}/audit`, page: <Audit />, heading: /audit/i, rows: "audit-row" },
  { name: "Settings", route: "/settings", at: "/settings", page: <Settings />, heading: /settings/i },
  { name: "Timeline", route: "/p/:pid/timeline", at: `/p/${pid}/timeline`, page: <Timeline />, heading: /timeline/i, rows: "timeline-entry" },
  { name: "Provenance", route: "/p/:pid/provenance", at: `/p/${pid}/provenance?path=src/payments/charge.py`, page: <Provenance />, heading: /provenance/i, rows: "prov-block" },
];

const byName = (n: string) => CASES.find((c) => c.name === n)!; // not by index: adding or removing a page must not shift the others

function mount(c: Case) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[c.at]}>
        <Routes><Route path={c.route} element={c.page} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => { state.mode = "ok"; state.calls = []; state.replies = {}; });

describe.each(CASES)("$name page", (c) => {
  it("shows a heading, then its data from the API", async () => {
    mount(c);
    expect(screen.getByRole("status")).toBeInTheDocument(); // loading skeleton first
    expect(await screen.findByRole("heading", { level: 1, name: c.heading })).toBeInTheDocument();
    if (c.rows) expect((await screen.findAllByTestId(c.rows)).length).toBeGreaterThan(0);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("says so, as an alert, when the API is down", async () => {
    state.mode = "down";
    mount(c);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/\S/); // says what went wrong, not an empty box
    expect(screen.queryByRole("status")).not.toBeInTheDocument(); // and stops loading
  });

  it("renders with every list empty, without an alert", async () => {
    state.mode = "empty";
    mount(c);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    if (c.rows) expect(screen.queryAllByTestId(c.rows)).toHaveLength(0);
  });
});

describe("page details", () => {
  it("Overview shows the five summary tiles, each a link to its rows", async () => {
    mount(byName("Overview"));
    for (const t of ["Requests", "Code changed", "Cost", "Rules met", "PII exposure"]) {
      const tile = await screen.findByTestId(`tile-${t}`);
      expect(tile.querySelector("a.stat-link")).toHaveAttribute("href", expect.stringContaining(`/p/${pid}/`));
    }
  });
  it("Change detail shows the change panel", async () => {
    mount(byName("Change detail"));
    expect(await screen.findByTestId("change-detail")).toBeInTheDocument();
  });
  it("Settings shows the price table with its verified state", async () => {
    mount(byName("Settings"));
    expect(await screen.findByTestId("settings")).toBeInTheDocument();
    expect(screen.getByText(/unverified|verified/)).toBeInTheDocument();
  });

  describe("Provenance states", () => {
    const file = (status: number, body: unknown) => { state.replies["/provenance/file"] = { status, body }; };
    const at = (path: string) => ({ ...byName("Provenance"), at: `/p/${pid}/provenance${path}` });
    const base = { path: "a.bin", rev: "HEAD", counts: {}, blocks: [], truncated: false, reason: null };

    it("shows the instruction state with no path, and makes no file request", async () => {
      mount(at(""));
      expect(await screen.findByText(/choose a file/i)).toBeInTheDocument();
      expect(state.calls.some((c) => c.endsWith("/provenance/file"))).toBe(false);
    });
    it("counts and the limits, each block with a word for who", async () => {
      mount(byName("Provenance"));
      const count = await screen.findByTestId("prov-count");
      expect(count).toHaveTextContent(/agent/i);
      expect(count).toHaveTextContent(/not observed/i);
      expect(screen.getByText(/Not observed means Seen could not have seen it; it is not a claim that a person wrote it\./)).toBeInTheDocument();
      expect(screen.getByText(/edits made through Bash are not attributed/)).toBeInTheDocument();
      const blocks = await screen.findAllByTestId("prov-block");
      expect(blocks[0]).toHaveTextContent(/agent/i);
      expect(blocks[0]!.querySelector("a")).toHaveAttribute("href", expect.stringContaining("/changes/"));
      expect(screen.getByRole("region", { name: /line blocks/i })).toHaveAttribute("tabindex", "0");
    });
    it("Table view lists the same blocks in a table", async () => {
      mount(byName("Provenance"));
      const n = (await screen.findAllByTestId("prov-block")).length;
      screen.getByRole("button", { name: "Table view" }).click();
      expect(await screen.findAllByRole("row")).toHaveLength(n + 1);
    });
    it("a 404 is a calm note with the API's reason, not an alert", async () => {
      file(404, { detail: "not tracked by git" });
      mount(byName("Provenance"));
      expect(await screen.findByText(/not tracked by git/)).toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });
    it("a reason says no lines were attributed, with no counts", async () => {
      file(200, { ...base, reason: "binary file" });
      mount(byName("Provenance"));
      expect(await screen.findByText("No lines attributed: binary file")).toBeInTheDocument();
      expect(screen.queryByTestId("prov-count")).not.toBeInTheDocument();
    });
    it("a truncated result says it is partial", async () => {
      file(200, { ...base, counts: { agent: 1 }, truncated: true, blocks: [{ start: 1, end: 1, who: "agent", change_id: "c1", headline: "h", started_at: null, model: null, skills: [], pii_state: null }] });
      mount(byName("Provenance"));
      expect(await screen.findByText(/partial/i)).toBeInTheDocument();
    });
    it("a notebook is not line-attributed and is not fetched", async () => {
      mount(at("?path=x/n.ipynb"));
      expect(await screen.findByText(/notebook files are not line-attributed/i)).toBeInTheDocument();
      expect(state.calls.some((c) => c.endsWith("/provenance/file"))).toBe(false);
    });
  });
});
