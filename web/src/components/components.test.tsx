import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { S } from "../api/client";
import { ChangesTable } from "./ChangesTable";
import { Eyes, lens, lidAt } from "./Eyes";
import { PiiChip, SkillStatus } from "./ui";
import { day, money, when } from "../lib/format";

const row = (over: Partial<S["ChangeRow"]> = {}): S["ChangeRow"] => ({
  id: "ch_1", seq: 1, session_id: "s", started_at: "2026-10-18T10:00:00Z", summary: "Did a thing", model: "claude-sonnet-5-5",
  tool: "claude-code", files: ["a.py"], added: 3, removed: 1, tokens: 1000, cost_usd: 0.12, git_status: "committed",
  mem_state: "loaded", skills: ["tdd"], policy_missed: false, pii_state: "none", pii_count: 0, pii_high: false, unapproved_skill: false,
  ...over,
});

describe("Eyes", () => {
  it("renders idle and alert states with accessible labels", () => {
    const { rerender } = render(<Eyes />);
    expect(screen.getByRole("img", { name: "Seen" })).toHaveAttribute("data-state", "idle");
    rerender(<Eyes state="alert" />);
    expect(screen.getByRole("img", { name: /needs attention/i })).toHaveAttribute("data-state", "alert");
  });
  it("blinks shut and back open within 275 ms", () => {
    expect(lidAt(-1)).toBe(1);
    expect(lidAt(0)).toBe(1);
    expect(lidAt(90)).toBe(0);
    expect(lidAt(150)).toBeGreaterThan(0);
    expect(lidAt(150)).toBeLessThan(1);
    expect(lidAt(275)).toBe(1);
  });
  it("lids are an almond around the eye centre that grows with openness", () => {
    expect(lens(18, 1)).toBe("M2,25 Q18,-3.3999999999999986 34,25 Q18,53.4 2,25 Z");
    expect(lens(18, 0.5)).toContain("Q18,10.8 ");
  });
});

describe("PII chip", () => {
  it("never shows a bare clean label", () => {
    render(<PiiChip count={0} />);
    expect(screen.queryByText(/clean/i)).toBeNull();
    expect(screen.getByText("none found")).toHaveAttribute("title", expect.stringMatching(/not detected/));
  });
  it("marks high-confidence findings critical", () => {
    render(<PiiChip count={4} high />);
    expect(screen.getByText("PII ×4").closest(".badge")).toHaveClass("critical");
  });
});

describe("status badges carry an icon and a label, never color alone", () => {
  it.each(["approved", "changed", "unreviewed", "blocked"])("%s", (st) => {
    render(<SkillStatus status={st} />);
    const b = screen.getByText(st).closest(".badge")!;
    expect(b.querySelector("svg[aria-hidden]")).not.toBeNull();
  });
});

describe("ChangesTable", () => {
  it("shows checks and navigates on Enter", async () => {
    render(
      <MemoryRouter initialEntries={["/p/x/changes?range=7"]}>
        <Routes>
          <Route path="/p/:pid/changes" element={<ChangesTable pid="x" rows={[row({ mem_state: "missed", policy_missed: true, pii_count: 2, pii_high: true })]} />} />
          <Route path="/p/:pid/changes/:cid" element={<div>detail page</div>} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText("no memory")).toBeInTheDocument();
    expect(screen.getByText("policy missed")).toBeInTheDocument();
    screen.getByTestId("change-row").focus();
    await userEvent.keyboard("{Enter}");
    expect(screen.getByText("detail page")).toBeInTheDocument();
  });
  it("says so when nothing matches", () => {
    render(<MemoryRouter><ChangesTable pid="x" rows={[]} /></MemoryRouter>);
    expect(screen.getByText("No changes match")).toBeInTheDocument();
  });
});

describe("format", () => {
  it("shows IST and money", () => {
    expect(when("2026-10-18T20:00:00Z")).toMatch(/19 Oct/);
    expect(day("2026-10-18")).toMatch(/18 Oct/);
    expect(money(12.5)).toBe("$12.50");
    expect(money(0.1234)).toBe("$0.1234");
  });
});
