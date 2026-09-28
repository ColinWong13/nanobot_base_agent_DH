import { ExternalLink } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Chip } from "@/components/ui/chip";
import type { KnowledgePaper } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * The tier chips borrow the registry page's scale, so a rank reads the same
 * way wherever it appears. `tertiary` is MD3's role for an accent that must not
 * read as a primary action, which is exactly what a top mark is.
 */
const TIER_VARIANT: Record<string, "filled" | "tonal" | "outline" | "tertiary"> = {
  "A*": "tertiary",
  A: "filled",
  B: "tonal",
  C: "outline",
};

interface PaperRowProps {
  paper: KnowledgePaper;
  /** Hidden where the heading above already says it -- a theme chip repeated
   * down a list of papers that all share that theme is noise, not information. */
  showThemes?: boolean;
  showDomains?: boolean;
  className?: string;
}

/**
 * One paper card, as the browse page lists it.
 *
 * Deliberately quiet: a vault of 81 cards is read by scanning, so the title is
 * the only thing at full contrast and everything else — year, rank, themes —
 * is metadata the eye can skip until it wants it.
 */
export function PaperRow({
  paper,
  showThemes = false,
  showDomains = false,
  className,
}: PaperRowProps) {
  const { t } = useTranslation();
  const tier = paper.venue_tier ? TIER_VARIANT[paper.venue_tier] ?? "outline" : null;

  return (
    <li className={cn("flex flex-col gap-1 py-2.5", className)}>
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        {paper.url ? (
          <a
            href={paper.url}
            target="_blank"
            rel="noreferrer noopener"
            className="group inline-flex items-baseline gap-1 text-sm font-medium text-foreground underline-offset-4 hover:underline focus-visible:rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {paper.title}
            <ExternalLink
              className="h-3 w-3 shrink-0 translate-y-px text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100 motion-reduce:transition-none"
              aria-hidden
            />
          </a>
        ) : (
          <span className="text-sm font-medium text-foreground">{paper.title}</span>
        )}
        {paper.year ? (
          <span className="text-xs tabular-nums text-muted-foreground">{paper.year}</span>
        ) : null}
        {paper.venue ? (
          <Chip size="sm" variant={tier ?? "outline"}>
            {paper.venue}
            {paper.venue_tier ? ` · ${paper.venue_tier}` : ""}
          </Chip>
        ) : null}
        {paper.status && paper.status !== "unread" ? (
          <span className="text-xs text-muted-foreground">
            {t(`settings.knowledge.status.${paper.status}`, { defaultValue: paper.status })}
          </span>
        ) : null}
      </div>

      {paper.one_liner ? (
        <p className="max-w-3xl text-xs leading-relaxed text-muted-foreground">
          {paper.one_liner}
        </p>
      ) : null}

      {(showThemes && paper.topic_terms.length > 0) ||
      (showDomains && paper.domains.length > 0) ? (
        <div className="mt-0.5 flex flex-wrap gap-1.5">
          {showThemes
            ? paper.topic_terms.map((term) => (
                <Chip key={`t:${term}`} size="sm" variant="tonal">
                  {term}
                </Chip>
              ))
            : null}
          {showDomains
            ? paper.domains.map((domain) => (
                <Chip key={`d:${domain}`} size="sm" variant="outline">
                  {domain}
                </Chip>
              ))
            : null}
        </div>
      ) : null}
    </li>
  );
}
