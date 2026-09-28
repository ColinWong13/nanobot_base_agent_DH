import { useCallback, useMemo, useState } from "react";
import { ChevronRight, Loader2, RefreshCw, Search, TriangleAlert } from "lucide-react";
import { useTranslation } from "react-i18next";

import { InquiryList } from "@/components/settings/knowledge/InquiryList";
import { PaperRow } from "@/components/settings/knowledge/PaperRow";
import { useKnowledgeIndex } from "@/components/settings/knowledge/useKnowledgeIndex";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Chip } from "@/components/ui/chip";
import { DisclosureContent } from "@/components/ui/disclosure";
import { Input } from "@/components/ui/input";
import { SegmentedControl } from "@/components/ui/segmented-control";
import type { KnowledgeIndex, KnowledgePaper } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * The knowledge the vault has accumulated, browsed four ways.
 *
 * The four dimensions are the four questions someone actually has about their
 * own reading: *what disciplines have I collected* (学科), *what arguments have
 * I organised this into* (主题), *what came in recently* (时间), and *what did I
 * ask that led here* (提问). They are all views over one set of cards — the page
 * holds one index and regroups it, so the dimensions cannot drift apart.
 *
 * **主题 leads the tabs, and it is not the order the request listed them in.**
 * That is a deliberate call about today's data: the vault holds one discipline
 * (`ai`), so 学科 renders as a single undifferentiated list of everything, while
 * 主题 is the axis the review actually gave structure to. The tab order should
 * be revisited when a second discipline exists.
 */

type Dimension = "topic" | "domain" | "time" | "inquiry";

interface Group {
  key: string;
  title: string;
  /** The long form, or where the papers came from. Shown only when it adds. */
  subtitle?: string;
  papers: KnowledgePaper[];
}

/** Papers are matched against the one search box on the title, the one-liner
 * and the identifier — the three things a person half-remembers. */
function matches(paper: KnowledgePaper, query: string): boolean {
  if (!query) return true;
  const needle = query.toLowerCase();
  return (
    paper.title.toLowerCase().includes(needle) ||
    paper.one_liner.toLowerCase().includes(needle) ||
    paper.id.toLowerCase().includes(needle) ||
    (paper.venue ?? "").toLowerCase().includes(needle) ||
    paper.topic_terms.some((term) => term.toLowerCase().includes(needle))
  );
}

function topicGroups(index: KnowledgeIndex, papers: KnowledgePaper[]): Group[] {
  const groups: Group[] = index.topics.map((topic) => ({
    key: `topic:${topic.term}`,
    title: topic.term,
    // The review's heading is the argument; the short term is only a label.
    // Shown only when they differ, so a review that never shortened a heading
    // does not repeat itself.
    subtitle: topic.title === topic.term ? undefined : topic.title,
    papers: papers.filter((paper) => paper.topic_terms.includes(topic.term)),
  }));
  const unclassified = papers.filter((paper) => paper.topic_terms.length === 0);
  if (unclassified.length) {
    groups.push({
      key: "topic:none",
      title: "",
      subtitle: "",
      papers: unclassified,
    });
  }
  return groups;
}

function domainGroups(index: KnowledgeIndex, papers: KnowledgePaper[]): Group[] {
  const groups: Group[] = index.domains.map((domain) => ({
    key: `domain:${domain.id}`,
    title: domain.label,
    subtitle: domain.label === domain.id ? undefined : domain.id,
    papers: papers.filter((paper) => paper.domains.includes(domain.id)),
  }));
  const unclassified = papers.filter((paper) => paper.domains.length === 0);
  if (unclassified.length) {
    groups.push({ key: "domain:none", title: "", papers: unclassified });
  }
  return groups;
}

function timeGroups(papers: KnowledgePaper[]): Group[] {
  const byDate = new Map<string, KnowledgePaper[]>();
  for (const paper of papers) {
    const day = paper.added ?? "";
    const bucket = byDate.get(day);
    if (bucket) bucket.push(paper);
    else byDate.set(day, [paper]);
  }
  // Descending by date string, which is ISO: the newest day is the one someone
  // opening this page wants. The empty key sorts last and means "no date".
  return Array.from(byDate.entries())
    .sort(([a], [b]) => (a < b ? 1 : a > b ? -1 : 0))
    .map(([day, bucket]) => ({
      key: `time:${day || "none"}`,
      title: day,
      papers: bucket,
    }));
}

export function KnowledgePage() {
  const { t } = useTranslation();
  const { index, loading, missing, error, reload } = useKnowledgeIndex();
  const [dimension, setDimension] = useState<Dimension>("topic");
  const [query, setQuery] = useState("");
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());

  const toggle = useCallback((key: string) => {
    setCollapsed((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const papers = index?.papers ?? [];
  const visible = useMemo(
    () => papers.filter((paper) => matches(paper, query)),
    [papers, query],
  );

  const groups = useMemo(() => {
    if (!index) return [];
    if (dimension === "topic") return topicGroups(index, visible);
    if (dimension === "domain") return domainGroups(index, visible);
    return timeGroups(visible);
  }, [dimension, index, visible]);

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
            {/* The gateway's own message names the path and the command that
                creates it, so it is shown rather than paraphrased. */}
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

  return (
    <div className="settings-stack">
      <Card>
        <CardHeader>
          <CardTitle>
            {t("settings.knowledge.title", { defaultValue: "Accumulated knowledge" })}
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-wrap gap-2">
            <Chip variant="filled">
              {t("settings.knowledge.countPapers", {
                defaultValue: "{{count}} papers",
                count: index.counts.papers,
              })}
            </Chip>
            <Chip variant="tonal">
              {t("settings.knowledge.countTopics", {
                defaultValue: "{{count}} themes",
                count: index.counts.topics,
              })}
            </Chip>
            <Chip variant="tonal">
              {t("settings.knowledge.countDomains", {
                defaultValue: "{{count}} disciplines",
                count: index.counts.domains,
              })}
            </Chip>
            <Chip variant="outline">
              {t("settings.knowledge.countReviews", {
                defaultValue: "{{count}} reviews",
                count: index.counts.reviews,
              })}
            </Chip>
          </div>

          {/* A card the gateway could not parse is named here rather than
              dropped: a page that quietly shows 80 of 81 papers is wrong in a
              way the reader has no way to notice. */}
          {index.counts.skipped > 0 ? (
            <p className="flex items-start gap-2 text-xs text-muted-foreground">
              <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
              {t("settings.knowledge.skipped", {
                defaultValue:
                  "{{count}} file(s) could not be read and are not counted: {{names}}",
                count: index.counts.skipped,
                names: index.skipped.map((entry) => entry.path).join(", "),
              })}
            </p>
          ) : null}

          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <div className="relative min-w-0 flex-1">
              <Search
                className="pointer-events-none absolute start-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
                aria-hidden
              />
              <Input
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                aria-label={t("settings.knowledge.search", { defaultValue: "Search the vault" })}
                placeholder={t("settings.knowledge.search", { defaultValue: "Search the vault" })}
                className="ps-11"
              />
            </div>
            <SegmentedControl
              value={dimension}
              onChange={(value) => setDimension(value as Dimension)}
              ariaLabel={t("settings.knowledge.dimension", { defaultValue: "Browse by" })}
              options={[
                { value: "topic", label: t("settings.knowledge.byTopic", { defaultValue: "Theme" }) },
                { value: "domain", label: t("settings.knowledge.byDomain", { defaultValue: "Discipline" }) },
                { value: "time", label: t("settings.knowledge.byTime", { defaultValue: "Time" }) },
                { value: "inquiry", label: t("settings.knowledge.byInquiry", { defaultValue: "Questions" }) },
              ]}
            />
          </div>
        </CardContent>
      </Card>

      {dimension === "inquiry" ? (
        <InquiryList inquiries={index.inquiries} papers={index.papers} />
      ) : groups.length === 0 ? (
        <p className="px-3 py-12 text-center text-sm text-muted-foreground">
          {t("settings.knowledge.empty", { defaultValue: "Nothing in the vault matches." })}
        </p>
      ) : (
        groups.map((group) => (
          <GroupCard
            key={group.key}
            group={group}
            index={index}
            open={!collapsed.has(group.key)}
            onToggle={() => toggle(group.key)}
            showThemes={dimension !== "topic"}
            showDomains={dimension !== "domain"}
          />
        ))
      )}
    </div>
  );
}

function GroupCard({
  group,
  index,
  open,
  onToggle,
  showThemes,
  showDomains,
}: {
  group: Group;
  index: KnowledgeIndex;
  open: boolean;
  onToggle: () => void;
  showThemes: boolean;
  showDomains: boolean;
}) {
  const { t } = useTranslation();
  const review = index.reviews.find((entry) => entry.themes.some((theme) => theme.term === group.title));

  return (
    <Card>
      <CardHeader className="gap-1">
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          aria-controls={`knowledge-group-${group.key}`}
          className="flex w-full items-start gap-2 rounded-md text-start focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <ChevronRight
            className={cn(
              "mt-0.5 h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-200 motion-reduce:transition-none",
              open && "rotate-90",
            )}
            aria-hidden
          />
          <span className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-2 gap-y-1">
            <CardTitle className="text-base">
              {group.title || t("settings.knowledge.unclassified", { defaultValue: "Unclassified" })}
            </CardTitle>
            <Chip size="sm" variant="tonal">
              {group.papers.length}
            </Chip>
            {group.subtitle ? (
              <span className="text-xs text-muted-foreground">{group.subtitle}</span>
            ) : null}
            {review ? (
              <span className="text-xs text-muted-foreground">
                {t("settings.knowledge.fromReview", {
                  defaultValue: "{{topic}}",
                  topic: review.topic,
                })}
              </span>
            ) : null}
          </span>
        </button>
      </CardHeader>
      <DisclosureContent id={`knowledge-group-${group.key}`} open={open}>
        <CardContent>
          <ul className="divide-y divide-border">
            {group.papers.map((paper) => (
              <PaperRow
                key={paper.id}
                paper={paper}
                showThemes={showThemes}
                showDomains={showDomains}
              />
            ))}
          </ul>
        </CardContent>
      </DisclosureContent>
    </Card>
  );
}
