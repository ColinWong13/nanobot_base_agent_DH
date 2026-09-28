import { useCallback, useEffect, useMemo, useState } from "react";
import { Check, Loader2, RefreshCw, Search, TriangleAlert } from "lucide-react";
import { useTranslation } from "react-i18next";

import { DismissibleStatusMessage } from "@/components/settings/shared/SettingsControls";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Chip } from "@/components/ui/chip";
import { DisclosureContent } from "@/components/ui/disclosure";
import { Input } from "@/components/ui/input";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { ApiError, fetchDomains, setDomainConfirmed, setDomainVenueEnabled } from "@/lib/api";
import type { DomainEntry, DomainVenue, DomainsPayload } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useClient } from "@/providers/ClientProvider";

/**
 * The venue registry, curated.
 *
 * This page is the MD3 pilot ("样板间"): it is built from the Phase-3 primitives
 * -- `Card`, `Chip`, the radius scale, the motion curves and the ambient layer
 * -- rather than from the older `SettingsGroup` idiom, so the new tokens can be
 * reviewed on a real screen before being pushed out across the rest of the
 * settings surface. It still sits in the settings shell and keeps the same root
 * `settings-stack`, so it navigates exactly like its neighbours.
 *
 * Only the two edits the registry rebuild actually preserves are offered (see
 * `nanobot/webui/domains_api.py`): a venue's `enabled` flag and a domain's
 * `confirmed` flag. The page therefore leans on `confirmed` rather than hiding
 * it: an unconfirmed domain loses its toggles on the next rebuild, so the card
 * says so and offers to fix it.
 */

/** Display order for the tiers the two registry sources produce. */
const TIER_ORDER = ["A*", "A", "B", "C"];

/**
 * Venues rendered before the "show more" button. The `ai` domain ships 231 of
 * them; the rest are one click away rather than a scroll away.
 */
const VENUE_PAGE_SIZE = 60;

type TierVariant = "filled" | "tonal" | "outline" | "tertiary";

/**
 * Chips carry the tier, so they have to read as a ranking at a glance. The top
 * mark takes `tertiary` -- the role MD3 reserves for an accent that is not a
 * primary action -- and the rest step down through the neutral variants.
 */
const TIER_VARIANT: Record<string, TierVariant> = {
  "A*": "tertiary",
  A: "filled",
  B: "tonal",
  C: "outline",
};

function tierVariant(tier: string | null | undefined): TierVariant {
  return (tier && TIER_VARIANT[tier]) || "outline";
}

function venueKey(domainId: string, venueName: string): string {
  return `venue:${domainId}:${venueName}`;
}

/** Pending-mutation key for the domain's confirmation toggle. */
function confirmKey(domainId: string): string {
  return `confirm:${domainId}`;
}

/**
 * One venue, as a checkbox.
 *
 * A `role="checkbox"` button rather than a switch: the list is scanned and
 * ticked a row at a time, which is what a checkbox announces. The button
 * element supplies Enter/Space and focus for free.
 */
function VenueRow({
  venue,
  saving,
  disabled,
  onToggle,
}: {
  venue: DomainVenue;
  saving: boolean;
  disabled: boolean;
  onToggle: () => void;
}) {
  const { t } = useTranslation();
  const enabled = Boolean(venue.enabled);
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={enabled}
      aria-label={t("settings.domains.toggleVenue", {
        defaultValue: "Use {{name}}",
        name: venue.name,
      })}
      disabled={disabled}
      onClick={onToggle}
      className={cn(
        "flex w-full min-w-0 items-center gap-3 rounded-control px-3 py-2 text-left",
        "transition-colors ease-standard hover:bg-secondary/60",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        "disabled:cursor-not-allowed disabled:opacity-55",
      )}
    >
      <span
        aria-hidden
        className={cn(
          "grid h-4 w-4 shrink-0 place-items-center rounded-mark border transition-colors ease-standard",
          enabled
            ? "border-primary bg-primary text-primary-foreground"
            : "border-border bg-background",
        )}
      >
        {saving ? (
          <Loader2 className="h-2.5 w-2.5 animate-spin motion-reduce:animate-none" />
        ) : enabled ? (
          <Check className="h-3 w-3" strokeWidth={3} />
        ) : null}
      </span>
      <span className="min-w-0 flex-1 truncate text-[13px] leading-5 text-foreground">
        {venue.name}
      </span>
      {venue.type ? (
        <span className="hidden shrink-0 text-[11px] text-muted-foreground sm:inline">
          {venue.type}
        </span>
      ) : null}
      {venue.tier ? <Chip variant={tierVariant(venue.tier)} size="sm">{venue.tier}</Chip> : null}
    </button>
  );
}

/** A domain's confirmation state, and the control that changes it. */
function ConfirmationBanner({
  domain,
  saving,
  disabled,
  onConfirm,
}: {
  domain: DomainEntry;
  saving: boolean;
  disabled: boolean;
  onConfirm: (confirmed: boolean) => void;
}) {
  const { t } = useTranslation();
  if (domain.confirmed) {
    return (
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] leading-5 text-muted-foreground">
        <Chip variant="tertiary" size="sm">
          {t("settings.domains.confirmed", { defaultValue: "Confirmed" })}
        </Chip>
        <span>{t("settings.domains.confirmedNote", {
          defaultValue: "These toggles survive a rebuild.",
        })}</span>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={disabled}
          onClick={() => onConfirm(false)}
          className="h-7 rounded-pill px-2.5 text-[12px] font-medium text-muted-foreground"
        >
          {t("settings.domains.unconfirmAction", { defaultValue: "Unconfirm" })}
        </Button>
      </div>
    );
  }
  return (
    <div
      role="status"
      className={cn(
        "flex flex-wrap items-center gap-x-3 gap-y-2 rounded-control px-3 py-2 text-[12px] leading-5",
        // `tertiary-foreground` is the on-tertiary role (white in light mode)
        // and would be unreadable on this tonal tint. `tertiary` itself is the
        // one that contrasts in both themes, since `.dark` redefines it.
        "bg-tertiary/15 text-tertiary",
      )}
    >
      <TriangleAlert className="h-3.5 w-3.5 shrink-0" aria-hidden />
      <span className="min-w-0 flex-1">
        <span className="font-medium">
          {t("settings.domains.unconfirmedTitle", { defaultValue: "Not confirmed" })}
        </span>
        {" — "}
        {t("settings.domains.unconfirmedBody", {
          defaultValue: "Rebuilding the registry resets these toggles.",
        })}
      </span>
      <Button
        type="button"
        size="sm"
        disabled={disabled}
        onClick={() => onConfirm(true)}
        className="h-7 rounded-pill px-3 text-[12px] font-medium"
      >
        {saving ? <Loader2 className="mr-1.5 h-3 w-3 animate-spin motion-reduce:animate-none" aria-hidden /> : null}
        {t("settings.domains.confirmAction", { defaultValue: "Confirm" })}
      </Button>
    </div>
  );
}

function DomainCard({
  domain,
  query,
  tier,
  onlyEnabled,
  pending,
  onToggleVenue,
  onConfirm,
}: {
  domain: DomainEntry;
  query: string;
  tier: string;
  onlyEnabled: boolean;
  pending: string | null;
  onToggleVenue: (venue: DomainVenue) => void;
  onConfirm: (confirmed: boolean) => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(true);
  const [limit, setLimit] = useState(VENUE_PAGE_SIZE);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return domain.venues.filter((venue) => {
      if (onlyEnabled && !venue.enabled) return false;
      if (tier !== "all" && (venue.tier ?? "") !== tier) return false;
      if (!needle) return true;
      return (
        venue.name.toLowerCase().includes(needle)
        || (venue.type ?? "").toLowerCase().includes(needle)
      );
    });
  }, [domain.venues, onlyEnabled, query, tier]);

  // A new filter is a new list; showing 60 of it again beats keeping a count
  // that was chosen for the previous one.
  useEffect(() => setLimit(VENUE_PAGE_SIZE), [onlyEnabled, query, tier]);

  const shown = visible.slice(0, limit);
  const hidden = visible.length - shown.length;
  const confirming = pending === confirmKey(domain.id);

  return (
    <Card>
      <CardHeader className="gap-3">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <button
            type="button"
            aria-expanded={open}
            aria-controls={`domain-panel-${domain.id}`}
            onClick={() => setOpen((value) => !value)}
            className="flex min-w-0 items-center gap-2 rounded-control px-1 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <CardTitle className="truncate">{domain.label}</CardTitle>
          </button>
          <Chip variant="tonal" size="sm">
            {t("settings.domains.counts", {
              defaultValue: "{{enabled}} of {{total}} enabled",
              enabled: domain.enabled_count,
              total: domain.venue_count,
            })}
          </Chip>
          {domain.arxiv_cats.slice(0, 3).map((category) => (
            <Chip key={category} variant="outline" size="sm">{category}</Chip>
          ))}
        </div>
        <ConfirmationBanner
          domain={domain}
          saving={confirming}
          disabled={pending !== null}
          onConfirm={onConfirm}
        />
      </CardHeader>
      <DisclosureContent id={`domain-panel-${domain.id}`} open={open}>
        <CardContent className="pb-3">
          {shown.length ? (
            <div className="grid grid-cols-1 gap-x-2 lg:grid-cols-2 2xl:grid-cols-3">
              {shown.map((venue) => {
                const key = venueKey(domain.id, venue.name);
                return (
                  <VenueRow
                    key={venue.name}
                    venue={venue}
                    saving={pending === key}
                    disabled={pending !== null && pending !== key}
                    onToggle={() => onToggleVenue(venue)}
                  />
                );
              })}
            </div>
          ) : (
            <p className="px-3 py-6 text-center text-[13px] text-muted-foreground">
              {t("settings.domains.noMatches", {
                defaultValue: "No venue matches these filters.",
              })}
            </p>
          )}
          {hidden > 0 ? (
            <div className="flex justify-center pt-3">
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={() => setLimit((value) => value + VENUE_PAGE_SIZE)}
                className="rounded-pill"
              >
                {t("settings.domains.showMore", {
                  defaultValue: "Show {{count}} more",
                  count: hidden,
                })}
              </Button>
            </div>
          ) : null}
        </CardContent>
      </DisclosureContent>
    </Card>
  );
}

export function DomainsSettings() {
  const { client, getToken } = useClient();
  const { i18n, t } = useTranslation();
  const [payload, setPayload] = useState<DomainsPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [tier, setTier] = useState("all");
  const [onlyEnabled, setOnlyEnabled] = useState(false);
  // Bumped by the retry button; the effect owns the fetch so its cleanup can
  // cancel a response that arrives after the page is gone.
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchDomains(getToken())
      .then((next) => {
        if (cancelled) return;
        setPayload(next);
        setMissing(false);
        setError(null);
      })
      .catch((reason: unknown) => {
        if (cancelled) return;
        // A missing registry is a setup step, not a failure. Its body is kept
        // as the error so the empty state can show the path and the command
        // the gateway named, rather than inventing its own copy of both.
        setError(reason instanceof Error ? reason.message : String(reason));
        setMissing(reason instanceof ApiError && reason.status === 404);
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [getToken, reloadToken]);

  const domains = useMemo(() => payload?.domains ?? [], [payload]);

  const tiers = useMemo(() => {
    const seen = new Set<string>();
    for (const domain of domains) {
      for (const venue of domain.venues) if (venue.tier) seen.add(venue.tier);
    }
    const known = TIER_ORDER.filter((value) => seen.has(value));
    const extra = Array.from(seen).filter((value) => !TIER_ORDER.includes(value)).sort();
    for (const value of extra) known.push(value);
    return known;
  }, [domains]);

  const runMutation = useCallback(
    async (key: string, action: () => Promise<DomainsPayload>) => {
      setPending(key);
      setError(null);
      try {
        const next = await action();
        setPayload(next);
      } catch (reason: unknown) {
        setError(reason instanceof Error ? reason.message : String(reason));
      } finally {
        setPending(null);
      }
    },
    [],
  );

  /**
   * One mutation at a time. Each answers with a full registry snapshot, so two
   * in flight at once could land out of order and paint the older one last.
   */
  const toggleVenue = useCallback(
    (domain: DomainEntry, venue: DomainVenue) => {
      if (pending !== null) return;
      void runMutation(
        venueKey(domain.id, venue.name),
        () => setDomainVenueEnabled(client, domain.id, venue.name, !venue.enabled),
      );
    },
    [client, pending, runMutation],
  );

  const confirmDomain = useCallback(
    (domain: DomainEntry, confirmed: boolean) => {
      if (pending !== null) return;
      void runMutation(
        confirmKey(domain.id),
        () => setDomainConfirmed(client, domain.id, confirmed),
      );
    },
    [client, pending, runMutation],
  );

  const totalEnabled = domains.reduce((sum, domain) => sum + domain.enabled_count, 0);
  const totalVenues = domains.reduce((sum, domain) => sum + domain.venue_count, 0);

  return (
    <div className="settings-stack">
      <section className="relative isolate overflow-hidden rounded-panel bg-card px-5 py-6">
        {/* MD3 ambient layer: decoration only, so it is hidden from assistive tech. */}
        <div aria-hidden className="pointer-events-none absolute inset-0 -z-10">
          <span className="ambient-shape ambient-shape-primary -left-8 -top-20 h-44 w-44" />
          <span className="ambient-shape ambient-shape-tertiary -top-12 right-4 h-32 w-32" />
        </div>
        <h2 className="text-[19px] font-normal leading-tight text-foreground">
          {t("settings.domains.title", { defaultValue: "Research domains" })}
        </h2>
        <p className="mt-1.5 max-w-[62ch] text-[13px] leading-5 text-muted-foreground">
          {t("settings.domains.caption", {
            defaultValue: "Choose which venues the agent searches for each domain.",
          })}
        </p>
        {domains.length ? (
          <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-muted-foreground">
            <Chip variant="filled" size="sm">
              {t("settings.domains.counts", {
                defaultValue: "{{enabled}} of {{total}} enabled",
                enabled: totalEnabled,
                total: totalVenues,
              })}
            </Chip>
            {payload?.path ? (
              <span className="truncate font-mono text-[11px] opacity-70" title={payload.path}>
                {payload.path}
              </span>
            ) : null}
          </div>
        ) : null}
      </section>

      {error && !missing ? (
        <DismissibleStatusMessage message={error} isError onDismiss={() => setError(null)} />
      ) : null}

      {payload?.suspects.length ? (
        <div className="flex items-start gap-2 rounded-control bg-tertiary/15 px-3 py-2 text-[12px] leading-5 text-tertiary">
          <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          <span>
            {t("settings.domains.suspects", {
              defaultValue: "The builder flagged {{count}} entries for review.",
              count: payload.suspects.length,
            })}
          </span>
        </div>
      ) : null}

      {loading && !payload ? (
        <div className="flex h-36 items-center justify-center text-sm text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden />
          {t("settings.domains.loading", { defaultValue: "Loading registry…" })}
        </div>
      ) : missing ? (
        <Card>
          <CardHeader>
            <CardTitle>
              {t("settings.domains.missingTitle", { defaultValue: "No venue registry yet" })}
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <p className="text-[13px] leading-5 text-muted-foreground">{error}</p>
            <div>
              <Button type="button" variant="outline" size="sm"
                onClick={() => setReloadToken((value) => value + 1)} className="rounded-pill">
                <RefreshCw className="mr-1.5 h-3.5 w-3.5" aria-hidden />
                {t("settings.domains.retry", { defaultValue: "Retry" })}
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : domains.length === 0 ? (
        <p className="px-3 py-12 text-center text-sm text-muted-foreground">
          {t("settings.domains.empty", { defaultValue: "The registry has no domains yet." })}
        </p>
      ) : (
        <>
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
                aria-label={t("settings.domains.search", { defaultValue: "Search venues" })}
                placeholder={t("settings.domains.search", { defaultValue: "Search venues" })}
                className="ps-11"
              />
            </div>
            <SegmentedControl
              value={tier}
              onChange={setTier}
              ariaLabel={t("settings.domains.tier", { defaultValue: "Tier" })}
              options={[
                { value: "all", label: t("settings.domains.allTiers", { defaultValue: "All tiers" }) },
                ...tiers.map((value) => ({ value, label: value })),
              ]}
            />
            <Button
              type="button"
              variant={onlyEnabled ? "default" : "outline"}
              size="sm"
              aria-pressed={onlyEnabled}
              onClick={() => setOnlyEnabled((value) => !value)}
              className="h-10 shrink-0 rounded-pill px-4"
            >
              {t("settings.domains.onlyEnabled", { defaultValue: "Enabled only" })}
            </Button>
          </div>

          {domains.map((domain) => (
            <DomainCard
              key={domain.id}
              domain={domain}
              query={query}
              tier={tier}
              onlyEnabled={onlyEnabled}
              pending={pending}
              onToggleVenue={(venue) => toggleVenue(domain, venue)}
              onConfirm={(confirmed) => confirmDomain(domain, confirmed)}
            />
          ))}

          <p className="px-1 text-[11px] leading-5 text-muted-foreground">
            {t("settings.domains.updatedAt", {
              defaultValue: "Updated {{value}}",
              value: formatStamp(
                domains.reduce<string | null>(
                  (latest, domain) => (domain.updated_at && (!latest || domain.updated_at > latest)
                    ? domain.updated_at
                    : latest),
                  null,
                ),
                i18n.resolvedLanguage,
              ),
            })}
          </p>
        </>
      )}
    </div>
  );
}

/** `updated_at` is the builder's UTC stamp; show it in the reader's own zone. */
function formatStamp(stamp: string | null, locale: string | undefined): string {
  if (!stamp) return "—";
  const parsed = new Date(stamp);
  if (Number.isNaN(parsed.getTime())) return stamp;
  return parsed.toLocaleString(locale ?? undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}
