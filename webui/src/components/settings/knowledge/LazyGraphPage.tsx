import { Suspense, lazy } from "react";
import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

/**
 * The graph page, behind its own chunk.
 *
 * cytoscape and its layout extension are roughly half a megabyte, and the only
 * page that needs them is this one — so they are fetched when someone opens the
 * graph, not when the shell loads. `import()` is what does that: the bundler
 * gives everything reachable only from here its own file, and the `graph-vendor`
 * manual chunk in `vite.config.ts` keeps the library itself in a second one.
 *
 * The boundary lives here rather than in `SettingsPage` so that the switch there
 * reads like every other section — and so that the reason for the split is
 * written down next to the split.
 */
const GraphPage = lazy(() =>
  import("@/components/settings/knowledge/GraphPage").then((module) => ({
    default: module.GraphPage,
  })),
);

export function LazyGraphPage() {
  const { t } = useTranslation();
  return (
    <Suspense
      fallback={
        <div className="settings-stack">
          <div className="flex items-center gap-3 px-3 py-12 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden />
            {t("settings.knowledge.graphLoading", { defaultValue: "Drawing the graph…" })}
          </div>
        </div>
      }
    >
      <GraphPage />
    </Suspense>
  );
}
