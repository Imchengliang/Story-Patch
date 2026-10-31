"use client";

import type { Copy } from "@/lib/copy";
import type { BeatSequence, FeedbackSummary, MessageOut, Suggestion } from "@/lib/types";
import {
  PrecedentStrip,
  StoryFacts,
  StuckPointSummary,
  SuggestionList,
} from "@/components/result-blocks";

export function MessageList({
  messages,
  t,
  feedback,
  onFeedback,
  onReplay,
  onExpand,
}: {
  messages: MessageOut[];
  t: Copy;
  feedback: FeedbackSummary | null;
  onFeedback: (
    suggestion: Suggestion,
    decision: string,
    reason: string,
    runId?: string | null,
  ) => Promise<void>;
  onReplay?: (runId: string) => void;
  onExpand?: (
    suggestion: Suggestion,
    sceneId: string,
    runId?: string | null,
  ) => Promise<BeatSequence | null>;
}) {
  if (messages.length === 0) {
    return <p className="text-[13px] leading-6 text-[var(--muted-soft)]">{t.noMessages}</p>;
  }

  return (
    <div className="space-y-8">
      {messages.map((message) => {
        if (message.role === "user") {
          return (
            <article key={message.id} className="border-l-2 border-[var(--accent)] pl-4">
              <p className="font-mono text-[11px] uppercase tracking-[0.16em] text-[var(--accent)]">
                {t.userLabel} · {String(message.seq).padStart(2, "0")}
              </p>
              <p className="mt-2 font-display text-[19px] leading-8 text-[var(--text)]">
                {message.content}
              </p>
            </article>
          );
        }
        const payload = message.payload;
        if (!payload) {
          return (
            <article key={message.id} className="border-l border-[var(--border)] pl-4">
              <p className="font-mono text-[11px] uppercase tracking-[0.16em] text-[var(--muted-soft)]">
                {t.assistantLabel} · {String(message.seq).padStart(2, "0")}
              </p>
            </article>
          );
        }
        return (
          <article key={message.id} className="space-y-6 border-l border-[var(--border)] pl-4">
            <div className="flex items-center justify-between gap-3">
              <p className="font-mono text-[11px] uppercase tracking-[0.16em] text-[var(--muted-soft)]">
                {t.assistantLabel} · {String(message.seq).padStart(2, "0")}
                {message.run_id ? ` · run ${message.run_id.slice(0, 8)}` : ""}
              </p>
              {message.run_id && onReplay ? (
                <button
                  type="button"
                  onClick={() => onReplay(message.run_id as string)}
                  className="border border-[var(--border-strong)] px-2 py-1 font-mono text-[10px] uppercase tracking-[0.14em] text-[var(--muted)] transition hover:text-[var(--text)]"
                >
                  {t.replay}
                </button>
              ) : null}
            </div>
            {payload.error ? (
              <p className="border-l-2 border-[var(--accent)] bg-[var(--surface-2)] px-3 py-2 text-sm leading-6 text-[var(--accent)]">
                {payload.error}
              </p>
            ) : null}
            {payload.stuck_point ? <StuckPointSummary stuck={payload.stuck_point} t={t} /> : null}
            {(payload.story_facts?.length ?? 0) > 0 ? (
              <StoryFacts facts={payload.story_facts ?? []} t={t} />
            ) : null}
            <PrecedentStrip precedents={payload.precedents ?? []} t={t} />
            <SuggestionList
              suggestions={payload.suggestions ?? []}
              stuckQuestion={payload.stuck_point?.stuck_question ?? ""}
              runId={message.run_id}
              precedents={payload.precedents ?? []}
              beats={payload.beats ?? []}
              t={t}
              feedback={feedback}
              onFeedback={onFeedback}
              onExpand={onExpand}
              emptyLabel={t.noSuggestions}
            />
          </article>
        );
      })}
    </div>
  );
}
