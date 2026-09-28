import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { KnowledgePage } from "@/components/settings/knowledge/KnowledgePage";
import { ApiError } from "@/lib/api";
import type { KnowledgeIndex, KnowledgePaper } from "@/lib/types";

/**
 * The browse page, from the payload to the screen.
 *
 * `tests/webui/test_vault_index.py` covers what the vault actually contains and
 * `knowledge-graph-elements.test.ts` covers what connects to what; this file is
 * only about the page turning one payload into four browsable dimensions. The
 * interesting failures here are the quiet ones — a card dropped from a group
 * because nothing claimed it, a filter that searches the wrong fields, a
 * dimension that renders the previous dimension's grouping.
 */

const fetchKnowledge = vi.fn();

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, fetchKnowledge: (...args: unknown[]) => fetchKnowledge(...args) };
});

// `getToken` must keep one identity across renders: the hook's effect depends on
// it, and the real provider memoises it with `useCallback(..., [])`. A fresh
// arrow per render would re-run the fetch forever, and the test would be
// measuring a loop that cannot happen in the app.
vi.mock("@/providers/ClientProvider", () => {
  const getToken = () => "test-token";
  return { useClient: () => ({ getToken }) };
});

afterEach(cleanup);
// Braces, not a bare arrow: `mockReset()` returns the mock, and vitest treats a
// function returned from `beforeEach` as teardown. It would call the mock after
// the test, and a rejection test's mock rejects when called — an unhandled
// rejection blamed on whichever test just ran.
beforeEach(() => {
  fetchKnowledge.mockReset();
});

function paper(overrides: Partial<KnowledgePaper> & { id: string; title: string }): KnowledgePaper {
  return {
    year: 2026,
    venue: null,
    venue_tier: null,
    status: null,
    topics: [],
    topic_terms: [],
    domains: ["ai"],
    added: "2026-09-20",
    updated: null,
    one_liner: "",
    url: null,
    path: `10-Papers/${overrides.id}.md`,
    ...overrides,
  };
}

function payload(overrides: Partial<KnowledgeIndex> = {}): KnowledgeIndex {
  return {
    version: 1,
    vault: "/vault",
    workspace: "/workspace",
    fingerprint: "fp",
    papers: [],
    topics: [],
    domains: [{ id: "ai", label: "人工智能 / AI", count: 0 }],
    reviews: [],
    weekly: [],
    skipped: [],
    counts: { papers: 0, topics: 0, domains: 1, reviews: 0, weekly: 0, skipped: 0 },
    inquiries: [],
    ...overrides,
  };
}

/** Render and wait for the fetch to land, so no assertion runs against the spinner. */
async function renderPage(index: KnowledgeIndex) {
  fetchKnowledge.mockResolvedValue(index);
  render(<KnowledgePage />);
  await waitFor(() => expect(screen.queryByText("Reading the vault…")).toBeNull());
}

const TWO_THEMES = payload({
  papers: [
    paper({ id: "g1", title: "Graph paper", topic_terms: ["图结构 RAG"] }),
    paper({ id: "a1", title: "Agentic paper", topic_terms: ["自适应与 Agentic RAG"] }),
    paper({ id: "x1", title: "Unclaimed paper" }),
  ],
  topics: [
    { term: "图结构 RAG", title: "图结构增强的检索与推理", review: "slr-rag", count: 1 },
    { term: "自适应与 Agentic RAG", title: "自适应与 Agentic RAG", review: "slr-rag", count: 1 },
  ],
  counts: { papers: 3, topics: 2, domains: 1, reviews: 1, weekly: 0, skipped: 0 },
});

describe("KnowledgePage", () => {
  it("groups by theme and keeps an unclaimed card visible", async () => {
    await renderPage(TWO_THEMES);

    expect(screen.getByText("Graph paper")).toBeVisible();
    expect(screen.getByText("Agentic paper")).toBeVisible();
    // The card no theme claimed still has to be somewhere; dropping it would
    // make the page quietly disagree with the vault.
    expect(screen.getByText("Unclassified")).toBeVisible();
    expect(screen.getByText("Unclaimed paper")).toBeVisible();
  });

  it("shows the review's long heading under a short theme name, but not when they match", async () => {
    await renderPage(TWO_THEMES);

    expect(screen.getByText("图结构增强的检索与推理")).toBeVisible();
    // The second theme's heading is its own term, so repeating it would be noise.
    expect(screen.queryByText("自适应与 Agentic RAG", { selector: "span.text-xs" })).toBeNull();
  });

  it("filters within the dimension rather than across all of them", async () => {
    await renderPage(TWO_THEMES);

    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "Graph" } });

    expect(screen.getByText("Graph paper")).toBeVisible();
    expect(screen.queryByText("Agentic paper")).toBeNull();
    expect(screen.queryByText("Unclaimed paper")).toBeNull();
  });

  it("searches the one-liner and the identifier, not just the title", async () => {
    await renderPage(
      payload({
        papers: [
          paper({ id: "2609.1", title: "Alpha", one_liner: "a study of retrieval" }),
          paper({ id: "2609.2", title: "Beta", one_liner: "unrelated" }),
        ],
      }),
    );

    const box = screen.getByRole("searchbox");
    fireEvent.change(box, { target: { value: "retrieval" } });
    expect(screen.getByText("Alpha")).toBeVisible();
    expect(screen.queryByText("Beta")).toBeNull();

    fireEvent.change(box, { target: { value: "2609.2" } });
    expect(screen.getByText("Beta")).toBeVisible();
    expect(screen.queryByText("Alpha")).toBeNull();
  });

  it("regroups when the dimension changes", async () => {
    await renderPage(TWO_THEMES);

    fireEvent.click(screen.getByRole("button", { name: "Discipline" }));
    expect(screen.getByText("人工智能 / AI")).toBeVisible();
    // Every card is in this one discipline, so all three are here.
    expect(screen.getByText("Graph paper")).toBeVisible();
    expect(screen.getByText("Unclaimed paper")).toBeVisible();
  });

  it("groups by the day a card arrived, newest first", async () => {
    await renderPage(
      payload({
        papers: [
          paper({ id: "old", title: "Older", added: "2026-09-01" }),
          paper({ id: "new", title: "Newer", added: "2026-09-27" }),
        ],
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: "Time" }));

    const headings = screen.getAllByText(/^2026-09-\d\d$/).map((node) => node.textContent);
    expect(headings).toEqual(["2026-09-27", "2026-09-01"]);
  });

  it("switches to the questions dimension and shows an empty state when there are none", async () => {
    await renderPage(TWO_THEMES);

    fireEvent.click(screen.getByRole("button", { name: "Questions" }));

    expect(screen.getByText("No literature questions yet")).toBeVisible();
    // The theme groups must be gone, not merely hidden behind the tab.
    expect(screen.queryByText("Graph paper")).toBeNull();
  });

  it("shows what was asked, with the day's additions as a library fact", async () => {
    await renderPage(
      payload({
        papers: [paper({ id: "g1", title: "Graph paper", added: "2026-09-20" })],
        inquiries: [
          {
            key: "websocket:c1",
            channel: "feishu",
            title: "RAG survey",
            created_at: "2026-09-20T10:00:00Z",
            updated_at: "2026-09-20T11:00:00Z",
            questions: ["我想看 RAG 最新进展"],
            library_that_day: { date: "2026-09-20", papers: ["g1"] },
          },
        ],
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: "Questions" }));

    expect(screen.getByText("我想看 RAG 最新进展")).toBeVisible();
    expect(screen.getByText("Feishu")).toBeVisible();

    // Worded as a fact about the library, never as "this question collected these".
    const toggle = screen.getByRole("button", { name: /entered the vault that day/ });
    expect(toggle).toHaveTextContent("1 paper(s) entered the vault that day");
    fireEvent.click(toggle);
    expect(screen.getByText("Graph paper")).toBeVisible();
  });

  it("names a card the gateway could not parse instead of hiding it", async () => {
    await renderPage(
      payload({
        skipped: [{ path: "10-Papers/broken.md", reason: "bad frontmatter" }],
        counts: { papers: 0, topics: 0, domains: 1, reviews: 0, weekly: 0, skipped: 1 },
      }),
    );

    const warning = screen.getByText(/could not be read and are not counted/);
    expect(warning).toBeVisible();
    expect(warning).toHaveTextContent("10-Papers/broken.md");
  });

  it("shows the gateway's own message for a missing vault, not a paraphrase", async () => {
    fetchKnowledge.mockRejectedValue(
      new ApiError(404, "no literature workspace at /w; create one with paperctl.py vault-init"),
    );
    render(<KnowledgePage />);

    await waitFor(() => expect(screen.getByText("No literature vault yet")).toBeVisible());
    // The path and the command come from the gateway, so the page cannot drift
    // out of step with what actually creates a vault.
    expect(screen.getByText(/paperctl\.py vault-init/)).toBeVisible();
  });

  it("treats an unreadable vault as a failure rather than an empty one", async () => {
    fetchKnowledge.mockRejectedValue(new ApiError(500, "failed to read the Obsidian vault"));
    render(<KnowledgePage />);

    await waitFor(() => expect(screen.getByText("Could not read the vault")).toBeVisible());
    // "Nothing in the vault matches" would be a lie about a vault that exists.
    expect(screen.queryByText(/No literature vault yet/)).toBeNull();
  });

  it("retries on demand and paints the retry's answer", async () => {
    fetchKnowledge.mockRejectedValueOnce(new ApiError(500, "failed to read the Obsidian vault"));
    render(<KnowledgePage />);
    await waitFor(() => expect(screen.getByText("Could not read the vault")).toBeVisible());

    fetchKnowledge.mockResolvedValue(TWO_THEMES);
    fireEvent.click(screen.getByRole("button", { name: /Retry/ }));

    await waitFor(() => expect(screen.getByText("Graph paper")).toBeVisible());
    expect(fetchKnowledge).toHaveBeenCalledTimes(2);
  });

  it("counts what it is showing", async () => {
    await renderPage(TWO_THEMES);

    expect(screen.getByText("3 papers")).toBeVisible();
    expect(screen.getByText("2 themes")).toBeVisible();
    expect(screen.getByText("1 disciplines")).toBeVisible();
  });

  it("collapses and reopens a group", async () => {
    await renderPage(TWO_THEMES);

    const toggle = screen.getByRole("button", { name: /图结构 RAG/ });
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });
});
