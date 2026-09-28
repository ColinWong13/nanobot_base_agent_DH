import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

describe("index.html", () => {
  it("keeps browser zoom available", () => {
    const html = readFileSync(resolve(process.cwd(), "index.html"), "utf8");
    const viewport = html.match(/<meta\s+name="viewport"\s+content="([^"]+)"/i)?.[1];

    expect(viewport).toContain("width=device-width");
    expect(viewport).not.toContain("user-scalable=no");
    expect(viewport).not.toMatch(/maximum-scale\s*=\s*1(?:\.0)?(?:,|$)/);
  });

  it("lets iOS keep standalone content inside the safe area", () => {
    const html = readFileSync(resolve(process.cwd(), "index.html"), "utf8");
    const viewport = html.match(/<meta\s+name="viewport"\s+content="([^"]+)"/i)?.[1];

    expect(viewport).toContain("viewport-fit=auto");
    expect(viewport).not.toContain("viewport-fit=cover");
  });

  it("provides light and dark PWA chrome colors", () => {
    const html = readFileSync(resolve(process.cwd(), "index.html"), "utf8");
    const manifest = JSON.parse(
      readFileSync(resolve(process.cwd(), "public/manifest.json"), "utf8"),
    ) as {
      background_color?: string;
      theme_color?: string;
      color_scheme_dark?: { background_color?: string; theme_color?: string };
    };
    const document = new DOMParser().parseFromString(html, "text/html");
    const themeColor = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
    const lightBodyBackground = html.match(/body\s*{[^}]*background:\s*([^;]+);/s)?.[1]?.trim();
    const darkBodyBackground = html.match(
      /html\.dark body\s*{[^}]*background:\s*([^;]+);/s,
    )?.[1]?.trim();

    // The MD3 background/on-background pair. Three places paint the first
    // frame -- the meta tag, the inline sheet, and the manifest -- and they are
    // read by three different runtimes, so this asserts they agree rather than
    // asserting any one of them.
    expect(themeColor?.content).toBe("#fffbfe");
    expect(themeColor?.dataset.themeColorLight).toBe("#fffbfe");
    expect(themeColor?.dataset.themeColorDark).toBe("#141218");
    expect(lightBodyBackground).toBe("#fffbfe");
    expect(darkBodyBackground).toBe("#141218");
    expect(manifest.background_color).toBe("#fffbfe");
    expect(manifest.theme_color).toBe("#fffbfe");
    expect(manifest.color_scheme_dark?.background_color).toBe("#141218");
    expect(manifest.color_scheme_dark?.theme_color).toBe("#141218");
  });
});
