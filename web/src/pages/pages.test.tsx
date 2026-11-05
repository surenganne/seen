import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { fireEvent } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ids, state, TEAM_PID } from "../test/mock-api";
import { Audit } from "./Audit";
import { ChangeDetail } from "./ChangeDetail";
import { Changes } from "./Changes";
import { Overview } from "./Overview";
import { Projects } from "./Projects";
import { Sessions } from "./Sessions";
import { Settings } from "./Settings";
import { Skills } from "./Skills";
import { Team } from "./Team";
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
  { name: "Team", route: "/team", at: "/team", page: <Team />, heading: /team/i, rows: "team-project-row" },
  { name: "Timeline", route: "/p/:pid/timeline", at: `/p/${pid}/timeline`, page: <Timeline />, heading: /timeline/i, rows: "timeline-entry" },
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

afterEach(() => { state.mode = "ok"; state.calls = []; state.team = {}; vi.useRealTimers(); });

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
});

describe("Team page", () => {
  const P = "/api/team/projects", M = `/api/team/projects/${TEAM_PID}/members`;
  const member = (id: string, at: string | null, expired = false) => ({ user_id: id, email: null, last_synced_at: at, changes: 1, key_expired: expired });

  it("renders the project rows and tiles for an ok state", async () => {
    mount(byName("Team"));
    expect(await screen.findAllByTestId("team-project-row")).toHaveLength(1);
    expect((await screen.findAllByTestId("team-tile")).length).toBeGreaterThan(0);
    expect(screen.queryByTestId("team-state")).not.toBeInTheDocument();
    expect(screen.getByText(/PII types and counts only, from machines where PII counts sync is on/)).toBeInTheDocument();
  });
  it("not_configured shows the reason and no table", async () => {
    state.team[P] = { state: "not_configured", reason: "Team sync is not configured.", projects: [] };
    state.team["/api/team/session"] = { state: "not_configured", email: null, role: null };
    mount(byName("Team"));
    expect(await screen.findByTestId("team-state")).toHaveTextContent(/sync\.server/);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByTestId("team-signin")).not.toBeInTheDocument();
  });
  it.each(["unauthorized", "forbidden", "unreachable", "bad_response"])("%s renders its reason", async (st) => {
    state.team[P] = { state: st, reason: `reason for ${st}`, projects: [] };
    mount(byName("Team"));
    expect(await screen.findByTestId("team-state")).toHaveTextContent(`reason for ${st}`);
    expect(screen.queryByTestId("team-project-row")).not.toBeInTheDocument();
  });
  it("renders a hostile project name and user id as text", async () => {
    state.team[P] = { state: "ok", reason: null, projects: [{ id: TEAM_PID, name: "<img src=x onerror=alert(1)>", changes: 1, cost_7d: 0, last_change_at: null }] };
    state.team[M] = { state: "ok", reason: null, members: [member("<b>x</b>", null)] };
    const { container } = mount(byName("Team"));
    expect((await screen.findAllByText("<img src=x onerror=alert(1)>")).length).toBeGreaterThan(0);
    expect(await screen.findByText("<b>x</b>")).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
  });
  it("labels each member Synced, Stale, Never synced, Key expired in order", async () => {
    vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-11-05T12:00:00Z") });
    state.team[M] = { state: "ok", reason: null, members: [
      member("a", "2026-11-05T11:00:00Z"), member("b", "2026-11-04T06:00:00Z"), member("c", null), member("d", "2026-11-05T11:00:00Z", true),
    ] };
    mount(byName("Team"));
    const rows = await screen.findAllByTestId("team-member-row");
    expect(rows.map((r) => /Synced|Stale|Never synced|Key expired/.exec(r.textContent ?? "")?.[0])).toEqual(["Synced", "Stale", "Never synced", "Key expired"]);
  });
  it("members forbidden shows one line and keeps the tiles", async () => {
    state.team[M] = { state: "forbidden", reason: "no", members: [] };
    mount(byName("Team"));
    expect(await screen.findByText("Only leads and admins can see who has synced.")).toBeInTheDocument();
    expect((await screen.findAllByTestId("team-tile")).length).toBeGreaterThan(0);
    expect(screen.queryByTestId("team-member-row")).not.toBeInTheDocument();
  });
  it("prefers email, falls back to user id", async () => {
    mount(byName("Team"));
    expect(await screen.findByText("dev@example.test")).toBeInTheDocument();
  });
  it("an empty project list says why, without an alert", async () => {
    state.mode = "empty";
    mount(byName("Team"));
    expect(await screen.findByText(/No projects are visible to this account/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
  it("shows who is signed in and signs out", async () => {
    mount(byName("Team"));
    expect(await screen.findByTestId("team-session")).toHaveTextContent("Signed in as lead@example.test (lead)");
    fireEvent.click(screen.getByTestId("team-signout"));
    await waitFor(() => expect(state.calls).toContain("/api/team/logout"));
  });
  it("signed out: Sign in with SSO starts the login", async () => {
    state.team["/api/team/session"] = { state: "signed_out", email: null, role: null };
    state.team[P] = { state: "login_required", reason: "Sign in to see the team.", projects: [] };
    state.team["/api/team/login"] = { url: null, reason: "unavailable" };
    mount(byName("Team"));
    fireEvent.click(await screen.findByTestId("team-signin"));
    expect(await screen.findByText("Sign-in is unavailable right now. Try again later.")).toBeInTheDocument();
    expect(state.calls).toContain("/api/team/login");
  });
  it("data ok while signed out shows no sign-in prompt", async () => {
    state.team["/api/team/session"] = { state: "signed_out", email: null, role: null };
    mount(byName("Team"));
    await screen.findAllByTestId("team-project-row");
    expect(screen.queryByTestId("team-signin")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
