import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DomainsSettings } from "@/components/settings/domains/DomainsSettings";
import type { DomainsPayload } from "@/lib/types";
import { ClientProvider } from "@/providers/ClientProvider";

import { requestMutationMock } from "./settings-test-utils";

/**
 * The page fetches on mount and every mutation answers with a whole registry,
 * so most tests here are about which request went out and what the page paints
 * from the reply -- not about the registry rules themselves, which
 * `tests/webui/test_domains_api.py` covers on the Python side.
 *
 * The two dialogs are portalled, and a destructive action's confirm button
 * carries the same words as the button that opened it. Both are why several
 * queries below go through `within(...)` rather than `screen`.
 */

function domainsPayload(): DomainsPayload {
  return {
    version: 1,
    path: "/home/u/.nanobot/workspace/registry/domains.json",
    suspects: [],
    domains: [
      {
        id: "ai",
        label: "人工智能 / AI",
        aliases: ["AI"],
        arxiv_cats: ["cs.CL", "cs.LG"],
        confirmed: false,
        updated_at: "2026-09-27T11:47:11Z",
        venue_count: 2,
        enabled_count: 1,
        origin: "ccf-2026",
        tier_override_count: 0,
        manual_edit_count: 0,
        venues: [
          {
            name: "ACL",
            tier: "A",
            base_tier: "A",
            type: "conference",
            enabled: true,
            origin: "ccf-2026",
          },
          {
            name: "EMNLP",
            tier: "B",
            base_tier: "B",
            type: "conference",
            enabled: false,
            origin: "ccf-2026",
          },
        ],
      },
      {
        id: "finance",
        label: "金融 / Finance",
        aliases: ["金融"],
        arxiv_cats: ["q-fin.PM"],
        confirmed: true,
        updated_at: "2026-09-27T11:47:11Z",
        venue_count: 1,
        enabled_count: 1,
        origin: "finance-seed",
        tier_override_count: 0,
        manual_edit_count: 0,
        venues: [
          {
            name: "Journal of Finance",
            tier: "A*",
            base_tier: "A*",
            type: "journal",
            enabled: true,
            origin: "ft50",
          },
        ],
      },
    ],
  };
}

/** The registry with EMNLP switched on, as the server would answer. */
function toggledPayload(): DomainsPayload {
  const payload = domainsPayload();
  const ai = payload.domains[0];
  ai.enabled_count = 2;
  ai.venues = ai.venues.map((venue) => (
    venue.name === "EMNLP" ? { ...venue, enabled: true } : venue
  ));
  return payload;
}

/** A registry carrying every kind of curation the page has to draw. */
function curatedPayload(): DomainsPayload {
  const payload = domainsPayload();
  const ai = payload.domains[0];
  ai.tier_override_count = 1;
  ai.manual_edit_count = 1;
  ai.venues = [
    { ...ai.venues[0], tier: "B" },
    { ...ai.venues[1], enabled: true },
    {
      name: "手加的刊",
      tier: "A",
      type: "journal",
      enabled: true,
      origin: "user",
    },
  ];
  ai.venue_count = 3;
  ai.enabled_count = 3;
  return payload;
}

function stubFetch(response: Partial<Response> & { body?: unknown }) {
  const { body, ...rest } = response;
  vi.stubGlobal("fetch", vi.fn(async () => ({
    ok: rest.ok ?? true,
    status: rest.status ?? 200,
    headers: { get: () => "application/json" },
    json: async () => body,
    text: async () => (typeof rest.text === "function" ? await rest.text() : ""),
    ...rest,
  } as unknown as Response)));
}

function renderDomains() {
  render(
    <ClientProvider client={{ requestMutation: requestMutationMock } as never} token="tok">
      <DomainsSettings />
    </ClientProvider>,
  );
}

/** Assert the exact frame that went out, so a renamed field fails loudly. */
function expectMutationSent(action: string, payload: Record<string, unknown>) {
  expect(requestMutationMock).toHaveBeenCalledWith(action, payload, 20_000);
}

/** Open the dialog behind a named button and hand back its subtree. */
async function openDialog(button: HTMLElement, role: "dialog" | "alertdialog" = "dialog") {
  fireEvent.click(button);
  return within(await screen.findByRole(role));
}

describe("DomainsSettings", () => {
  beforeEach(() => {
    requestMutationMock.mockReset();
    vi.stubGlobal(
      "matchMedia",
      vi.fn((query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    );
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("lists every domain with its venues and counts", async () => {
    stubFetch({ body: domainsPayload() });
    renderDomains();

    expect(await screen.findByText("人工智能 / AI")).toBeTruthy();
    expect(screen.getByText("金融 / Finance")).toBeTruthy();
    expect(screen.getByText("ACL")).toBeTruthy();
    expect(screen.getByText("EMNLP")).toBeTruthy();
    expect(screen.getByText("Journal of Finance")).toBeTruthy();
    // Per-domain count and the page total, which differ here on purpose.
    expect(screen.getByText("1 of 2 enabled")).toBeTruthy();
    expect(screen.getByText("2 of 3 enabled")).toBeTruthy();
  });

  it("marks a venue's checkbox from the registry", async () => {
    stubFetch({ body: domainsPayload() });
    renderDomains();

    const acl = await screen.findByRole("checkbox", { name: "Use ACL" });
    const emnlp = screen.getByRole("checkbox", { name: "Use EMNLP" });
    expect(acl.getAttribute("aria-checked")).toBe("true");
    expect(emnlp.getAttribute("aria-checked")).toBe("false");
  });

  it("sends the venue toggle the server expects and repaints from the reply", async () => {
    stubFetch({ body: domainsPayload() });
    requestMutationMock.mockResolvedValue(toggledPayload());
    renderDomains();

    fireEvent.click(await screen.findByRole("checkbox", { name: "Use EMNLP" }));

    await waitFor(() => {
      expectMutationSent("domains.venue.set_enabled", {
        domain_id: "ai",
        venue: "EMNLP",
        enabled: true,
      });
    });
    // The reply carries the whole registry; the page trusts it rather than
    // flipping the one row it clicked.
    await waitFor(() => {
      expect(screen.getByRole("checkbox", { name: "Use EMNLP" }).getAttribute("aria-checked"))
        .toBe("true");
    });
    expect(screen.getByText("2 of 2 enabled")).toBeTruthy();
  });

  it("records that a list was read without promising anything about a rebuild", async () => {
    stubFetch({ body: domainsPayload() });
    requestMutationMock.mockResolvedValue(domainsPayload());
    renderDomains();

    // ai is unreviewed, finance is reviewed. Neither state changes what a
    // rebuild does -- curation is kept either way -- so the page must not say
    // that it does.
    expect(await screen.findByText("Not reviewed")).toBeTruthy();
    expect(screen.getByText("Reviewed")).toBeTruthy();
    expect(screen.getAllByText("Your edits survive a rebuild either way.")).toHaveLength(2);
    expect(screen.queryByText(/resets these toggles/)).toBeNull();

    fireEvent.click(screen.getAllByRole("button", { name: "Mark reviewed" })[0]);

    await waitFor(() => {
      expectMutationSent("domains.confirm", { domain_id: "ai", confirmed: true });
    });
  });

  it("draws a hand-added venue and a drifted tier differently", async () => {
    stubFetch({ body: curatedPayload() });
    renderDomains();

    // A venue the user added, and one whose tier no longer matches its source.
    expect(await screen.findByText("Added by you")).toBeTruthy();
    expect(screen.getByText("was A")).toBeTruthy();
    expect(screen.getByText("1 tier edits")).toBeTruthy();
  });

  it("adds a venue through the dialog", async () => {
    stubFetch({ body: domainsPayload() });
    requestMutationMock.mockResolvedValue(domainsPayload());
    renderDomains();

    const dialog = await openDialog(await screen.findByRole("button", { name: "Add a venue to 人工智能 / AI" }));
    expect(dialog.getByText("Add a venue")).toBeTruthy();

    fireEvent.change(dialog.getByLabelText("Name"), { target: { value: "NeurIPS" } });
    fireEvent.click(dialog.getByRole("button", { name: "B" }));
    fireEvent.click(dialog.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expectMutationSent("domains.venue.add", {
        domain_id: "ai",
        venue: { name: "NeurIPS", tier: "B" },
      });
    });
    // The reply is the whole registry, so the dialog closes on it.
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("refuses to save a venue with no name", async () => {
    stubFetch({ body: domainsPayload() });
    renderDomains();

    const dialog = await openDialog(await screen.findByRole("button", { name: "Add a venue to 人工智能 / AI" }));

    expect(dialog.getByRole("button", { name: "Save" }).hasAttribute("disabled")).toBe(true);
    fireEvent.change(dialog.getByLabelText("Name"), { target: { value: "  " } });
    expect(dialog.getByRole("button", { name: "Save" }).hasAttribute("disabled")).toBe(true);
    expect(requestMutationMock).not.toHaveBeenCalled();
  });

  it("edits a generated venue's tier and says which fields a refresh rebuilds", async () => {
    stubFetch({ body: domainsPayload() });
    requestMutationMock.mockResolvedValue(domainsPayload());
    renderDomains();

    const dialog = await openDialog(await screen.findByRole("button", { name: "Edit ACL" }));
    expect(dialog.getByText(/rebuilt on the next refresh/)).toBeTruthy();

    fireEvent.click(dialog.getByRole("button", { name: "B" }));
    fireEvent.click(dialog.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      // Only the field that moved: rewriting the untouched ones would push the
      // form's copy of a source-owned value back over the row.
      expectMutationSent("domains.venue.update", {
        domain_id: "ai",
        venue: "ACL",
        patch: { tier: "B" },
      });
    });
  });

  it("sends a rename alongside the fields it changed", async () => {
    stubFetch({ body: domainsPayload() });
    requestMutationMock.mockResolvedValue(domainsPayload());
    renderDomains();

    const dialog = await openDialog(await screen.findByRole("button", { name: "Edit ACL" }));
    fireEvent.change(dialog.getByLabelText("Name"), { target: { value: "ACL 2027" } });
    fireEvent.click(dialog.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expectMutationSent("domains.venue.update", {
        domain_id: "ai",
        venue: "ACL",
        patch: { new_name: "ACL 2027" },
      });
    });
  });

  it("keeps the dialog open and shows why the server refused", async () => {
    stubFetch({ body: domainsPayload() });
    requestMutationMock.mockRejectedValue(new Error("venue already exists in ai: ACL"));
    renderDomains();

    const dialog = await openDialog(await screen.findByRole("button", { name: "Add a venue to 人工智能 / AI" }));
    fireEvent.change(dialog.getByLabelText("Name"), { target: { value: "ACL" } });
    fireEvent.click(dialog.getByRole("button", { name: "Save" }));

    // The message names a field, so it belongs next to the fields.
    expect(await dialog.findByRole("alert")).toHaveTextContent(
      "venue already exists in ai: ACL",
    );
    expect(screen.getByRole("dialog")).toBeTruthy();
    // And it stays typable, so the fix is one edit away.
    expect(dialog.getByLabelText("Name")).toHaveProperty("value", "ACL");
  });

  it("deletes a venue only after the confirm, and says what comes back", async () => {
    stubFetch({ body: domainsPayload() });
    requestMutationMock.mockResolvedValue(domainsPayload());
    renderDomains();

    const confirm = await openDialog(
      await screen.findByRole("button", { name: "Delete EMNLP" }),
      "alertdialog",
    );
    expect(confirm.getByText("Delete EMNLP?")).toBeTruthy();
    expect(confirm.getByText(/returns on the next rebuild/)).toBeTruthy();
    expect(requestMutationMock).not.toHaveBeenCalled();

    fireEvent.click(confirm.getByRole("button", { name: "Delete" }));

    await waitFor(() => {
      expectMutationSent("domains.venue.remove", { domain_id: "ai", venue: "EMNLP" });
    });
  });

  it("restores a domain's tiers after the confirm", async () => {
    stubFetch({ body: curatedPayload() });
    requestMutationMock.mockResolvedValue(domainsPayload());
    renderDomains();

    const confirm = await openDialog(
      await screen.findByRole("button", { name: "Restore source tiers for 人工智能 / AI" }),
      "alertdialog",
    );
    expect(confirm.getByText(/All 1 tier edits/)).toBeTruthy();

    // The card button behind the dialog carries the per-domain label, so the
    // click has to be scoped to the dialog to reach the action.
    fireEvent.click(confirm.getByRole("button", { name: "Restore source tiers" }));

    await waitFor(() => {
      expectMutationSent("domains.tier_reset", { domain_id: "ai" });
    });
  });

  it("disables the restore until there is something to restore", async () => {
    stubFetch({ body: domainsPayload() });
    renderDomains();

    const restore = await screen.findByRole("button", { name: "Restore source tiers for 人工智能 / AI" });
    expect(restore.hasAttribute("disabled")).toBe(true);
    expect(restore.getAttribute("title")).toBe("No tier edits to restore");
  });

  it("offers no restore for a domain that has no upstream", async () => {
    const payload = domainsPayload();
    payload.domains.push({
      id: "mine",
      label: "我自己建的",
      aliases: [],
      arxiv_cats: [],
      confirmed: false,
      updated_at: null,
      venue_count: 1,
      enabled_count: 1,
      origin: "user",
      tier_override_count: 0,
      manual_edit_count: 0,
      venues: [{ name: "手加的刊", tier: "A", enabled: true, origin: "user" }],
    });
    stubFetch({ body: payload });
    renderDomains();

    await screen.findByText("我自己建的");
    // ai and finance each get one; the hand-made domain gets none, because
    // there is no source to restore it to.
    expect(screen.getAllByRole("button", { name: /^Restore source tiers for / })).toHaveLength(2);
  });

  it("creates a domain", async () => {
    stubFetch({ body: domainsPayload() });
    requestMutationMock.mockResolvedValue(domainsPayload());
    renderDomains();

    const dialog = await openDialog(await screen.findByRole("button", { name: "Add domain" }));
    fireEvent.change(dialog.getByLabelText("ID"), { target: { value: "robotics" } });
    fireEvent.change(dialog.getByLabelText("Name"), { target: { value: "机器人 / Robotics" } });
    fireEvent.change(dialog.getByLabelText("arXiv categories"), {
      target: { value: "cs.RO, cs.SY" },
    });
    fireEvent.click(dialog.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expectMutationSent("domains.create", {
        id: "robotics",
        label: "机器人 / Robotics",
        aliases: [],
        arxiv_cats: ["cs.RO", "cs.SY"],
      });
    });
  });

  it("locks the domain ID once the domain exists", async () => {
    stubFetch({ body: domainsPayload() });
    requestMutationMock.mockResolvedValue(domainsPayload());
    renderDomains();

    const dialog = await openDialog(await screen.findByRole("button", { name: "Edit 人工智能 / AI" }));
    expect(dialog.getByLabelText("ID")).toHaveProperty("disabled", true);
    expect(dialog.getByText("The ID cannot be changed once the domain exists.")).toBeTruthy();

    fireEvent.change(dialog.getByLabelText("Name"), { target: { value: "AI 与机器学习" } });
    fireEvent.click(dialog.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expectMutationSent("domains.update", {
        domain_id: "ai",
        patch: { label: "AI 与机器学习", aliases: ["AI"], arxiv_cats: ["cs.CL", "cs.LG"] },
      });
    });
  });

  it("deletes a domain after the confirm", async () => {
    stubFetch({ body: domainsPayload() });
    requestMutationMock.mockResolvedValue(domainsPayload());
    renderDomains();

    const confirm = await openDialog(
      await screen.findByRole("button", { name: "Delete 金融 / Finance" }),
      "alertdialog",
    );
    expect(confirm.getByText("Delete 金融 / Finance?")).toBeTruthy();

    fireEvent.click(confirm.getByRole("button", { name: "Delete" }));

    await waitFor(() => {
      expectMutationSent("domains.delete", { domain_id: "finance" });
    });
  });

  it("shows the gateway's own message when no registry has been built", async () => {
    const message = "no venue registry at /home/u/.nanobot/workspace/registry/domains.json; "
      + "build one with skills/venue-registry/scripts/build_registry.py";
    stubFetch({ ok: false, status: 404, text: async () => message });
    renderDomains();

    expect(await screen.findByText("No venue registry yet")).toBeTruthy();
    // Repeating the path and the command here would be a second copy to drift.
    expect(screen.getByText(message)).toBeTruthy();
    expect(screen.getByRole("button", { name: /Retry/ })).toBeTruthy();
    expect(screen.queryByRole("checkbox")).toBeNull();
    // Nothing to add a venue to, so the page offers no such thing.
    expect(screen.queryByRole("button", { name: "Add domain" })).toBeNull();
  });

  it("filters by search text", async () => {
    stubFetch({ body: domainsPayload() });
    renderDomains();

    const search = await screen.findByRole("searchbox", { name: "Search venues" });
    fireEvent.change(search, { target: { value: "emnlp" } });

    await waitFor(() => {
      expect(screen.getByRole("checkbox", { name: "Use EMNLP" })).toBeTruthy();
    });
    expect(screen.queryByRole("checkbox", { name: "Use ACL" })).toBeNull();
  });

  it("narrows to enabled venues only", async () => {
    stubFetch({ body: domainsPayload() });
    renderDomains();

    fireEvent.click(await screen.findByRole("button", { name: "Enabled only" }));

    await waitFor(() => {
      expect(screen.queryByRole("checkbox", { name: "Use EMNLP" })).toBeNull();
    });
    expect(screen.getByRole("checkbox", { name: "Use ACL" })).toBeTruthy();
  });

  it("surfaces a mutation failure without dropping the page", async () => {
    stubFetch({ body: domainsPayload() });
    requestMutationMock.mockRejectedValue(new Error("unknown venue in ai: NOPE"));
    renderDomains();

    fireEvent.click(await screen.findByRole("checkbox", { name: "Use EMNLP" }));

    expect(await screen.findByText("unknown venue in ai: NOPE")).toBeTruthy();
    // The registry is still on screen, still holding its original state.
    expect(screen.getByRole("checkbox", { name: "Use EMNLP" }).getAttribute("aria-checked"))
      .toBe("false");
  });
});
