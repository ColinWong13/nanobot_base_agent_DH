import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import {
  Check,
  Loader2,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  TriangleAlert,
  Undo2,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { DismissibleStatusMessage } from "@/components/settings/shared/SettingsControls";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Chip } from "@/components/ui/chip";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { DisclosureContent } from "@/components/ui/disclosure";
import { Input } from "@/components/ui/input";
import { SegmentedControl } from "@/components/ui/segmented-control";
import {
  addDomainVenue,
  ApiError,
  createDomain,
  deleteDomain,
  fetchDomains,
  removeDomainVenue,
  resetDomainTiers,
  setDomainConfirmed,
  setDomainVenueEnabled,
  updateDomain,
  updateDomainVenue,
} from "@/lib/api";
import type { VenuePatch } from "@/lib/api";
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
 * **Every edit here survives a rebuild.** The registry file keeps the user's
 * intent in an `overrides` block and re-applies it on every build (see
 * `venue-registry/scripts/build_registry.py`), so the page offers the whole
 * editing surface: venues, domains and tiers. The one thing a rebuild *does*
 * overwrite is a generated venue's descriptive fields, because the row is
 * regenerated from its source -- the venue dialog says so where it applies.
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

/** Pending-mutation key for the domain's review marker. */
function reviewKey(domainId: string): string {
  return `review:${domainId}`;
}

/** A hand-made venue, as opposed to one a source generated. */
function isUserVenue(venue: DomainVenue): boolean {
  return venue.origin === "user";
}

/**
 * One venue: the tick that decides whether the agent searches it, plus the two
 * controls that change the entry itself.
 *
 * The tick is a `role="checkbox"` button rather than a switch -- the list is
 * scanned and ticked a row at a time, which is what a checkbox announces -- and
 * the row's other controls sit *beside* it rather than inside it, because a
 * button cannot contain a button.
 */
function VenueRow({
  venue,
  saving,
  disabled,
  onToggle,
  onEdit,
  onDelete,
}: {
  venue: DomainVenue;
  saving: boolean;
  disabled: boolean;
  onToggle: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation();
  const enabled = Boolean(venue.enabled);
  // The tier no longer matches what the source ranks it. Only a curated venue
  // can drift, and `base_tier` is absent exactly when nothing ranked it.
  const drifted = Boolean(venue.base_tier && venue.base_tier !== venue.tier);
  return (
    <div
      className={cn(
        "flex min-w-0 items-center gap-1 rounded-control ps-1 pe-1",
        "transition-colors ease-standard hover:bg-secondary/60",
      )}
    >
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
          "flex min-w-0 flex-1 items-center gap-3 rounded-control px-2 py-2 text-left",
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
        {isUserVenue(venue) ? (
          <Chip variant="outline" size="sm">
            {t("settings.domains.userAdded", { defaultValue: "Added by you" })}
          </Chip>
        ) : null}
        {drifted ? (
          <span className="shrink-0 text-[10px] leading-4 text-muted-foreground">
            {t("settings.domains.sourceTier", {
              defaultValue: "was {{tier}}",
              tier: venue.base_tier,
            })}
          </span>
        ) : null}
        {venue.type ? (
          <span className="hidden shrink-0 text-[11px] text-muted-foreground sm:inline">
            {venue.type}
          </span>
        ) : null}
        {venue.tier ? <Chip variant={tierVariant(venue.tier)} size="sm">{venue.tier}</Chip> : null}
      </button>
      {/* Always visible rather than revealed on hover: a row whose controls
          only exist under a pointer is unusable on a touch screen. */}
      <Button
        type="button"
        variant="ghost"
        size="icon"
        disabled={disabled}
        aria-label={t("settings.domains.editVenue", {
          defaultValue: "Edit {{name}}",
          name: venue.name,
        })}
        onClick={onEdit}
        className="h-7 w-7 shrink-0 rounded-full text-muted-foreground"
      >
        <Pencil className="h-3.5 w-3.5" aria-hidden />
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        disabled={disabled}
        aria-label={t("settings.domains.deleteVenue", {
          defaultValue: "Delete {{name}}",
          name: venue.name,
        })}
        onClick={onDelete}
        className="h-7 w-7 shrink-0 rounded-full text-muted-foreground hover:text-destructive"
      >
        <Trash2 className="h-3.5 w-3.5" aria-hidden />
      </Button>
    </div>
  );
}

/**
 * Whether the reader has been through this list, and the button that changes
 * that.
 *
 * This used to be a warning banner, because a rebuild really did reset the
 * toggles of an unconfirmed domain. It no longer does -- curation is kept
 * unconditionally -- so the banner would be a lie and the tint and the triangle
 * would be alarm about nothing. All that is left is a note to oneself.
 */
function ReviewMark({
  domain,
  saving,
  disabled,
  onToggle,
}: {
  domain: DomainEntry;
  saving: boolean;
  disabled: boolean;
  onToggle: (reviewed: boolean) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] leading-5 text-muted-foreground">
      {domain.confirmed ? (
        <Chip variant="tonal" size="sm">
          {t("settings.domains.confirmed", { defaultValue: "Reviewed" })}
        </Chip>
      ) : (
        <span className="font-medium">
          {t("settings.domains.unconfirmedTitle", { defaultValue: "Not reviewed" })}
        </span>
      )}
      <span className="min-w-0">
        {t("settings.domains.confirmedNote", {
          defaultValue: "Your edits survive a rebuild either way.",
        })}
      </span>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        disabled={disabled}
        onClick={() => onToggle(!domain.confirmed)}
        className="h-7 rounded-pill px-2.5 text-[12px] font-medium text-muted-foreground"
      >
        {saving ? (
          <Loader2 className="mr-1.5 h-3 w-3 animate-spin motion-reduce:animate-none" aria-hidden />
        ) : null}
        {domain.confirmed
          ? t("settings.domains.unconfirmAction", { defaultValue: "Unmark" })
          : t("settings.domains.confirmAction", { defaultValue: "Mark reviewed" })}
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
  onEditVenue,
  onDeleteVenue,
  onAddVenue,
  onEditDomain,
  onDeleteDomain,
  onRestoreTiers,
  onToggleReviewed,
}: {
  domain: DomainEntry;
  query: string;
  tier: string;
  onlyEnabled: boolean;
  pending: string | null;
  onToggleVenue: (venue: DomainVenue) => void;
  onEditVenue: (venue: DomainVenue) => void;
  onDeleteVenue: (venue: DomainVenue) => void;
  onAddVenue: () => void;
  onEditDomain: () => void;
  onDeleteDomain: () => void;
  onRestoreTiers: () => void;
  onToggleReviewed: (reviewed: boolean) => void;
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
  const reviewing = pending === reviewKey(domain.id);
  const busy = pending !== null;
  // A domain with no upstream has nothing to restore its tiers to, so the
  // action is absent rather than disabled.
  const restoreable = domain.origin !== "user";
  const overrides = domain.tier_override_count;

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
          {overrides > 0 ? (
            <Chip variant="tertiary" size="sm">
              {t("settings.domains.tierEdits", {
                defaultValue: "{{count}} tier edits",
                count: overrides,
              })}
            </Chip>
          ) : null}
          {domain.arxiv_cats.slice(0, 3).map((category) => (
            <Chip key={category} variant="outline" size="sm">{category}</Chip>
          ))}
        </div>
        <ReviewMark
          domain={domain}
          saving={reviewing}
          disabled={busy}
          onToggle={onToggleReviewed}
        />
        {/* Every card carries the same four buttons, so each one's accessible
            name names its own domain -- otherwise a screen reader hears "Add
            venue" as many times as there are domains, with nothing to tell
            them apart. */}
        <div className="flex flex-wrap items-center gap-1.5">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={busy}
            aria-label={t("settings.domains.addVenueFor", {
              defaultValue: "Add a venue to {{domain}}",
              domain: domain.label,
            })}
            onClick={onAddVenue}
            className="h-7 rounded-pill px-2.5 text-[12px] font-medium"
          >
            <Plus className="mr-1 h-3.5 w-3.5" aria-hidden />
            {t("settings.domains.addVenue", { defaultValue: "Add venue" })}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={busy}
            aria-label={t("settings.domains.editDomainTitle", {
              defaultValue: "Edit {{name}}",
              name: domain.label,
            })}
            onClick={onEditDomain}
            className="h-7 rounded-pill px-2.5 text-[12px] font-medium"
          >
            <Pencil className="mr-1 h-3.5 w-3.5" aria-hidden />
            {t("settings.domains.editDomain", { defaultValue: "Edit domain" })}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={busy}
            aria-label={t("settings.domains.deleteDomainFor", {
              defaultValue: "Delete {{domain}}",
              domain: domain.label,
            })}
            onClick={onDeleteDomain}
            className="h-7 rounded-pill px-2.5 text-[12px] font-medium text-muted-foreground hover:text-destructive"
          >
            <Trash2 className="mr-1 h-3.5 w-3.5" aria-hidden />
            {t("settings.domains.deleteDomain", { defaultValue: "Delete domain" })}
          </Button>
          {restoreable ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={busy || overrides === 0}
              aria-label={t("settings.domains.restoreTiersFor", {
                defaultValue: "Restore source tiers for {{domain}}",
                domain: domain.label,
              })}
              title={
                overrides === 0
                  ? t("settings.domains.nothingToRestore", {
                      defaultValue: "No tier edits to restore",
                    })
                  : undefined
              }
              onClick={onRestoreTiers}
              className="h-7 rounded-pill px-3 text-[12px] font-medium"
            >
              <Undo2 className="mr-1 h-3.5 w-3.5" aria-hidden />
              {t("settings.domains.restoreTiers", { defaultValue: "Restore source tiers" })}
            </Button>
          ) : null}
        </div>
      </CardHeader>
      <DisclosureContent id={`domain-panel-${domain.id}`} open={open}>
        <CardContent className="pb-3">
          {shown.length ? (
            <div className="grid grid-cols-1 gap-x-2 lg:grid-cols-2 2xl:grid-cols-3">
              {shown.map((venue) => {
                const key = venueKey(domain.id, venue.name);
                const rowBusy = busy && pending !== key;
                return (
                  <VenueRow
                    key={venue.name}
                    venue={venue}
                    saving={pending === key}
                    disabled={rowBusy}
                    onToggle={() => onToggleVenue(venue)}
                    onEdit={() => onEditVenue(venue)}
                    onDelete={() => onDeleteVenue(venue)}
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

/** A labelled form row. The hint is the backend's rule, said in advance. */
function Field({
  id,
  label,
  hint,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-[12px] font-medium leading-5 text-foreground">
        {label}
      </label>
      {children}
      {hint ? (
        <span className="text-[11px] leading-4 text-muted-foreground">{hint}</span>
      ) : null}
    </div>
  );
}

interface VenueForm {
  name: string;
  tier: string;
  type: string;
  full_name: string;
  area: string;
  issn: string;
}

const EMPTY_VENUE: VenueForm = {
  name: "",
  tier: "",
  type: "",
  full_name: "",
  area: "",
  issn: "",
};

function venueToForm(venue: DomainVenue | null): VenueForm {
  if (!venue) return EMPTY_VENUE;
  return {
    name: venue.name,
    tier: venue.tier ?? "",
    type: venue.type ?? "",
    full_name: venue.full_name ?? "",
    area: venue.area ?? "",
    issn: venue.issn ?? "",
  };
}

/** The tiers this domain can be given, matching the backend's `_require_tier`. */
function tierOptions(domain: DomainEntry): string[] {
  const seen = new Set<string>();
  for (const venue of domain.venues) if (venue.tier) seen.add(venue.tier);
  const known = TIER_ORDER.filter((value) => seen.has(value));
  for (const extra of Array.from(seen).filter((v) => !TIER_ORDER.includes(v)).sort()) {
    known.push(extra);
  }
  return known;
}

function VenueDialog({
  domain,
  venue,
  onClose,
  onSaved,
}: {
  domain: DomainEntry;
  venue: DomainVenue | null;
  onClose: () => void;
  onSaved: (next: DomainsPayload) => void;
}) {
  const { client } = useClient();
  const { t } = useTranslation();
  const [form, setForm] = useState<VenueForm>(() => venueToForm(venue));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const editing = venue !== null;
  // Set only where it applies: a generated row is rebuilt from its source, so
  // the descriptive fields typed here are the ones that will not last.
  const generated = editing && !isUserVenue(venue);

  const set = <K extends keyof VenueForm>(key: K, value: VenueForm[K]) =>
    setForm((current) => ({ ...current, [key]: value }));

  const tiers = tierOptions(domain);
  const canSave = form.name.trim().length > 0 && !saving;

  const submit = async () => {
    if (!canSave) return;
    setSaving(true);
    setError(null);
    // Only what changed, so an untouched field is not rewritten from the form's
    // copy of it -- which for a generated row is a value the source owns. Blank
    // values are skipped rather than sent: the API reads a field's presence as
    // "set it", rejects an empty string, and has no way to clear one either.
    const patch: VenuePatch = {};
    const next = venueToForm(venue);
    for (const field of ["tier", "type", "full_name", "area", "issn"] as const) {
      const value = form[field].trim();
      if (value && value !== next[field]) patch[field] = value;
    }
    const renamed = form.name.trim() !== (venue?.name ?? "");
    try {
      const payload = editing
        ? await updateDomainVenue(client, domain.id, venue.name, {
            ...patch,
            ...(renamed ? { new_name: form.name.trim() } : {}),
          })
        : await addDomainVenue(client, domain.id, {
            name: form.name.trim(),
            ...(form.tier ? { tier: form.tier } : {}),
            ...(form.type.trim() ? { type: form.type.trim() } : {}),
            ...(form.full_name.trim() ? { full_name: form.full_name.trim() } : {}),
            ...(form.area.trim() ? { area: form.area.trim() } : {}),
            ...(form.issn.trim() ? { issn: form.issn.trim() } : {}),
          });
      onSaved(payload);
    } catch (reason: unknown) {
      // Shown in the dialog rather than the page banner: the message names the
      // field, so it belongs next to the fields it is about.
      setError(reason instanceof Error ? reason.message : String(reason));
      setSaving(false);
    }
  };

  return (
    <Dialog open onOpenChange={(open) => { if (!open && !saving) onClose(); }}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {editing
              ? t("settings.domains.editVenueTitle", {
                  defaultValue: "Edit {{name}}",
                  name: venue.name,
                })
              : t("settings.domains.addVenueTitle", { defaultValue: "Add a venue" })}
          </DialogTitle>
          <DialogDescription>
            {t("settings.domains.caption", {
              defaultValue: "Choose which venues the agent searches for each domain.",
            })}
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <Field
            id="venue-name"
            label={t("settings.domains.venueName", { defaultValue: "Name" })}
          >
            <Input
              id="venue-name"
              autoFocus
              value={form.name}
              onChange={(event) => set("name", event.target.value)}
            />
          </Field>
          <Field
            id="venue-tier"
            label={t("settings.domains.tier", { defaultValue: "Tier" })}
          >
            <SegmentedControl
              value={form.tier || "none"}
              onChange={(value) => set("tier", value === "none" ? "" : value)}
              ariaLabel={t("settings.domains.tier", { defaultValue: "Tier" })}
              options={[
                // Only a new venue may go without a tier: the API takes a tier
                // as a non-empty string, so there is nothing "clear" could mean
                // for one that already has it.
                ...(editing ? [] : [{ value: "none", label: "—" }]),
                ...tiers.map((value) => ({ value, label: value })),
              ]}
            />
          </Field>
          {generated ? (
            <p className="rounded-control bg-tertiary/15 px-3 py-2 text-[12px] leading-5 text-tertiary">
              {t("settings.domains.generatedVenueNote", {
                defaultValue:
                  "This venue comes from a data source, so these fields are rebuilt on the next refresh. Its tier is yours to keep.",
              })}
            </p>
          ) : null}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field
              id="venue-type"
              label={t("settings.domains.venueType", { defaultValue: "Type" })}
              hint={t("settings.domains.optional", { defaultValue: "Optional" })}
            >
              <Input
                id="venue-type"
                value={form.type}
                onChange={(event) => set("type", event.target.value)}
              />
            </Field>
            <Field
              id="venue-full-name"
              label={t("settings.domains.venueFullName", { defaultValue: "Full name" })}
              hint={t("settings.domains.optional", { defaultValue: "Optional" })}
            >
              <Input
                id="venue-full-name"
                value={form.full_name}
                onChange={(event) => set("full_name", event.target.value)}
              />
            </Field>
            <Field
              id="venue-area"
              label={t("settings.domains.venueArea", { defaultValue: "Area" })}
              hint={t("settings.domains.optional", { defaultValue: "Optional" })}
            >
              <Input
                id="venue-area"
                value={form.area}
                onChange={(event) => set("area", event.target.value)}
              />
            </Field>
            <Field
              id="venue-issn"
              label={t("settings.domains.venueIssn", { defaultValue: "ISSN" })}
              hint={t("settings.domains.optional", { defaultValue: "Optional" })}
            >
              <Input
                id="venue-issn"
                value={form.issn}
                onChange={(event) => set("issn", event.target.value)}
              />
            </Field>
          </div>
          {error ? (
            <p role="alert" className="text-[12px] leading-5 text-destructive">{error}</p>
          ) : null}
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" disabled={saving} onClick={onClose}
            className="rounded-pill">
            {t("common.cancel", { defaultValue: "Cancel" })}
          </Button>
          <Button type="button" disabled={!canSave} onClick={() => void submit()}
            className="rounded-pill">
            {saving ? (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin motion-reduce:animate-none"
                aria-hidden />
            ) : null}
            {t("settings.domains.save", { defaultValue: "Save" })}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

interface DomainForm {
  id: string;
  label: string;
  aliases: string;
  arxiv_cats: string;
}

/** Comma-separated in the form, a list in the file. */
function splitList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function DomainDialog({
  domain,
  onClose,
  onSaved,
}: {
  domain: DomainEntry | null;
  onClose: () => void;
  onSaved: (next: DomainsPayload) => void;
}) {
  const { client } = useClient();
  const { t } = useTranslation();
  const [form, setForm] = useState<DomainForm>(() => ({
    id: domain?.id ?? "",
    label: domain?.label ?? "",
    aliases: (domain?.aliases ?? []).join(", "),
    arxiv_cats: (domain?.arxiv_cats ?? []).join(", "),
  }));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const editing = domain !== null;
  const set = <K extends keyof DomainForm>(key: K, value: DomainForm[K]) =>
    setForm((current) => ({ ...current, [key]: value }));

  // Deliberately not the backend's regex, only its shape: a client copy of the
  // rule would drift, and the server's own message names the id it rejected.
  const canSave = form.id.trim().length > 0 && form.label.trim().length > 0 && !saving;

  const submit = async () => {
    if (!canSave) return;
    setSaving(true);
    setError(null);
    try {
      const payload = editing
        ? await updateDomain(client, domain.id, {
            label: form.label.trim(),
            aliases: splitList(form.aliases),
            arxiv_cats: splitList(form.arxiv_cats),
          })
        : await createDomain(
            client,
            form.id.trim(),
            form.label.trim(),
            splitList(form.aliases),
            splitList(form.arxiv_cats),
          );
      onSaved(payload);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setSaving(false);
    }
  };

  return (
    <Dialog open onOpenChange={(open) => { if (!open && !saving) onClose(); }}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {editing
              ? t("settings.domains.editDomainTitle", {
                  defaultValue: "Edit {{name}}",
                  name: domain.label,
                })
              : t("settings.domains.addDomainTitle", { defaultValue: "Add a domain" })}
          </DialogTitle>
          <DialogDescription>
            {t("settings.domains.domainDialogHint", {
              defaultValue:
                "A domain groups the venues the agent searches together for one field.",
            })}
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <Field
            id="domain-id"
            label={t("settings.domains.domainId", { defaultValue: "ID" })}
            hint={
              editing
                ? t("settings.domains.domainIdFixed", {
                    defaultValue: "The ID cannot be changed once the domain exists.",
                  })
                : t("settings.domains.domainIdHint", {
                    defaultValue: "Lowercase letters, digits, and - or _",
                  })
            }
          >
            <Input
              id="domain-id"
              autoFocus={!editing}
              value={form.id}
              disabled={editing}
              onChange={(event) => set("id", event.target.value)}
            />
          </Field>
          <Field
            id="domain-label"
            label={t("settings.domains.domainLabel", { defaultValue: "Name" })}
          >
            <Input
              id="domain-label"
              autoFocus={editing}
              value={form.label}
              onChange={(event) => set("label", event.target.value)}
            />
          </Field>
          <Field
            id="domain-aliases"
            label={t("settings.domains.domainAliases", { defaultValue: "Aliases" })}
            hint={t("settings.domains.commaHint", { defaultValue: "Separate with commas" })}
          >
            <Input
              id="domain-aliases"
              value={form.aliases}
              onChange={(event) => set("aliases", event.target.value)}
            />
          </Field>
          <Field
            id="domain-cats"
            label={t("settings.domains.domainArxivCats", { defaultValue: "arXiv categories" })}
            hint={t("settings.domains.commaHint", { defaultValue: "Separate with commas" })}
          >
            <Input
              id="domain-cats"
              value={form.arxiv_cats}
              onChange={(event) => set("arxiv_cats", event.target.value)}
            />
          </Field>
          {error ? (
            <p role="alert" className="text-[12px] leading-5 text-destructive">{error}</p>
          ) : null}
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" disabled={saving} onClick={onClose}
            className="rounded-pill">
            {t("common.cancel", { defaultValue: "Cancel" })}
          </Button>
          <Button type="button" disabled={!canSave} onClick={() => void submit()}
            className="rounded-pill">
            {saving ? (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin motion-reduce:animate-none"
                aria-hidden />
            ) : null}
            {t("settings.domains.save", { defaultValue: "Save" })}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** What the delete and restore buttons ask before they do it. */
type Destructive =
  | { kind: "venue"; domain: DomainEntry; venue: DomainVenue }
  | { kind: "domain"; domain: DomainEntry }
  | { kind: "restore"; domain: DomainEntry }
  | null;

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
  const [editingVenue, setEditingVenue] = useState<{ domain: DomainEntry; venue: DomainVenue | null } | null>(null);
  const [editingDomain, setEditingDomain] = useState<{ domain: DomainEntry | null } | null>(null);
  const [destructive, setDestructive] = useState<Destructive>(null);
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

  const markReviewed = useCallback(
    (domain: DomainEntry, reviewed: boolean) => {
      if (pending !== null) return;
      void runMutation(
        reviewKey(domain.id),
        () => setDomainConfirmed(client, domain.id, reviewed),
      );
    },
    [client, pending, runMutation],
  );

  /** The dialog owns its own error, so this only runs on success. */
  const applySaved = useCallback((next: DomainsPayload) => {
    setPayload(next);
    setError(null);
    setEditingVenue(null);
    setEditingDomain(null);
    setDestructive(null);
  }, []);

  const runDestructive = useCallback(async () => {
    if (!destructive) return;
    const key = destructive.kind === "venue"
      ? venueKey(destructive.domain.id, destructive.venue.name)
      : `${destructive.kind}:${destructive.domain.id}`;
    setPending(key);
    setError(null);
    try {
      const next = destructive.kind === "venue"
        ? await removeDomainVenue(client, destructive.domain.id, destructive.venue.name)
        : destructive.kind === "domain"
          ? await deleteDomain(client, destructive.domain.id)
          : await resetDomainTiers(client, destructive.domain.id);
      applySaved(next);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setDestructive(null);
    } finally {
      setPending(null);
    }
  }, [applySaved, client, destructive]);

  const totalEnabled = domains.reduce((sum, domain) => sum + domain.enabled_count, 0);
  const totalVenues = domains.reduce((sum, domain) => sum + domain.venue_count, 0);

  /** The three destructive actions differ only in what they promise. */
  const confirmCopy = (() => {
    if (!destructive) return null;
    if (destructive.kind === "venue") {
      return {
        title: t("settings.domains.deleteVenueTitle", {
          defaultValue: "Delete {{name}}?",
          name: destructive.venue.name,
        }),
        body: t("settings.domains.deleteVenueBody", {
          defaultValue:
            "A venue that came from a source returns on the next rebuild. One you added is gone for good.",
        }),
        // Just the verb: the title already names what is about to go, and the
        // row's own button is still on screen behind the dialog.
        action: t("deleteConfirm.confirm", { defaultValue: "Delete" }),
      };
    }
    if (destructive.kind === "domain") {
      return {
        title: t("settings.domains.deleteDomainTitle", {
          defaultValue: "Delete {{name}}?",
          name: destructive.domain.label,
        }),
        body: t("settings.domains.deleteDomainBody", {
          defaultValue:
            "Its venues and your edits to it are removed. A domain that came from a source returns on the next rebuild, without your edits.",
        }),
        action: t("deleteConfirm.confirm", { defaultValue: "Delete" }),
      };
    }
    return {
      title: t("settings.domains.restoreTiersTitle", { defaultValue: "Restore source tiers?" }),
      body: t("settings.domains.restoreTiersBody", {
        defaultValue:
          "All {{count}} tier edits in this domain go back to what the source ranks them.",
        count: destructive.domain.tier_override_count,
      }),
      action: t("settings.domains.restoreTiers", { defaultValue: "Restore source tiers" }),
    };
  })();

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
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={pending !== null}
              onClick={() => setEditingDomain({ domain: null })}
              className="h-7 rounded-pill px-3 text-[12px] font-medium"
            >
              <Plus className="mr-1 h-3.5 w-3.5" aria-hidden />
              {t("settings.domains.addDomain", { defaultValue: "Add domain" })}
            </Button>
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
              onEditVenue={(venue) => setEditingVenue({ domain, venue })}
              onDeleteVenue={(venue) => setDestructive({ kind: "venue", domain, venue })}
              onAddVenue={() => setEditingVenue({ domain, venue: null })}
              onEditDomain={() => setEditingDomain({ domain })}
              onDeleteDomain={() => setDestructive({ kind: "domain", domain })}
              onRestoreTiers={() => setDestructive({ kind: "restore", domain })}
              onToggleReviewed={(reviewed) => markReviewed(domain, reviewed)}
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

      {editingVenue ? (
        <VenueDialog
          domain={editingVenue.domain}
          venue={editingVenue.venue}
          onClose={() => setEditingVenue(null)}
          onSaved={applySaved}
        />
      ) : null}

      {editingDomain ? (
        <DomainDialog
          domain={editingDomain.domain}
          onClose={() => setEditingDomain(null)}
          onSaved={applySaved}
        />
      ) : null}

      <AlertDialog
        open={destructive !== null}
        onOpenChange={(open) => { if (!open && pending === null) setDestructive(null); }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{confirmCopy?.title}</AlertDialogTitle>
            <AlertDialogDescription>{confirmCopy?.body}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={pending !== null}>
              {t("common.cancel", { defaultValue: "Cancel" })}
            </AlertDialogCancel>
            <AlertDialogAction
              disabled={pending !== null}
              onClick={(event) => { event.preventDefault(); void runDestructive(); }}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {pending !== null ? (
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin motion-reduce:animate-none"
                  aria-hidden />
              ) : null}
              {confirmCopy?.action}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
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
