import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import userEvent from "@testing-library/user-event";
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
  it("Overview folders link to the Provenance file list, filtered by that folder", async () => {
    mount(byName("Overview"));
    const folder = (await screen.findAllByRole("link", { name: /^See files in / }))[0]!;
    expect(folder).toHaveAttribute("href", expect.stringMatching(new RegExp(`^/p/${pid}/provenance\\?.*q=`)));
  });
  it("Timeline area chips link to the Provenance file list, filtered by that area", async () => {
    mount(byName("Timeline"));
    const chip = (await screen.findAllByRole("link", { name: "Files in src/auth" }))[0]!;
    expect(chip).toHaveClass("tag");
    expect(chip).toHaveAttribute("href", expect.stringMatching(new RegExp(`^/p/${pid}/provenance\\?.*q=src%2Fauth`)));
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

    it("with no path the ranked file list is the page: rows, one instruction, no datalist, no file request", async () => {
      mount(at(""));
      const rows = await screen.findAllByTestId("prov-file-row");
      expect(rows.length).toBeGreaterThan(1);
      expect(screen.getByText("Pick a file to see which lines an agent wrote.")).toBeInTheDocument();
      expect(screen.getByRole("table", { name: /files agents changed/i })).toBeInTheDocument();
      expect(screen.getByRole("region", { name: /files agents changed/i })).toHaveAttribute("tabindex", "0");
      expect(screen.getByLabelText("Filter files")).toBeInTheDocument();
      expect(document.querySelector("datalist")).toBeNull();
      expect(document.querySelector("details")).toBeNull(); // the list is the page, not tucked away
      expect(state.calls.some((c) => c.endsWith("/provenance/file"))).toBe(false);
    });
    it("clicking a row opens that file's provenance", async () => {
      const u = userEvent.setup();
      mount(at(""));
      const rows = await screen.findAllByTestId("prov-file-row");
      await u.click(rows[1]!);
      await waitFor(() => expect(state.calls.some((c) => c.endsWith("/provenance/file"))).toBe(true));
      expect(await screen.findByTestId("prov-count")).toBeInTheDocument();
    });
    it("Enter on a row's button sets ?path= and the list closes into Choose another file", async () => {
      const u = userEvent.setup();
      mount(at("?q=charge"));
      const rows = await screen.findAllByTestId("prov-file-row");
      const btn = rows[0]!.querySelector("button")!;
      btn.focus();
      await u.keyboard("{Enter}");
      expect(await screen.findByTestId("prov-count")).toBeInTheDocument();
      const details = document.querySelector("details")!;
      expect(details).not.toHaveAttribute("open");
      expect(details.querySelector("summary")).toHaveTextContent(/^Choose another file/);
    });
    it("the selected file's row carries aria-current when the list is open", async () => {
      const u = userEvent.setup();
      mount(at("?path=src/auth/tokens.py"));
      await screen.findByTestId("prov-count");
      await u.click(screen.getByText(/^Choose another file/));
      const rows = await screen.findAllByTestId("prov-file-row");
      const cur = rows.filter((r) => r.getAttribute("aria-current") === "true");
      expect(cur).toHaveLength(1);
      expect(cur[0]).toHaveTextContent("src/auth/tokens.py");
    });
    it("sort and filter go to the API", async () => {
      const u = userEvent.setup();
      mount(at(""));
      await screen.findAllByTestId("prov-file-row");
      await u.click(screen.getByRole("button", { name: "Most requests" }));
      expect(screen.getByRole("button", { name: "Most requests" })).toHaveAttribute("aria-pressed", "true");
      await u.type(screen.getByLabelText("Filter files"), "charge{Enter}");
      await waitFor(() => expect(state.calls.filter((c) => c.endsWith("/provenance/files")).length).toBeGreaterThan(2));
    });
    it("the list states the day range, and the closed summary states the range and total", async () => {
      mount(at(""));
      expect(await screen.findByTestId("prov-range-note")).toHaveTextContent("Files changed by your requests in the last 7 days. Change the range in the top bar.");
      await screen.findAllByTestId("prov-file-row");
      mount(at("?path=src/auth/tokens.py&range=28"));
      expect(await screen.findByText(/Choose another file \(\d+ files, last 28 days\)/)).toBeInTheDocument();
      expect(screen.queryByTestId("prov-not-in-range")).not.toBeInTheDocument(); // tokens.py is in the list
    });
    it("a file that is not in the current list says so calmly and still shows its provenance", async () => {
      mount(at("?path=src/payments/charge.py"));
      expect(await screen.findByTestId("prov-not-in-range")).toHaveTextContent("src/payments/charge.py has no requests in the last 7 days");
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(await screen.findByTestId("prov-count")).toBeInTheDocument();
    });
    it("an empty list says what was checked and offers to clear the filter", async () => {
      state.replies["/provenance/files"] = { status: 200, body: { total: 0, page: 1, page_size: 50, items: [] } };
      mount(at("?q=zzz"));
      expect(await screen.findByText(/No files changed by requests in this period/)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /clear filter/i })).toBeInTheDocument();
    });
    it("API down shows the standard alert for the list", async () => {
      state.replies["/provenance/files"] = { status: 500, body: { detail: "the ledger is unavailable" } };
      mount(at(""));
      expect(await screen.findByRole("alert")).toHaveTextContent(/ledger is unavailable/);
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
      const toggle = screen.getByRole("button", { name: "Table view" });
      expect(toggle).toHaveAttribute("aria-pressed", "false");
      toggle.click();
      expect(await screen.findAllByRole("row")).toHaveLength(n + 1);
      expect(screen.getByRole("button", { name: "Table view" })).toHaveAttribute("aria-pressed", "true"); // name is stable; pressed says the table shows
      const names = screen.getAllByRole("link", { name: /^Open change/ }).map((a) => a.getAttribute("aria-label"));
      expect(new Set(names).size).toBe(names.length); // every link is distinguishable
      expect(screen.getAllByRole("region", { name: /line blocks/i })).toHaveLength(1); // one scroll region, not two nested
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
