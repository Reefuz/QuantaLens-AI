"use client";

import { useEffect, useRef } from "react";

/** Calls `fn` every `intervalMs` while `enabled`. Never overlaps calls; stops on unmount. */
export function usePolling(fn: () => Promise<void>, enabled: boolean, intervalMs = 1500) {
  const saved = useRef(fn);
  useEffect(() => {
    saved.current = fn;
  });
  useEffect(() => {
    if (!enabled) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        await saved.current();
      } catch {
        /* transient errors: try again on the next tick */
      }
      if (!stopped) timer = setTimeout(tick, intervalMs);
    };
    timer = setTimeout(tick, intervalMs);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [enabled, intervalMs]);
}
