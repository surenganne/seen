import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { ids, state } from "../test/mock-api";
import { Audit } from "./Audit";
import { ChangeDetail } from "./ChangeDetail";
import { Changes } from "./Changes";
import { Memory } from "./Memory";
import { Overview } from "./Overview";
import { Projects } from "./Projects";
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
  { name: "Memory", route: "/p/:pid/memory", at: `/p/${pid}/memory`, page: <Memory />, heading: /memory/i },
  { name: "Skills", route: "/p/:pid/skills", at: `/p/${pid}/skills`, page: <Skills />, heading: /skills/i, rows: "skill-row" },
  { name: "Audit", route: "/p/:pid/audit", at: `/p/${pid}/audit`, page: <Audit />, heading: /audit/i, rows: "audit-row" },
  { name: "Settings", route: "/settings", at: "/settings", page: <Settings />, heading: /settings/i },
  { name: "Timeline", route: "/p/:pid/timeline", at: `/p/${pid}/timeline`, page: <Timeline />, heading: /timeline/i, rows: "timeline-entry" },
];

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

afterEach(() => { state.mode = "ok"; state.calls = []; });

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
  it("Overview shows the six summary tiles, each a link to its rows", async () => {
    mount(CASES[1]!);
    for (const t of ["Changes", "Cost", "Tokens", "Memory loaded", "Policy missed", "Changes with PII exposure"]) {
      const tile = await screen.findByTestId(`tile-${t}`);
      expect(tile.querySelector("a.stat-link")).toHaveAttribute("href", expect.stringContaining(`/p/${pid}/changes`));
    }
  });
  it("Change detail shows the change panel", async () => {
    mount(CASES[3]!);
    expect(await screen.findByTestId("change-detail")).toBeInTheDocument();
  });
  it("Settings shows the price table with its verified state", async () => {
    mount(CASES[8]!);
    expect(await screen.findByTestId("settings")).toBeInTheDocument();
    expect(screen.getByText(/unverified|verified/)).toBeInTheDocument();
  });
});
