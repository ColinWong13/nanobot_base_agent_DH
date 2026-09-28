import { describe, expect, it } from "vitest";

import { buildElements, nodeSize } from "@/components/settings/knowledge/graphElements";
import type { KnowledgeIndex, KnowledgePaper } from "@/lib/types";

/**
 * The graph's edge rules.
 *
 * These are asserted rather than left to the page because the failure they
 * guard against is silent: a vault whose cards lost their themes still renders
 * — as a cloud of disconnected dots. The plan's acceptance test is literally
 * "连线而非孤点", so that is what is checked here.
 */

function paper(overrides: Partial<KnowledgePaper> & { id: string }): KnowledgePaper {
  return {
    title: overrides.id,
    year: 2026,
    venue: null,
    venue_tier: null,
    status: null,
    topics: [],
    topic_terms: [],
    domains: ["ai"],
    added: "2026-09-01",
    updated: null,
    one_liner: "",
    url: null,
    path: `20-Papers/${overrides.id}.md`,
    ...overrides,
  };
}

function index(papers: KnowledgePaper[], topics: KnowledgeIndex["topics"] = []): KnowledgeIndex {
  return {
    version: 1,
    vault: "/vault",
    workspace: "/workspace",
    fingerprint: "f",
    papers,
    topics,
    domains: [{ id: "ai", label: "人工智能 / AI", count: papers.length }],
    reviews: [],
    weekly: [],
    skipped: [],
    counts: {
      papers: papers.length,
      topics: topics.length,
      domains: 1,
      reviews: 0,
      weekly: 0,
      skipped: 0,
    },
    inquiries: [],
  };
}

const isNode = (element: { data: unknown }) => !("source" in (element.data as object));
const isEdge = (element: { data: unknown }) => "source" in (element.data as object);
const idOf = (element: { data: unknown }) => String((element.data as { id: string }).id);

describe("buildElements", () => {
  it("connects a themed card to its theme and its discipline", () => {
    const elements = buildElements(
      index([paper({ id: "p1", topic_terms: ["图结构 RAG"] })], [
        { term: "图结构 RAG", title: "Graph-structured RAG", review: "slr-rag", count: 1 },
      ]),
      true,
    );

    expect(elements.filter(isEdge).map(idOf).sort()).toEqual([
      "domain:ai->topic:图结构 RAG",
      "topic:图结构 RAG->paper:p1",
    ]);
  });

  it("leaves no node unconnected, even when no theme claimed a card", () => {
    const elements = buildElements(index([paper({ id: "p1" })]), true);

    expect(elements.filter(isNode)).toHaveLength(2); // the paper and its discipline
    expect(elements.filter(isEdge).map(idOf)).toEqual(["domain:ai->paper:p1"]);
  });

  it("anchors an unthemed card even when other cards are themed", () => {
    const elements = buildElements(
      index(
        [paper({ id: "themed", topic_terms: ["t"] }), paper({ id: "stray" })],
        [{ term: "t", title: "T", review: null, count: 1 }],
      ),
      true,
    );

    expect(elements.filter(isEdge).map(idOf)).toContain("domain:ai->paper:stray");
  });

  it("draws a theme once no matter how many cards carry it", () => {
    const elements = buildElements(
      index(
        [paper({ id: "a", topic_terms: ["t"] }), paper({ id: "b", topic_terms: ["t"] })],
        [{ term: "t", title: "T", review: null, count: 2 }],
      ),
      true,
    );

    expect(elements.filter(isNode).filter((e) => idOf(e) === "topic:t")).toHaveLength(1);
    // But each card gets its own edge, which is the whole point of the dimension.
    expect(elements.filter(isEdge).map(idOf)).toContain("topic:t->paper:a");
    expect(elements.filter(isEdge).map(idOf)).toContain("topic:t->paper:b");
  });

  it("draws a discipline once no matter how many cards name it", () => {
    const elements = buildElements(
      index([paper({ id: "a", topic_terms: ["t"] }), paper({ id: "b", topic_terms: ["t"] })], [
        { term: "t", title: "T", review: null, count: 2 },
      ]),
      true,
    );

    expect(elements.filter(isNode).filter((e) => idOf(e) === "domain:ai")).toHaveLength(1);
    // One discipline-theme edge, not one per card.
    expect(elements.filter(isEdge).map(idOf)).toEqual([
      "domain:ai->topic:t",
      "topic:t->paper:a",
      "topic:t->paper:b",
    ]);
  });

  it("draws one discipline-theme edge per discipline a card belongs to", () => {
    const twoDomains: KnowledgeIndex = {
      ...index([paper({ id: "p", topic_terms: ["t"], domains: ["ai", "finance"] })]),
      domains: [
        { id: "ai", label: "AI", count: 1 },
        { id: "finance", label: "Finance", count: 1 },
      ],
    };

    const elements = buildElements(twoDomains, true);
    expect(elements.filter(isEdge).map(idOf)).toEqual([
      "domain:ai->topic:t",
      "domain:finance->topic:t",
      "topic:t->paper:p",
    ]);
    expect(elements.filter(isNode).map(idOf).sort()).toEqual([
      "domain:ai",
      "domain:finance",
      "paper:p",
      "topic:t",
    ]);
  });

  it("keeps a card in both themes when a review claimed it twice", () => {
    // Two of the real vault's cards are genuinely claimed by two themes; that is
    // a real membership, not a pairing error, and the graph must show both.
    const elements = buildElements(
      index(
        [paper({ id: "p", topic_terms: ["a", "b"] })],
        [
          { term: "a", title: "A", review: null, count: 1 },
          { term: "b", title: "B", review: null, count: 1 },
        ],
      ),
      true,
    );

    const edges = elements.filter(isEdge).map(idOf);
    expect(edges).toContain("topic:a->paper:p");
    expect(edges).toContain("topic:b->paper:p");
  });

  it("drops paper nodes but keeps the themes when papers are hidden", () => {
    const elements = buildElements(
      index(
        [paper({ id: "p", topic_terms: ["t"] })],
        [{ term: "t", title: "T", review: null, count: 1 }],
      ),
      false,
    );

    expect(elements.filter(isNode).map(idOf).sort()).toEqual(["domain:ai", "topic:t"]);
    expect(elements.filter(isEdge).map(idOf)).toEqual(["domain:ai->topic:t"]);
  });

  it("has no orphan paper edge when papers are hidden", () => {
    const elements = buildElements(index([paper({ id: "stray" })]), false);

    // The discipline stays; there is nothing left for it to connect to, which
    // is why the graph is a theme view rather than an empty canvas.
    expect(elements.filter(isNode).map(idOf)).toEqual(["domain:ai"]);
    expect(elements.filter(isEdge)).toHaveLength(0);
  });

  it("names a discipline node from the registry, falling back to its id", () => {
    const known = buildElements(index([paper({ id: "p" })]), true);
    expect(known.find((e) => idOf(e) === "domain:ai")?.data).toMatchObject({
      label: "人工智能 / AI",
    });

    const unknown: KnowledgeIndex = { ...index([paper({ id: "p", domains: ["ghost"] })]) };
    const fallback = buildElements(unknown, true);
    expect(fallback.find((e) => idOf(e) === "domain:ghost")?.data).toMatchObject({
      label: "ghost",
    });
  });

  it("carries the review's heading on a theme node, not just its term", () => {
    const elements = buildElements(
      index([paper({ id: "p", topic_terms: ["图结构 RAG"] })], [
        { term: "图结构 RAG", title: "图结构增强的检索与推理", review: "slr-rag", count: 1 },
      ]),
      true,
    );

    expect(elements.find((e) => idOf(e) === "topic:图结构 RAG")?.data).toMatchObject({
      label: "图结构 RAG",
      heading: "图结构增强的检索与推理",
    });
  });

  it("sizes a theme by its count", () => {
    const elements = buildElements(
      index([paper({ id: "p", topic_terms: ["t"] })], [
        { term: "t", title: "T", review: null, count: 25 },
      ]),
      true,
    );

    const size = (elements.find((e) => idOf(e) === "topic:t")?.data as { size: number }).size;
    expect(size).toBe(nodeSize("topic", 25));
    expect(size).toBeGreaterThan(nodeSize("topic", 1));
  });

  it("gives an empty vault an empty graph rather than a stray node", () => {
    expect(buildElements(index([]), true)).toEqual([]);
  });
});
