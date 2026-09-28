import { useCallback, useEffect, useState } from "react";

import { ApiError, fetchKnowledge } from "@/lib/api";
import type { KnowledgeIndex } from "@/lib/types";
import { useClient } from "@/providers/ClientProvider";

export interface KnowledgeState {
  index: KnowledgeIndex | null;
  loading: boolean;
  /** The vault has never been created. A setup step, not a failure. */
  missing: boolean;
  /** The gateway's own message, kept verbatim so the empty state can show the
   * path and the command it named rather than a copy that would drift. */
  error: string | null;
  reload: () => void;
}

/**
 * Read the vault index once and hand it to whichever knowledge page is open.
 *
 * The two pages fetch the same payload on purpose. The browse page groups these
 * rows and the graph page draws edges between them, and a second endpoint would
 * only be a second chance for the two to disagree about what is in the vault.
 * The gateway caches the scan behind a vault fingerprint, so a page switch
 * costs a request but not a re-read of 85 files.
 */
export function useKnowledgeIndex(): KnowledgeState {
  const { getToken } = useClient();
  const [index, setIndex] = useState<KnowledgeIndex | null>(null);
  const [loading, setLoading] = useState(true);
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Bumped by the retry button; the effect owns the fetch so its cleanup can
  // cancel a response that arrives after the page is gone.
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchKnowledge(getToken())
      .then((next) => {
        if (cancelled) return;
        setIndex(next);
        setMissing(false);
        setError(null);
      })
      .catch((reason: unknown) => {
        if (cancelled) return;
        setError(reason instanceof Error ? reason.message : String(reason));
        setMissing(reason instanceof ApiError && reason.status === 404);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [getToken, reloadToken]);

  const reload = useCallback(() => setReloadToken((value) => value + 1), []);

  return { index, loading, missing, error, reload };
}
