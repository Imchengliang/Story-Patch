"use client";

import { useState } from "react";

import { API_URL } from "@/lib/api";
import type { Copy } from "@/lib/copy";
import type {
  BeatSequence,
  FeedbackSummary,
  Precedent,
  StuckPoint,
  Suggestion,
} from "@/lib/types";

const FEEDBACK_REASON_VALUES = [
  "structure_mismatch",
  "character_mismatch",
  "world_conflict",
  "cliche",
  "low_novelty",
  "other",
] as const;

const DECISIONS = ["adopt", "modify", "reject"] as const;

function decisionLabel(value: string, t: Copy): string {
  if (value === "adopt") return t.accept;
  if (value === "modify") return t.modify;
  return t.reject;
}

export function StuckPointSummary({
  stuck,
  t,
  heading = t.stuckParse,
}: {
  stuck: StuckPoint;
  t: Copy;
  heading?: string;
}) {
  return (
    <section className="border border-[var(--border)] bg-[var(--surface)] p-6 sm:p-7">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="font-mono text-[12px] uppercase tracking-[0.16em] text-[var(--accent)]">
          {heading}
        </h3>
        <div className="flex flex-wrap gap-2 font-mono text-[11px] uppercase tracking-[0.14em] text-[var(--muted)]">
          {stuck.narrative_functions.map((item) => (
            <span key={item} className="border border-[var(--border)] px-2 py-1">
              {item}
            </span>
          ))}
          <span className="border border-[var(--border)] px-2 py-1">
            {t.valueLabel}: {stuck.value_polarity}
          </span>
        </div>
      </div>
      <p className="mt-4 max-w-3xl font-display text-xl leading-8 text-[var(--text)]">
        {stuck.current_node}
      </p>
      <div className="mt-4 flex flex-wrap gap-2 font-mono text-[11px] uppercase tracking-[0.14em] text-[var(--muted)]">
        {stuck.characters.map((item) => (
          <span key={`${item.name}-${item.function}`} className="border border-[var(--border)] px-2 py-1">
            {item.name} · {item.function}
          </span>
        ))}
      </div>
    </section>
  );
}

export function StoryFacts({
  facts,
  status,
  t,
}: {
  facts: string[];
  status?: "ready" | "building" | "absent";
  t: Copy;
}) {
  if (status === "absent") return null;
  return (
    <section>
      <h3 className="font-mono text-[12px] uppercase tracking-[0.16em] text-[var(--muted)]">
        {t.storyFacts}
      </h3>
      {status === "building" ? (
        <p className="mt-3 text-[12px] leading-6 text-[var(--muted-soft)]">{t.storyBuilding}</p>
      ) : facts.length > 0 ? (
        <ul className="mt-3 space-y-1 border-l border-[var(--border)] pl-4 text-[12px] leading-6 text-[var(--muted)]">
          {facts.map((fact) => (
            <li key={fact}>{fact}</li>
          ))}
        </ul>
      ) : (
        <p className="mt-3 text-[12px] leading-6 text-[var(--muted-soft)]">{t.storyEmpty}</p>
      )}
    </section>
  );
}

export function PrecedentStrip({
  precedents,
  t,
}: {
  precedents: Precedent[];
  t: Copy;
}) {
  if (precedents.length === 0) return null;
  return (
    <section>
      <h3 className="font-mono text-[12px] uppercase tracking-[0.16em] text-[var(--muted)]">
        {t.precedentsTitle}
      </h3>
      <div className="mt-3 flex gap-3 overflow-x-auto pb-2">
        {precedents.map((item, index) => (
          <article
            key={`${item.work_title}-${item.scene_heading}-${index}`}
            className="min-w-[240px] flex-1 border border-[var(--border)] bg-[var(--surface)] p-4"
          >
            <div className="flex items-center justify-between font-mono text-[11px] uppercase tracking-[0.16em] text-[var(--muted-soft)]">
              <span>SC. {String(index + 1).padStart(2, "0")}</span>
              <span className={index === 0 ? "text-[var(--accent)]" : ""}>
                {t.totalScore} {item.score.toFixed(2)}
              </span>
            </div>
            <h4 className="mt-3 font-display text-lg leading-6 text-[var(--text)]">
              {item.work_title}
            </h4>
            <p className="mt-1 font-mono text-[11px] text-[var(--muted-soft)]">{item.scene_heading}</p>
            {item.excerpt ? (
              <p className="mt-3 font-mono text-[10px] uppercase tracking-[0.16em] text-[var(--muted-soft)]">
                {t.excerpt}
              </p>
            ) : null}
            {item.excerpt ? (
              <p className="mt-1 max-h-40 overflow-hidden text-[12px] leading-6 text-[var(--muted)]">
                {item.highlight && item.excerpt.includes(item.highlight) ? (
                  <>
                    {item.excerpt.slice(0, item.excerpt.indexOf(item.highlight))}
                    <mark className="bg-transparent text-[var(--text)] underline decoration-[var(--accent)] decoration-2 underline-offset-4">
                      {item.highlight}
                    </mark>
                    {item.excerpt.slice(item.excerpt.indexOf(item.highlight) + item.highlight.length)}
                  </>
                ) : (
                  item.excerpt
                )}
              </p>
            ) : null}
            {item.reasons.length > 0 ? (
              <p className="mt-2 text-[11px] leading-5 text-[var(--muted-soft)]">
                {item.reasons.join(" · ")}
              </p>
            ) : null}
          </article>
        ))}
      </div>
    </section>
  );
}

export function SuggestionCard({
  suggestion,
  index,
  stuckQuestion,
  runId,
  sceneId,
  initialBeats,
  t,
  onFeedback,
  onExpand,
}: {
  suggestion: Suggestion;
  index: number;
  stuckQuestion: string;
  runId?: string | null;
  sceneId?: string;
  initialBeats?: BeatSequence | null;
  t: Copy;
  onFeedback: (
    suggestion: Suggestion,
    decision: string,
    reason: string,
    runId?: string | null,
  ) => Promise<void>;
  onExpand?: (
    suggestion: Suggestion,
    sceneId: string,
    runId?: string | null,
  ) => Promise<BeatSequence | null>;
}) {
  const [decision, setDecision] = useState<string>("adopt");
  const [reason, setReason] = useState<string>("other");
  const [pending, setPending] = useState(false);
  const [beats, setBeats] = useState<BeatSequence | null>(initialBeats ?? null);
  const [expanding, setExpanding] = useState(false);

  async function submit() {
    setPending(true);
    try {
      await onFeedback(suggestion, decision, reason, runId);
    } finally {
      setPending(false);
    }
  }

  async function expand() {
    if (!onExpand || !sceneId) return;
    setExpanding(true);
    try {
      const sequence = await onExpand(suggestion, sceneId, runId);
      if (sequence) setBeats(sequence);
    } finally {
      setExpanding(false);
    }
  }

  return (
    <article className="grid gap-5 py-8 lg:grid-cols-[52px_minmax(0,1fr)]">
      <div className="font-display text-3xl leading-none text-[var(--muted-soft)]">
        {String(index + 1).padStart(2, "0")}
      </div>
      <div>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <h4 className="max-w-3xl font-display text-[22px] leading-8 text-[var(--text)]">
            {suggestion.next_node}
          </h4>
          <div className="flex gap-4 font-mono text-[12px] uppercase tracking-[0.16em] text-[var(--muted)]">
            <span>
              {t.fit} {suggestion.fit_score.toFixed(2)}
            </span>
            <span>
              {t.novelty} {suggestion.novelty_score.toFixed(2)}
            </span>
          </div>
        </div>

        <dl className="mt-5 grid gap-4 sm:grid-cols-3">
          <div>
            <dt className="font-mono text-[12px] uppercase tracking-[0.16em] text-[var(--muted-soft)]">
              {t.behaviorLogic}
            </dt>
            <dd className="mt-1.5 text-[13px] leading-6 text-[var(--muted)]">
              {suggestion.character_behavior_logic}
            </dd>
          </div>
          <div>
            <dt className="font-mono text-[12px] uppercase tracking-[0.16em] text-[var(--muted-soft)]">
              {t.tone}
            </dt>
            <dd className="mt-1.5 text-[13px] leading-6 text-[var(--muted)]">
              {suggestion.emotional_tone}
            </dd>
          </div>
          <div>
            <dt className="font-mono text-[12px] uppercase tracking-[0.16em] text-[var(--muted-soft)]">
              {t.transferRationale}
            </dt>
            <dd className="mt-1.5 text-[13px] leading-6 text-[var(--muted)]">
              {suggestion.transfer_rationale}
            </dd>
          </div>
        </dl>

        <figure className="mt-5 border-l-2 border-[var(--accent)] bg-[var(--surface-2)] p-4 text-[var(--paper-text)]">
          <blockquote className="font-display text-[15px] leading-7">
            {suggestion.reference_quote ?? t.noQuote}
          </blockquote>
          <figcaption className="mt-2 font-mono text-[11px] uppercase tracking-[0.14em] text-[var(--muted-soft)]">
            {t.source}: {suggestion.corpus_reference}
          </figcaption>
        </figure>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <div className="flex border border-[var(--border-strong)]">
            {DECISIONS.map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => setDecision(value)}
                className={`px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.14em] transition ${
                  decision === value
                    ? "bg-[var(--text)] text-[var(--accent-contrast)]"
                    : "text-[var(--muted)] hover:text-[var(--text)]"
                }`}
              >
                {decisionLabel(value, t)}
              </button>
            ))}
          </div>
          <select
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            className="border border-[var(--border-strong)] bg-[var(--bg)] px-2 py-1.5 font-mono text-[11px] uppercase tracking-[0.12em] text-[var(--muted)] outline-none focus:border-[var(--accent)]"
          >
            {FEEDBACK_REASON_VALUES.map((value) => (
              <option key={value} value={value}>
                {t.reasonLabels[value]}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={submit}
            disabled={pending}
            className="border border-[var(--accent)] px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.14em] text-[var(--accent)] transition hover:bg-[var(--accent)] hover:text-[var(--accent-contrast)] disabled:opacity-50"
          >
            {pending ? t.recording : t.record}
          </button>
          {onExpand && sceneId && (decision === "adopt" || decision === "modify") ? (
            <button
              type="button"
              onClick={expand}
              disabled={expanding}
              className="border border-[var(--border-strong)] px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.14em] text-[var(--muted)] transition hover:text-[var(--text)] disabled:opacity-50"
            >
              {expanding ? t.expandingBeats : t.expandBeats}
            </button>
          ) : null}
          <span className="ml-auto font-mono text-[11px] text-[var(--muted-soft)]">
            {t.stuckLabel}: {stuckQuestion}
          </span>
        </div>

        {beats ? (
          <div className="mt-5 border-t border-[var(--border)] pt-4">
            <ol className="space-y-3">
              {beats.beats.map((beat) => (
                <li key={beat.index} className="grid gap-2 sm:grid-cols-[32px_minmax(0,1fr)]">
                  <span className="font-display text-lg leading-6 text-[var(--muted-soft)]">
                    {String(beat.index).padStart(2, "0")}
                  </span>
                  <div>
                    <p className="font-display text-[15px] leading-6 text-[var(--text)]">
                      {beat.next_node}
                    </p>
                    <p className="mt-1 text-[12px] leading-5 text-[var(--muted)]">
                      {beat.character_behavior_logic} · {beat.emotional_tone}
                    </p>
                    {beat.reference_quote ? (
                      <blockquote className="mt-1 border-l-2 border-[var(--accent)] pl-3 text-[12px] leading-5 text-[var(--muted-soft)]">
                        {beat.reference_quote}
                      </blockquote>
                    ) : null}
                  </div>
                </li>
              ))}
            </ol>
            {beats.risk ? (
              <p className="mt-3 text-[12px] leading-5 text-[var(--muted)]">
                {t.beatRisk}: {beats.risk}
              </p>
            ) : null}
            {beats.still_unresolved ? (
              <p className="mt-1 text-[12px] leading-5 text-[var(--muted)]">
                {t.beatUnresolved}: {beats.still_unresolved}
              </p>
            ) : null}
          </div>
        ) : null}
      </div>
    </article>
  );
}

export function SuggestionList({
  suggestions,
  stuckQuestion,
  runId,
  precedents,
  beats,
  t,
  feedback,
  onFeedback,
  onExpand,
  emptyLabel,
}: {
  suggestions: Suggestion[];
  stuckQuestion: string;
  runId?: string | null;
  precedents: Precedent[];
  beats?: Array<BeatSequence | null>;
  t: Copy;
  feedback: FeedbackSummary | null;
  onFeedback: (
    suggestion: Suggestion,
    decision: string,
    reason: string,
    runId?: string | null,
  ) => Promise<void>;
  onExpand?: (
    suggestion: Suggestion,
    sceneId: string,
    runId?: string | null,
  ) => Promise<BeatSequence | null>;
  emptyLabel?: string;
}) {
  return (
    <section>
      <div className="flex flex-wrap items-end justify-between gap-2 border-b border-[var(--border)] pb-3">
        <h3 className="font-mono text-[12px] uppercase tracking-[0.16em] text-[var(--muted)]">
          {t.coverageNotes}
        </h3>
        <div className="flex items-center gap-4 font-mono text-[11px] uppercase tracking-[0.14em] text-[var(--muted)]">
          {feedback ? (
            <span>
              {t.feedbackSummary(feedback.total, Math.round(feedback.adoption_rate * 100))}
            </span>
          ) : null}
          <span>{suggestions.length} ×</span>
        </div>
      </div>
      {suggestions.length === 0 && emptyLabel ? (
        <p className="mt-3 text-[12px] leading-6 text-[var(--muted-soft)]">{emptyLabel}</p>
      ) : null}
      <div className="divide-y divide-[var(--border)]">
        {suggestions.map((suggestion, index) => (
          <SuggestionCard
            key={`${suggestion.corpus_reference}-${index}`}
            suggestion={suggestion}
            index={index}
            stuckQuestion={stuckQuestion}
            runId={runId}
            sceneId={
              precedents.find(
                (item) => `${item.work_title} · ${item.scene_heading}` === suggestion.corpus_reference,
              )?.scene_id
            }
            initialBeats={beats?.[index] ?? null}
            t={t}
            onFeedback={onFeedback}
            onExpand={onExpand}
          />
        ))}
      </div>
    </section>
  );
}
