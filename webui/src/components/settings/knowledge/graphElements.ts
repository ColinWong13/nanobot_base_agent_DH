import type cytoscape from "cytoscape";

import type { KnowledgeIndex } from "@/lib/types";

/**
 * Turning the vault index into graph elements.
 *
 * Kept apart from the page and free of any cytoscape import at runtime — the
 * shapes below are its only dependency, and they are types — so the rules that
 * decide what connects to what can be tested without a canvas.
 *
 * Three node kinds and three edge kinds:
 *
 *   discipline -- theme     one per (discipline, theme) pair the cards imply
 *   theme      -- paper     one per card that a theme claims
 *   discipline -- paper     only for cards no theme claimed
 *
 * The last one exists so that nothing floats. An unclaimed card is a gap in the
 * review, and a gap is exactly what the graph should make visible — but an
 * isolated dot in the middle of nowhere reads as a rendering glitch, not as a
 * finding. Anchoring it to its discipline puts it somewhere legible.
 */

export type NodeKind = "domain" | "topic" | "paper";

/**
 * How big to draw a node. Count carries weight, so a theme with 24 papers reads
 * as heavier than one with 9 before any label is read.
 *
 * Computed while building rather than adjusted on the instance afterwards:
 * cytoscape maps `width: "data(size)"` against node data, so a size that
 * arrives late is a size the first layout never saw.
 */
export function nodeSize(kind: NodeKind, count: number): number {
  if (kind === "paper") return 5;
  const base = kind === "domain" ? 34 : 16;
  return base + Math.sqrt(Math.max(count, 1)) * 2;
}

export function buildElements(
  index: KnowledgeIndex,
  showPapers: boolean,
): cytoscape.ElementDefinition[] {
  const elements: cytoscape.ElementDefinition[] = [];
  const seenTopics = new Set<string>();
  const seenDomains = new Set<string>();
  const seenEdges = new Set<string>();

  /**
   * Every edge is pushed through here, and the id is the pair it connects.
   *
   * That dedupe is not a nicety: the natural way to write the loops below emits
   * one discipline->theme edge per *card*, so a vault where 81 cards share one
   * discipline would send cytoscape 81 elements all called `domain:ai->topic:x`.
   * cytoscape requires element ids to be unique and drops the repeats with a
   * console warning, so the graph would survive — quietly wrong, and noisy.
   */
  const pushEdge = (source: string, target: string): void => {
    const id = `${source}->${target}`;
    if (seenEdges.has(id)) return;
    seenEdges.add(id);
    elements.push({ data: { id, source, target } });
  };

  for (const paper of index.papers) {
    if (showPapers) {
      elements.push({
        data: {
          id: `paper:${paper.id}`,
          kind: "paper" satisfies NodeKind,
          label: paper.title,
          size: nodeSize("paper", 1),
        },
      });
    }

    for (const domain of paper.domains) {
      if (seenDomains.has(domain)) continue;
      seenDomains.add(domain);
      const entry = index.domains.find((candidate) => candidate.id === domain);
      const count = entry?.count ?? 0;
      elements.push({
        data: {
          id: `domain:${domain}`,
          kind: "domain" satisfies NodeKind,
          label: entry?.label ?? domain,
          count,
          size: nodeSize("domain", count),
        },
      });
    }

    for (const term of paper.topic_terms) {
      if (!seenTopics.has(term)) {
        seenTopics.add(term);
        const entry = index.topics.find((candidate) => candidate.term === term);
        const count = entry?.count ?? 0;
        elements.push({
          data: {
            id: `topic:${term}`,
            kind: "topic" satisfies NodeKind,
            label: term,
            count,
            size: nodeSize("topic", count),
            // The review's full heading, for the inspector only — it is far too
            // long to draw inside a node.
            heading: entry?.title ?? term,
          },
        });
      }
      for (const domain of paper.domains) {
        pushEdge(`domain:${domain}`, `topic:${term}`);
      }
      if (showPapers) {
        pushEdge(`topic:${term}`, `paper:${paper.id}`);
      }
    }

    if (showPapers && paper.topic_terms.length === 0) {
      for (const domain of paper.domains) {
        pushEdge(`domain:${domain}`, `paper:${paper.id}`);
      }
    }
  }

  return elements;
}
