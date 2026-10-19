import { describe, expect, it } from "vitest";
import { truncateWords } from "./format";

describe("truncateWords", () => {
  it("leaves short text alone and collapses whitespace", () => {
    expect(truncateWords("add   mul\n to calc", 240)).toBe("add mul to calc");
  });
  it("cuts at a word boundary, never mid-word, and says so", () => {
    expect(truncateWords("refactor the payment retry logic carefully", 30)).toBe("refactor the payment retry…");
  });
  it("hard-cuts a single very long token rather than returning nothing", () => {
    const out = truncateWords("x".repeat(500), 20);
    expect(out).toBe(`${"x".repeat(20)}…`);
  });
  it("drops trailing punctuation before the ellipsis", () => {
    expect(truncateWords("fix the bug, then ship it today", 13)).toBe("fix the bug…");
  });
});
