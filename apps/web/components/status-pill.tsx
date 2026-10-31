"use client";

import { useEffect, useState } from "react";

import { API_URL } from "@/lib/api";
import { copy, type Language } from "@/lib/copy";

type Status = "checking" | "ok" | "offline";

export function StatusPill({ language }: { language: Language }) {
  const [status, setStatus] = useState<Status>("checking");
  const t = copy[language];

  useEffect(() => {
    let cancelled = false;

    fetch(`${API_URL}/v1/health`)
      .then((response) => {
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        return response.json() as Promise<{ status: string }>;
      })
      .then((data) => {
        if (!cancelled) {
          setStatus(data.status === "ok" ? "ok" : "offline");
        }
      })
      .catch(() => {
        if (!cancelled) {
          setStatus("offline");
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const label =
    status === "ok"
      ? t.statusOk
      : status === "offline"
        ? t.statusOffline
        : t.statusChecking;
  const dot =
    status === "ok"
      ? "bg-emerald-500"
      : status === "offline"
        ? "bg-[var(--accent)]"
        : "bg-[var(--muted)]";

  return (
    <span className="flex items-center gap-2 font-mono text-[12px] uppercase tracking-[0.16em] text-[var(--muted)]">
      <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
      {label}
    </span>
  );
}
