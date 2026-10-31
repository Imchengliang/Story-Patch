"use client";

import { useState } from "react";

import { API_URL } from "@/lib/api";
import type { Copy } from "@/lib/copy";
import type { StuckPoint, ThreadOut } from "@/lib/types";

function lines(value: string): string[] {
  return value
    .split(/\n/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function StuckEditor({
  threadId,
  stuck,
  t,
  onSaved,
}: {
  threadId: string;
  stuck: StuckPoint;
  t: Copy;
  onSaved: (stuck: StuckPoint) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [question, setQuestion] = useState(stuck.stuck_question);
  const [currentNode, setCurrentNode] = useState(stuck.current_node);
  const [genre, setGenre] = useState(stuck.genre);
  const [constraints, setConstraints] = useState(stuck.constraints.join("\n"));
  const [desiredEffect, setDesiredEffect] = useState(stuck.desired_effect);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function save() {
    setPending(true);
    setMessage(null);
    const patch: Record<string, unknown> = {};
    if (question !== stuck.stuck_question) patch.stuck_question = question;
    if (currentNode !== stuck.current_node) patch.current_node = currentNode;
    if (genre !== stuck.genre) patch.genre = genre;
    if (desiredEffect !== stuck.desired_effect) patch.desired_effect = desiredEffect;
    if (constraints !== stuck.constraints.join("\n")) patch.constraints = lines(constraints);
    if (Object.keys(patch).length === 0) {
      setEditing(false);
      setPending(false);
      return;
    }
    try {
      const response = await fetch(`${API_URL}/v1/threads/${threadId}/stuck-point`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      if (!response.ok) {
        const detail = (await response.json().catch(() => ({}))) as { detail?: string };
        throw new Error(detail.detail ?? `HTTP ${response.status}`);
      }
      const thread = (await response.json()) as ThreadOut;
      if (thread.active_stuck) onSaved(thread.active_stuck);
      setMessage(t.stuckSaved);
      setEditing(false);
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setPending(false);
    }
  }

  return (
    <section className="border border-[var(--border)] bg-[var(--surface)] p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="font-mono text-[12px] uppercase tracking-[0.16em] text-[var(--accent)]">
          {t.currentStuck}
        </h3>
        <button
          type="button"
          onClick={() => setEditing((value) => !value)}
          className="border border-[var(--border-strong)] px-2.5 py-1 font-mono text-[11px] uppercase tracking-[0.14em] text-[var(--muted)] transition hover:text-[var(--text)]"
        >
          {editing ? t.cancel : t.editStuck}
        </button>
      </div>

      {!editing ? (
        <div className="mt-4 space-y-3">
          <p className="font-display text-lg leading-7 text-[var(--text)]">{stuck.stuck_question}</p>
          <p className="text-[13px] leading-6 text-[var(--muted)]">{stuck.current_node}</p>
          <div className="flex flex-wrap gap-2 font-mono text-[11px] uppercase tracking-[0.14em] text-[var(--muted)]">
            {stuck.characters.map((item) => (
              <span key={`${item.name}-${item.function}`} className="border border-[var(--border)] px-2 py-1">
                {item.name} · {item.function}
              </span>
            ))}
          </div>
          {stuck.constraints.length > 0 ? (
            <ul className="space-y-1 border-l border-[var(--border)] pl-4 text-[12px] leading-6 text-[var(--muted-soft)]">
              {stuck.constraints.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : (
        <div className="mt-4 space-y-4">
          <label className="block">
            <span className="font-mono text-[11px] uppercase tracking-[0.16em] text-[var(--muted-soft)]">
              {t.stuckQuestion}
            </span>
            <textarea
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              rows={2}
              className="mt-1.5 w-full border border-[var(--border-strong)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)]"
            />
          </label>
          <label className="block">
            <span className="font-mono text-[11px] uppercase tracking-[0.16em] text-[var(--muted-soft)]">
              {t.currentNode}
            </span>
            <textarea
              value={currentNode}
              onChange={(event) => setCurrentNode(event.target.value)}
              rows={2}
              className="mt-1.5 w-full border border-[var(--border-strong)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)]"
            />
          </label>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block">
              <span className="font-mono text-[11px] uppercase tracking-[0.16em] text-[var(--muted-soft)]">
                {t.genre}
              </span>
              <input
                value={genre}
                onChange={(event) => setGenre(event.target.value)}
                className="mt-1.5 w-full border border-[var(--border-strong)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)]"
              />
            </label>
            <label className="block">
              <span className="font-mono text-[11px] uppercase tracking-[0.16em] text-[var(--muted-soft)]">
                {t.desiredEffect}
              </span>
              <input
                value={desiredEffect}
                onChange={(event) => setDesiredEffect(event.target.value)}
                className="mt-1.5 w-full border border-[var(--border-strong)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)]"
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
              className="mt-1.5 w-full border border-[var(--border-strong)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)]"
            />
          </label>
          <button
            type="button"
            onClick={save}
            disabled={pending}
            className="border border-[var(--accent)] px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.14em] text-[var(--accent)] transition hover:bg-[var(--accent)] hover:text-[var(--accent-contrast)] disabled:opacity-50"
          >
            {pending ? t.savingStuck : t.saveStuck}
          </button>
        </div>
      )}

      {message ? (
        <p className="mt-3 border-l-2 border-[var(--success)] bg-[var(--success-bg)] px-3 py-2 text-[12px] text-[var(--success)]">
          {message}
        </p>
      ) : null}
    </section>
  );
}
