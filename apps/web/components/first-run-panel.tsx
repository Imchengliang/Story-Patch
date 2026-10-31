"use client";

import type { FormEvent } from "react";
import { useState } from "react";

import { API_URL } from "@/lib/api";
import { copy, samples, type Language } from "@/lib/copy";
import type { ThreadOut } from "@/lib/types";

function splitList(value: string): string[] {
  return value
    .split(/[,，\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function splitLines(value: string): string[] {
  return value
    .split(/\n/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function FirstRunPanel({
  language,
  onStarted,
}: {
  language: Language;
  onStarted: (threadId: string, runId: string) => void;
}) {
  const t = copy[language];
  const sample = samples[language];
  const [storyState, setStoryState] = useState(sample.story);
  const [question, setQuestion] = useState(sample.question);
  const [genre, setGenre] = useState(sample.genre);
  const [characters, setCharacters] = useState(sample.characters);
  const [constraints, setConstraints] = useState(sample.constraints);
  const [desiredEffect, setDesiredEffect] = useState(sample.desiredEffect);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!storyState.trim() || !question.trim()) {
      setError(t.firstRunMissing);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const names = splitList(characters);
      const created = await fetch(`${API_URL}/v1/threads`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: question.slice(0, 80),
          story_state: storyState,
          language: language === "zh" ? "zh" : "en",
          characters: names.map((name) => ({ name, function: "other" })),
        }),
      });
      if (!created.ok) {
        const detail = (await created.json().catch(() => ({}))) as { detail?: string };
        throw new Error(detail.detail ?? `HTTP ${created.status}`);
      }
      const thread = (await created.json()) as ThreadOut;

      const turn = await fetch(`${API_URL}/v1/threads/${thread.id}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          content: question,
          story_state: storyState,
          stuck_question: question,
          genre,
          characters: names,
          constraints: splitLines(constraints),
          desired_effect: desiredEffect,
        }),
      });
      if (!turn.ok) {
        const detail = (await turn.json().catch(() => ({}))) as { detail?: string };
        throw new Error(detail.detail ?? `HTTP ${turn.status}`);
      }
      const accepted = (await turn.json()) as { run_id: string };
      onStarted(thread.id, accepted.run_id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setLoading(false);
    }
  }

  return (
    <section className="space-y-10">
      <form
        onSubmit={handleSubmit}
        className="border border-[var(--border)] bg-[var(--surface-2)] p-3 sm:p-4"
      >
        <div className="grid items-start gap-3 md:grid-cols-[minmax(0,0.98fr)_minmax(0,0.92fr)]">
          <div className="paper-panel p-6 pl-14 sm:p-8 sm:pl-16">
            <div className="relative z-10 flex items-center justify-between font-mono text-[12px] uppercase tracking-[0.16em] text-[var(--muted-soft)]">
              <span>{t.pageLabel}</span>
              <span>{t.draftLabel}</span>
            </div>
            <p className="relative z-10 mt-4 max-w-sm font-display text-sm italic leading-6 text-[var(--muted-soft)]">
              {t.pageHint}
            </p>

            <div className="relative z-10 mt-7 space-y-6">
              <label className="block">
                <span className="font-mono text-[11px] uppercase tracking-[0.16em] text-[var(--muted-soft)]">
                  {t.storyState}
                </span>
                <textarea
                  value={storyState}
                  onChange={(event) => setStoryState(event.target.value)}
                  rows={5}
                  className="mt-2 w-full resize-y border-0 border-b border-[var(--border)] bg-transparent px-0 py-2 font-display text-[17px] leading-8 text-[var(--paper-text)] outline-none focus:border-[var(--accent)]"
                />
              </label>

              <label className="block">
                <span className="font-mono text-[11px] uppercase tracking-[0.16em] text-[var(--muted-soft)]">
                  {t.stuckQuestion}
                </span>
                <textarea
                  value={question}
                  onChange={(event) => setQuestion(event.target.value)}
                  rows={2}
                  className="mt-2 w-full resize-none border-0 border-b border-[var(--border)] bg-transparent px-0 py-2 font-display text-[16px] leading-7 text-[var(--paper-text)] outline-none focus:border-[var(--accent)]"
                />
              </label>

              <div className="grid gap-5 sm:grid-cols-2">
                <label className="block">
                  <span className="font-mono text-[11px] uppercase tracking-[0.16em] text-[var(--muted-soft)]">
                    {t.genre}
                  </span>
                  <input
                    value={genre}
                    onChange={(event) => setGenre(event.target.value)}
                    className="mt-2 w-full border-0 border-b border-[var(--border)] bg-transparent px-0 py-2 text-sm text-[var(--paper-text)] outline-none focus:border-[var(--accent)]"
                  />
                </label>
                <label className="block">
                  <span className="font-mono text-[11px] uppercase tracking-[0.16em] text-[var(--muted-soft)]">
                    {t.characters}
                  </span>
                  <input
                    value={characters}
                    onChange={(event) => setCharacters(event.target.value)}
                    className="mt-2 w-full border-0 border-b border-[var(--border)] bg-transparent px-0 py-2 text-sm text-[var(--paper-text)] outline-none focus:border-[var(--accent)]"
                  />
                </label>
              </div>

              <label className="block">
                <span className="font-mono text-[11px] uppercase tracking-[0.16em] text-[var(--muted-soft)]">
                  {t.constraints}
                </span>
                <textarea
                  value={constraints}
                  onChange={(event) => setConstraints(event.target.value)}
                  rows={3}
                  className="mt-2 w-full resize-y border-0 border-b border-[var(--border)] bg-transparent px-0 py-2 text-[13px] leading-7 text-[var(--paper-text)] outline-none focus:border-[var(--accent)]"
                />
              </label>

              <label className="block">
                <span className="font-mono text-[11px] uppercase tracking-[0.16em] text-[var(--muted-soft)]">
                  {t.desiredEffect}
                </span>
                <textarea
                  value={desiredEffect}
                  onChange={(event) => setDesiredEffect(event.target.value)}
                  rows={2}
                  className="mt-2 w-full resize-none border-0 border-b border-[var(--border)] bg-transparent px-0 py-2 text-sm leading-6 text-[var(--paper-text)] outline-none focus:border-[var(--accent)]"
                />
              </label>
            </div>
          </div>

          <div className="flex flex-col p-4 sm:p-6">
            <div className="flex items-center justify-between font-mono text-[12px] uppercase tracking-[0.16em] text-[var(--muted)]">
              <span>{t.deskLabel}</span>
              <span>{t.sessionLabel}</span>
            </div>

            <p className="mt-6 text-[12px] leading-6 text-[var(--muted-soft)]">{t.firstRunDeskHint}</p>

            <ol className="mt-6 space-y-1.5">
              {(["parse", "embed", "retrieve", "suggest"] as const).map((key) => (
                <li key={key} className="flex items-center gap-3">
                  <span className="h-1 w-1 rounded-full bg-[var(--border-strong)]" />
                  <span className="font-mono text-[11px] uppercase tracking-[0.16em] text-[var(--muted-soft)]">
                    {t.stages[key]}
                  </span>
                </li>
              ))}
            </ol>

            <button
              type="submit"
              disabled={loading}
              className="mt-6 w-full border border-[var(--accent)] bg-[var(--accent)] px-4 py-3 font-mono text-[11px] uppercase tracking-[0.18em] text-[var(--accent-contrast)] transition hover:opacity-90 disabled:opacity-50"
            >
              {loading ? t.startingSession : t.startSession}
            </button>

            {error ? (
              <p className="mt-4 border-l-2 border-[var(--accent)] bg-[var(--surface-2)] px-3 py-2 text-sm leading-6 text-[var(--accent)]">
                {error}
              </p>
            ) : null}
          </div>
        </div>
      </form>
    </section>
  );
}
