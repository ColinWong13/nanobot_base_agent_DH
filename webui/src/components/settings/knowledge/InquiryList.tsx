import { useState } from "react";
import { ChevronRight, MessageSquareQuote } from "lucide-react";
import { useTranslation } from "react-i18next";

import { PaperRow } from "@/components/settings/knowledge/PaperRow";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Chip } from "@/components/ui/chip";
import { DisclosureContent } from "@/components/ui/disclosure";
import type { KnowledgeInquiry, KnowledgePaper } from "@/lib/types";
import { cn } from "@/lib/utils";

/** The channels questions arrive on, named as the person would name them. */
const CHANNEL_LABEL: Record<string, string> = {
  feishu: "Feishu",
  weixin: "WeChat",
  websocket: "WebUI",
  cli: "CLI",
  telegram: "Telegram",
  discord: "Discord",
  slack: "Slack",
};

function channelLabel(channel: string | null, fallback: string): string {
  if (!channel) return fallback;
  return CHANNEL_LABEL[channel] ?? channel;
}

function day(iso: string | null): string {
  return iso ? iso.slice(0, 10) : "";
}

/**
 * What was asked, and what the vault looked like around then.
 *
 * Only sessions that actually *ran* the literature pipeline appear — the
 * gateway filters them, because the alternative is a page that lists "可以了"
 * and "不要" as explored interests.
 *
 * The papers shown against a question are **the day's additions, not that
 * question's harvest**. The link between a question and the cards it produced
 * is not recoverable: session transcripts truncate tool output, so a round that
 * wrote 80 cards reports 23 in one place and 48 in another with the middle
 * gone. Rather than print a number nobody could check, the page states the
 * library fact — "that day, this much entered the vault" — and says so.
 */
export function InquiryList({
  inquiries,
  papers,
}: {
  inquiries: KnowledgeInquiry[];
  papers: KnowledgePaper[];
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());

  if (inquiries.length === 0) {
    return (
      <Card>
        <CardContent className="flex items-start gap-3 py-6">
          <MessageSquareQuote className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
          <div className="flex flex-col gap-1">
            <p className="text-sm font-medium text-foreground">
              {t("settings.knowledge.inquiry.emptyTitle", {
                defaultValue: "No literature questions yet",
              })}
            </p>
            <p className="max-w-2xl text-xs leading-relaxed text-muted-foreground">
              {t("settings.knowledge.inquiry.emptyBody", {
                defaultValue:
                  "This fills in as you ask for literature — each conversation that ran the search pipeline shows up here with the questions you asked it.",
              })}
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }

  const byId = new Map(papers.map((paper) => [paper.id, paper]));

  return (
    <>
      {inquiries.map((inquiry) => {
        const isOpen = open.has(inquiry.key);
        const dayPapers = inquiry.library_that_day.papers
          .map((id) => byId.get(id))
          .filter((paper): paper is KnowledgePaper => paper !== undefined);
        const when = day(inquiry.updated_at) || day(inquiry.created_at);

        return (
          <Card key={inquiry.key}>
            <CardHeader className="gap-1">
              <div className="flex flex-wrap items-center gap-2">
                <Chip size="sm" variant="tonal">
                  {channelLabel(
                    inquiry.channel,
                    t("settings.knowledge.inquiry.otherChannel", { defaultValue: "Channel" }),
                  )}
                </Chip>
                {when ? (
                  <span className="text-xs tabular-nums text-muted-foreground">{when}</span>
                ) : null}
              </div>
              <CardTitle className="text-base">{inquiry.title}</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <ul className="flex flex-col gap-1.5 border-s-2 border-border ps-3">
                {inquiry.questions.map((question) => (
                  <li key={question} className="text-sm leading-relaxed text-foreground">
                    {question}
                  </li>
                ))}
              </ul>

              {dayPapers.length > 0 ? (
                <>
                  <button
                    type="button"
                    onClick={() =>
                      setOpen((current) => {
                        const next = new Set(current);
                        if (next.has(inquiry.key)) next.delete(inquiry.key);
                        else next.add(inquiry.key);
                        return next;
                      })
                    }
                    aria-expanded={isOpen}
                    aria-controls={`inquiry-day-${inquiry.key}`}
                    className="flex items-center gap-1.5 self-start rounded-md text-xs text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <ChevronRight
                      className={cn(
                        "h-3.5 w-3.5 transition-transform duration-200 motion-reduce:transition-none",
                        isOpen && "rotate-90",
                      )}
                      aria-hidden
                    />
                    {/* Worded as a fact about the library, never as "this
                        question collected these". */}
                    {t("settings.knowledge.inquiry.thatDay", {
                      defaultValue: "{{count}} paper(s) entered the vault that day",
                      count: dayPapers.length,
                    })}
                  </button>
                  <DisclosureContent id={`inquiry-day-${inquiry.key}`} open={isOpen}>
                    <ul className="divide-y divide-border border-t border-border">
                      {dayPapers.map((paper) => (
                        <PaperRow
                          key={paper.id}
                          paper={paper}
                          showThemes
                          showDomains
                        />
                      ))}
                    </ul>
                  </DisclosureContent>
                </>
              ) : null}
            </CardContent>
          </Card>
        );
      })}
    </>
  );
}
