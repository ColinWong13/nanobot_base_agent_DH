import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
        venues: [
          { name: "ACL", tier: "A", type: "conference", enabled: true, origin: "ccf-2026" },
          { name: "EMNLP", tier: "B", type: "conference", enabled: false, origin: "ccf-2026" },
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
        venues: [
          { name: "Journal of Finance", tier: "A*", type: "journal", enabled: true, origin: "ft50" },
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
      expect(requestMutationMock).toHaveBeenCalledWith(
        "domains.venue.set_enabled",
        { domain_id: "ai", venue: "EMNLP", enabled: true },
        20_000,
      );
    });
    // The reply carries the whole registry; the page trusts it rather than
    // flipping the one row it clicked.
    await waitFor(() => {
      expect(screen.getByRole("checkbox", { name: "Use EMNLP" }).getAttribute("aria-checked"))
        .toBe("true");
    });
    expect(screen.getByText("2 of 2 enabled")).toBeTruthy();
  });

  it("warns that an unconfirmed domain loses its toggles, and confirms on request", async () => {
    const payload = domainsPayload();
    // ai is unconfirmed, finance is confirmed: one warning, one confirm action.
    stubFetch({ body: payload });
    requestMutationMock.mockResolvedValue(domainsPayload());
    renderDomains();

    expect(await screen.findByText("Not confirmed")).toBeTruthy();
    expect(screen.getByText("Confirmed")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    await waitFor(() => {
      expect(requestMutationMock).toHaveBeenCalledWith(
        "domains.confirm",
        { domain_id: "ai", confirmed: true },
        20_000,
      );
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
