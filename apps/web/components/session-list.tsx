"use client";

import { useEffect, useState } from "react";

import { API_URL } from "@/lib/api";
import { copy, type Language } from "@/lib/copy";
import type { ThreadOut } from "@/lib/types";

export function SessionList({
  language,
  onOpen,
}: {
  language: Language;
  onOpen: (threadId: string) => void;
}) {
  const t = copy[language];
  const [threads, setThreads] = useState<ThreadOut[]>([]);

  useEffect(() => {
    let cancelled = false;
    fetch(`${API_URL}/v1/threads`)
      .then((response) => (response.ok ? response.json() : []))
      .then((data: ThreadOut[]) => {
        if (!cancelled) setThreads(data);
      })
      .catch(() => {
        if (!cancelled) setThreads([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function archive(threadId: string) {
    const response = await fetch(`${API_URL}/v1/threads/${threadId}`, { method: "DELETE" });
    if (response.ok) {
      setThreads((prev) => prev.filter((thread) => thread.id !== threadId));
    }
  }

  if (threads.length === 0) return null;

  return (
    <section className="mb-6 border border-[var(--border)] bg-[var(--surface)] p-5">
      <h3 className="font-mono text-[12px] uppercase tracking-[0.16em] text-[var(--muted)]">
        {t.historyLabel}
      </h3>
      <ul className="mt-3 divide-y divide-[var(--border)]">
        {threads.map((thread) => (
          <li key={thread.id} className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => onOpen(thread.id)}
              className="flex flex-1 items-baseline justify-between gap-4 py-2 text-left transition hover:text-[var(--accent)]"
            >
              <span className="truncate font-display text-[15px] text-[var(--text)]">
                {thread.title || t.untitledSession}
              </span>
              <span className="shrink-0 font-mono text-[11px] uppercase tracking-[0.12em] text-[var(--muted-soft)]">
                {new Date(thread.updated_at).toLocaleDateString()}
              </span>
            </button>
            <button
              type="button"
              onClick={() => archive(thread.id)}
              className="shrink-0 border border-[var(--border)] px-2 py-1 font-mono text-[10px] uppercase tracking-[0.12em] text-[var(--muted-soft)] transition hover:text-[var(--accent)]"
            >
              {t.archive}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
