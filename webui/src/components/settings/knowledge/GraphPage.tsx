import { useEffect, useMemo, useRef, useState } from "react";
import cytoscape from "cytoscape";
import fcose, { type FcoseLayoutOptions } from "cytoscape-fcose";
import { Loader2, RefreshCw, TriangleAlert } from "lucide-react";
import { useTranslation } from "react-i18next";

import { buildElements, type NodeKind } from "@/components/settings/knowledge/graphElements";
import { PaperRow } from "@/components/settings/knowledge/PaperRow";
import { useKnowledgeIndex } from "@/components/settings/knowledge/useKnowledgeIndex";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Chip } from "@/components/ui/chip";
import type { KnowledgePaper } from "@/lib/types";

/**
 * The vault as a graph: disciplines, the themes read out of them, and the
 * papers under each theme.
 *
 * **Papers are nodes here, and that is a deliberate departure.** The graph
 * membership principle elsewhere in this project says only topic pages and
 * concept notes earn a node — papers are material, not structure — and on an
 * *authored* wiki that is right. This vault is not authored, it is harvested:
 * there are no topic pages to point at, and a theme with 24 papers under it is
 * only legible if you can see which 24. So the paper nodes are the material and
 * the themes are the structure, which is the same shape, drawn one level
 * deeper. The toggle collapses it back to the principle when the papers are
 * just noise.
 *
 * The graph is derived in the browser rather than sent by the gateway. Edges
 * are a pure function of the facts the index already carries (a card names its
 * themes and its discipline), so shipping them would be a second representation
 * of one dataset, kept in step by hand. Building them lives in
 * `graphElements.ts`, one file over, so the rules can be tested without a
 * canvas.
 *
 * This module is the only place cytoscape is imported, and it is reached only
 * through `LazyGraphPage`.
 */

/** Above this many papers the initial layout is slow enough to feel broken. */
const PAPER_NODE_WARN = 400;

interface Selection {
  kind: NodeKind;
  label: string;
  /** Papers behind the node — one for a paper, many for a theme or discipline. */
  papers: KnowledgePaper[];
}

cytoscape.use(fcose);

export function GraphPage() {
  const { t } = useTranslation();
  const { index, loading, missing, error, reload } = useKnowledgeIndex();
  const [showPapers, setShowPapers] = useState(true);
  const [selected, setSelected] = useState<Selection | null>(null);
  const container = useRef<HTMLDivElement>(null);

  const elements = useMemo(
    () => (index ? buildElements(index, showPapers) : []),
    [index, showPapers],
  );

  useEffect(() => {
    if (!container.current || elements.length === 0) return;
    // Built as a typed value, not an inline literal: that is what lets fcose's
    // parameters through cytoscape's closed `LayoutOptions` union uncast.
    const layout: FcoseLayoutOptions = {
      name: "fcose",
      animate: false,
      nodeSeparation: 90,
      idealEdgeLength: 90,
      // A harvested vault is one clump of papers under one discipline; without
      // some gravity the disconnected pieces drift to the edges and the shape
      // is unreadable.
      gravity: 0.35,
      packComponents: true,
    };
    const cy = cytoscape({
      container: container.current,
      elements,
      wheelSensitivity: 0.2,
      style: [
        {
          selector: "node",
          style: {
            "background-color": "var(--muted)",
            label: "data(label)",
            color: "var(--muted-foreground)",
            "font-size": 9,
            "text-wrap": "ellipsis",
            "text-max-width": "110px",
            "text-valign": "bottom",
            "text-margin-y": 4,
            width: "data(size)",
            height: "data(size)",
            "border-width": 1,
            "border-color": "var(--border)",
          },
        },
        {
          selector: 'node[kind = "domain"]',
          style: {
            "background-color": "var(--tertiary)",
            "background-opacity": 0.18,
            "border-color": "var(--tertiary)",
            color: "var(--foreground)",
            "font-size": 13,
            "font-weight": 600,
            "text-max-width": "160px",
            width: "data(size)",
            height: "data(size)",
          },
        },
        {
          selector: 'node[kind = "topic"]',
          style: {
            "background-color": "var(--secondary)",
            color: "var(--foreground)",
            "font-size": 11,
            "font-weight": 500,
          },
        },
        {
          selector: "node:selected",
          style: { "border-width": 3, "border-color": "var(--ring)" },
        },
        {
          selector: "edge",
          style: {
            width: 1,
            "line-color": "var(--border)",
            "curve-style": "bezier",
            "target-arrow-shape": "none",
          },
        },
      ],
      layout,
    });

    cy.on("tap", "node", (event) => {
      const node = event.target;
      const kind = node.data("kind") as NodeKind;
      if (!index) return;
      const id = String(node.id());
      if (kind === "paper") {
        const paper = index.papers.find((candidate) => candidate.id === id.slice("paper:".length));
        if (paper) setSelected({ kind, label: paper.title, papers: [paper] });
        return;
      }
      if (kind === "topic") {
        const term = id.slice("topic:".length);
        setSelected({
          kind,
          label: node.data("label"),
          papers: index.papers.filter((paper) => paper.topic_terms.includes(term)),
        });
        return;
      }
      const domain = id.slice("domain:".length);
      const entry = index.domains.find((candidate) => candidate.id === domain);
      setSelected({
        kind,
        label: entry?.label ?? domain,
        papers: index.papers.filter((paper) => paper.domains.includes(domain)),
      });
    });
    cy.on("tap", (event) => {
      if (event.target === cy) setSelected(null);
    });

    return () => cy.destroy();
    // `elements` is the whole input; rebuilding on it is what keeps the canvas
    // and the toggle in step.
  }, [elements, index]);

  if (loading && !index) {
    return (
      <div className="settings-stack">
        <div className="flex items-center gap-3 px-3 py-12 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden />
          {t("settings.knowledge.loading", { defaultValue: "Reading the vault…" })}
        </div>
      </div>
    );
  }

  if (!index) {
    return (
      <div className="settings-stack">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <TriangleAlert className="h-4 w-4 text-muted-foreground" aria-hidden />
              {missing
                ? t("settings.knowledge.missingTitle", {
                    defaultValue: "No literature vault yet",
                  })
                : t("settings.knowledge.errorTitle", {
                    defaultValue: "Could not read the vault",
                  })}
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <p className="text-sm text-muted-foreground">{error}</p>
            <div>
              <Button type="button" variant="outline" onClick={reload} className="rounded-pill">
                <RefreshCw className="mr-1.5 h-3.5 w-3.5" aria-hidden />
                {t("settings.knowledge.retry", { defaultValue: "Retry" })}
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  const busy = index.counts.papers > PAPER_NODE_WARN && showPapers;

  return (
    <div className="settings-stack">
      <Card>
        <CardHeader className="gap-2">
          <CardTitle>{t("settings.knowledge.graphTitle", { defaultValue: "Knowledge graph" })}</CardTitle>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              variant={showPapers ? "default" : "outline"}
              size="sm"
              aria-pressed={showPapers}
              onClick={() => setShowPapers((value) => !value)}
              className="h-8 rounded-pill px-3 text-xs"
            >
              {t("settings.knowledge.graph.showPapers", { defaultValue: "Show papers" })}
            </Button>
            <Chip size="sm" variant="outline">
              {t("settings.knowledge.graph.nodeCount", {
                defaultValue: "{{count}} nodes",
                count: elements.filter((element) => !("source" in (element.data as object))).length,
              })}
            </Chip>
            <span className="text-xs text-muted-foreground">
              {t("settings.knowledge.graph.hint", {
                defaultValue: "Scroll to zoom, drag to pan, click a node for its papers.",
              })}
            </span>
          </div>
        </CardHeader>
      </Card>

      {busy ? (
        <p className="flex items-center gap-2 px-3 text-xs text-muted-foreground">
          <TriangleAlert className="h-3.5 w-3.5 shrink-0" aria-hidden />
          {t("settings.knowledge.graph.tooMany", {
            defaultValue:
              "{{count}} papers is a lot of nodes; turn papers off to see the shape of the themes first.",
            count: index.counts.papers,
          })}
        </p>
      ) : null}

      <div className="flex flex-col gap-3 lg:flex-row">
        <div
          ref={container}
          role="application"
          aria-label={t("settings.knowledge.graphTitle", { defaultValue: "Knowledge graph" })}
          className="h-[60vh] min-h-[420px] flex-1 overflow-hidden rounded-lg border border-border bg-card"
        />
        {selected ? (
          <Card className="lg:w-96 lg:shrink-0">
            <CardHeader className="gap-1">
              <div className="flex items-center gap-2">
                <Chip size="sm" variant="tonal">
                  {t(`settings.knowledge.graph.kind.${selected.kind}`, {
                    defaultValue: selected.kind,
                  })}
                </Chip>
                <span className="text-xs text-muted-foreground">
                  {t("settings.knowledge.graph.paperCount", {
                    defaultValue: "{{count}} papers",
                    count: selected.papers.length,
                  })}
                </span>
              </div>
              <CardTitle className="text-base">{selected.label}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="max-h-[48vh] overflow-y-auto">
                <ul className="divide-y divide-border">
                  {selected.papers.map((paper) => (
                    <PaperRow key={paper.id} paper={paper} showThemes showDomains />
                  ))}
                </ul>
              </div>
            </CardContent>
          </Card>
        ) : null}
      </div>
    </div>
  );
}
