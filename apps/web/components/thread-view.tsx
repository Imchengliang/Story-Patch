"use client";

import type { FormEvent } from "react";
import { useCallback, useEffect, useRef, useState } from "react";

import { MessageList } from "@/components/message-list";
import { PrecedentStrip, SuggestionList } from "@/components/result-blocks";
import { StuckEditor } from "@/components/stuck-editor";
import { API_URL } from "@/lib/api";
import { copy, type Language } from "@/lib/copy";
import { SseHttpError, streamSse, type SseEvent } from "@/lib/sse";
import type {
  BeatSequence,
  BudgetEvent,
  BudgetLimits,
  FeedbackSummary,
  LiveRun,
  MessageOut,
  ReplayReport,
  StuckPoint,
  SuggestResult,
  Suggestion,
  ThreadDetail,
  ThreadUsage,
  UsageSnapshot,
} from "@/lib/types";

const STAGE_KEYS = ["ingest", "parse", "embed", "retrieve", "suggest"] as const;

const EMPTY_LIVE: LiveRun = {
  runId: null,
  plan: [],
  stage: null,
  stuck: null,
  precedents: [],
  suggestions: [],
  storyFacts: [],
  usage: null,
  limits: null,
  error: null,
  done: false,
};

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function ThreadView({
  language,
  threadId,
  initialRunId,
  onNewSession,
}: {
  language: Language;
  threadId: string;
  initialRunId?: string | null;
  onNewSession: () => void;
}) {
  const t = copy[language];
  const [detail, setDetail] = useState<ThreadDetail | null>(null);
  const [messages, setMessages] = useState<MessageOut[]>([]);
  const [stuck, setStuck] = useState<StuckPoint | null>(null);
  const [live, setLive] = useState<LiveRun>(EMPTY_LIVE);
  const [usage, setUsage] = useState<ThreadUsage | null>(null);
  const [feedback, setFeedback] = useState<FeedbackSummary | null>(null);
  const [replayReport, setReplayReport] = useState<ReplayReport | null>(null);
  const [composer, setComposer] = useState("");
  const [sending, setSending] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const loadDetail = useCallback(
    async (silent = false): Promise<ThreadDetail | null> => {
      if (!silent) setLoading(true);
      try {
        const response = await fetch(`${API_URL}/v1/threads/${threadId}`);
        if (!response.ok) {
          const body = (await response.json().catch(() => ({}))) as { detail?: string };
          throw new Error(body.detail ?? `HTTP ${response.status}`);
        }
        const next = (await response.json()) as ThreadDetail;
        setDetail(next);
        setMessages(next.messages);
        if (next.thread.active_stuck) setStuck(next.thread.active_stuck);
        return next;
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : String(cause));
        return null;
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [threadId],
  );

  const loadUsage = useCallback(async () => {
    try {
      const response = await fetch(`${API_URL}/v1/threads/${threadId}/usage`);
      if (response.ok) setUsage((await response.json()) as ThreadUsage);
    } catch {
      // usage is informative only
    }
  }, [threadId]);

  const reloadAfterRun = useCallback(
    async (runId: string) => {
      for (let attempt = 0; attempt < 12; attempt += 1) {
        const next = await loadDetail(true);
        const stored = next?.messages.some(
          (message) => message.role === "assistant" && message.run_id === runId,
        );
        if (stored) break;
        await sleep(350);
      }
      await loadUsage();
    },
    [loadDetail, loadUsage],
  );

  const connect = useCallback(
    async (runId: string, expectAssistant = true) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setSending(true);
      setError(null);
      setLive({ ...EMPTY_LIVE, runId });

      const handleEvent = (event: SseEvent) => {
        const data = (event.data ?? {}) as Record<string, unknown>;
        if (event.event === "plan") {
          const steps = (data.steps as Array<{ tool?: string }> | undefined) ?? [];
          setLive((prev) => ({ ...prev, plan: steps.map((step) => step.tool ?? "") }));
        } else if (event.event === "stage") {
          setLive((prev) => ({ ...prev, stage: String(data.stage ?? "") }));
        } else if (event.event === "stuck_point") {
          const next = event.data as StuckPoint;
          setLive((prev) => ({ ...prev, stuck: next }));
          setStuck(next);
        } else if (event.event === "suggestion") {
          const next = event.data as Suggestion;
          setLive((prev) => ({ ...prev, suggestions: [...prev.suggestions, next] }));
        } else if (event.event === "budget") {
          const budget = event.data as BudgetEvent;
          setLive((prev) => ({
            ...prev,
            usage: budget,
            limits: (data.limits as BudgetLimits | undefined) ?? null,
          }));
        } else if (event.event === "result") {
          const result = event.data as SuggestResult;
          setLive((prev) => ({
            ...prev,
            stuck: result.stuck_point ?? prev.stuck,
            precedents: result.precedents ?? [],
            suggestions: result.suggestions ?? [],
            storyFacts: result.story_facts ?? [],
          }));
          if (result.stuck_point) setStuck(result.stuck_point);
        } else if (event.event === "replay") {
          setReplayReport(event.data as ReplayReport);
        } else if (event.event === "error") {
          const message = String(data.detail ?? t.generateFailed);
          setLive((prev) => ({ ...prev, error: message }));
          setError(message);
        } else if (event.event === "done") {
          setLive((prev) => ({
            ...prev,
            done: true,
            error: data.error ? String(data.error) : prev.error,
          }));
          if (expectAssistant) void reloadAfterRun(runId);
        }
      };

      try {
        let attempt = 0;
        while (true) {
          try {
            await streamSse(
              `${API_URL}/v1/threads/${threadId}/events?run_id=${encodeURIComponent(runId)}`,
              handleEvent,
              controller.signal,
            );
            break;
          } catch (cause) {
            if (controller.signal.aborted) return;
            // The background task may not have registered the run yet.
            if (cause instanceof SseHttpError && cause.status === 404 && attempt < 20) {
              attempt += 1;
              await sleep(400);
              continue;
            }
            throw cause;
          }
        }
      } catch (cause) {
        if (!controller.signal.aborted) {
          setError(cause instanceof Error ? cause.message : String(cause));
          if (expectAssistant) await reloadAfterRun(runId);
        }
      } finally {
        if (!controller.signal.aborted) setSending(false);
      }
    },
    [reloadAfterRun, t.generateFailed, threadId],
  );

  const replay = useCallback(
    async (sourceRunId: string) => {
      setError(null);
      setReplayReport(null);
      try {
        const response = await fetch(
          `${API_URL}/v1/threads/${threadId}/replay?source_run_id=${encodeURIComponent(sourceRunId)}`,
          { method: "POST" },
        );
        if (!response.ok) {
          const body = (await response.json().catch(() => ({}))) as { detail?: string };
          throw new Error(body.detail ?? `HTTP ${response.status}`);
        }
        const accepted = (await response.json()) as { run_id: string };
        await connect(accepted.run_id, false);
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : String(cause));
      }
    },
    [connect, threadId],
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const loaded = await loadDetail();
      if (cancelled) return;
      await loadUsage();
      if (initialRunId && loaded) {
        void connect(initialRunId);
      }
    })();
    return () => {
      cancelled = true;
      abortRef.current?.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [threadId]);

  async function send(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    const content = composer.trim();
    if (!content || sending) return;
    setComposer("");
    setError(null);
    try {
      const response = await fetch(`${API_URL}/v1/threads/${threadId}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => ({}))) as { detail?: string };
        throw new Error(body.detail ?? `HTTP ${response.status}`);
      }
      const accepted = (await response.json()) as { run_id: string };
      await loadDetail(true);
      void connect(accepted.run_id);
    } catch (cause) {
      setComposer(content);
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }

  async function handleExpand(
    suggestion: Suggestion,
    sceneId: string,
    runId?: string | null,
  ): Promise<BeatSequence | null> {
    if (!stuck) return null;
    try {
      const response = await fetch(`${API_URL}/v1/plot/beats`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          stuck,
          suggestion,
          scene_id: sceneId,
          thread_id: threadId,
          source_run_id: runId ?? null,
        }),
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => ({}))) as { detail?: string };
        throw new Error(body.detail ?? `HTTP ${response.status}`);
      }
      return (await response.json()) as BeatSequence;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      return null;
    }
  }

  async function handleFeedback(
    suggestion: Suggestion,
    decision: string,
    reason: string,
    runId?: string | null,
  ) {
    try {
      const response = await fetch(`${API_URL}/v1/plot/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          suggestion_id: "",
          decision,
          reason_code: reason,
          note: "",
          stuck_question: stuck?.stuck_question ?? "",
          corpus_reference: suggestion.corpus_reference,
          next_node: suggestion.next_node,
          thread_id: threadId,
          run_id: runId ?? null,
        }),
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => ({}))) as { detail?: string };
        throw new Error(body.detail ?? `HTTP ${response.status}`);
      }
      setFeedback((await response.json()) as FeedbackSummary);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }

  const stageIndex = live.stage
    ? STAGE_KEYS.indexOf(live.stage as (typeof STAGE_KEYS)[number])
    : -1;
  const usageSnapshot: UsageSnapshot | null =
    sending && live.usage ? live.usage : (usage?.thread ?? live.usage);

  if (loading && !detail) {
    return <p className="text-[13px] text-[var(--muted-soft)]">{t.loadingThread}</p>;
  }

  return (
    <section className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
      <div className="space-y-6">
        <div className="flex flex-wrap items-end justify-between gap-3 border-b border-[var(--border)] pb-4">
          <div>
            <p className="font-mono text-[12px] uppercase tracking-[0.18em] text-[var(--accent)]">
              {t.conversationLabel}
            </p>
            <h2 className="mt-1 font-display text-2xl text-[var(--text)]">
              {detail?.thread.title || t.sessionLabel}
            </h2>
          </div>
          <button
            type="button"
            onClick={onNewSession}
            className="border border-[var(--border-strong)] px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.14em] text-[var(--muted)] transition hover:text-[var(--text)]"
          >
            {t.newSession}
          </button>
        </div>

        {stuck ? (
          <StuckEditor
            key={stuck.stuck_question}
            threadId={threadId}
            stuck={stuck}
            t={t}
            onSaved={(next) => setStuck(next)}
          />
        ) : null}

        <MessageList
          messages={messages}
          t={t}
          feedback={feedback}
          onFeedback={handleFeedback}
          onReplay={replay}
          onExpand={handleExpand}
        />

        {error ? (
          <p className="border-l-2 border-[var(--accent)] bg-[var(--surface-2)] px-3 py-2 text-sm leading-6 text-[var(--accent)]">
            {error}
          </p>
        ) : null}

        <form
          onSubmit={send}
          className="border border-[var(--border)] bg-[var(--surface-2)] p-4"
        >
          <label className="block">
            <span className="font-mono text-[11px] uppercase tracking-[0.16em] text-[var(--muted-soft)]">
              {t.followUp}
            </span>
            <textarea
              value={composer}
              onChange={(event) => setComposer(event.target.value)}
              rows={3}
              placeholder={t.composerPlaceholder}
              className="mt-2 w-full resize-y border border-[var(--border-strong)] bg-[var(--bg)] px-3 py-2 text-sm leading-6 text-[var(--text)] outline-none focus:border-[var(--accent)]"
            />
          </label>
          <div className="mt-3 flex items-center justify-between gap-3">
            <p className="text-[11px] leading-5 text-[var(--muted-soft)]">{t.composerHint}</p>
            <button
              type="submit"
              disabled={sending || !composer.trim()}
              className="border border-[var(--accent)] bg-[var(--accent)] px-4 py-2 font-mono text-[11px] uppercase tracking-[0.16em] text-[var(--accent-contrast)] transition hover:opacity-90 disabled:opacity-50"
            >
              {sending ? t.sending : t.send}
            </button>
          </div>
        </form>
      </div>

      <aside className="space-y-4">
        <section className="desk-panel p-4">
          <div className="flex items-center justify-between font-mono text-[11px] uppercase tracking-[0.16em] text-[var(--muted)]">
            <span>{t.liveDeskLabel}</span>
            <span>{live.runId ? live.runId.slice(0, 8) : "—"}</span>
          </div>

          <div className="mt-4">
            <p className="font-mono text-[11px] uppercase tracking-[0.16em] text-[var(--muted-soft)]">
              {t.planTitle}
            </p>
            {live.plan.length === 0 ? (
              <p className="mt-2 text-[12px] text-[var(--muted-soft)]">{t.planEmpty}</p>
            ) : (
              <ol className="mt-2 space-y-1">
                {live.plan.map((step, index) => (
                  <li
                    key={`${step}-${index}`}
                    className="font-mono text-[11px] uppercase tracking-[0.12em] text-[var(--muted)]"
                  >
                    {String(index + 1).padStart(2, "0")} · {step}
                  </li>
                ))}
              </ol>
            )}
          </div>

          <div className="mt-4 border-t border-[var(--border)] pt-3">
            <ol className="space-y-1.5">
              {STAGE_KEYS.map((key, index) => {
                const active = live.stage === key;
                const done = stageIndex > index;
                return (
                  <li key={key} className="flex items-center gap-2">
                    <span
                      className={`h-1 w-1 rounded-full ${
                        active
                          ? "bg-[var(--accent)]"
                          : done
                            ? "bg-[var(--muted)]"
                            : "bg-[var(--border-strong)]"
                      }`}
                    />
                    <span
                      className={`font-mono text-[11px] uppercase tracking-[0.14em] ${
                        active
                          ? "text-[var(--text)]"
                          : done
                            ? "text-[var(--muted)]"
                            : "text-[var(--muted-soft)]"
                      }`}
                    >
                      {t.stages[key]}
                    </span>
                  </li>
                );
              })}
            </ol>
          </div>

          <div className="mt-4 border-t border-[var(--border)] pt-3 font-mono text-[11px] uppercase tracking-[0.12em] text-[var(--muted)]">
            <div className="flex items-center justify-between">
              <span>{t.tokensLabel}</span>
              <span>{usageSnapshot ? usageSnapshot.total_tokens.toLocaleString() : "—"}</span>
            </div>
            <div className="mt-1 flex items-center justify-between">
              <span>{t.costLabel}</span>
              <span>{usageSnapshot ? `$${usageSnapshot.cost_usd.toFixed(4)}` : "—"}</span>
            </div>
            {live.limits ? (
              <div className="mt-1 flex items-center justify-between text-[var(--muted-soft)]">
                <span>{t.limitLabel}</span>
                <span>
                  {live.limits.max_tokens.toLocaleString()} / ${live.limits.max_cost_usd.toFixed(2)}
                </span>
              </div>
            ) : null}
          </div>
        </section>

        {replayReport ? (
          <section className="border border-[var(--border)] bg-[var(--surface)] p-4">
            <h3 className="font-mono text-[12px] uppercase tracking-[0.16em] text-[var(--accent)]">
              {replayReport.ok ? t.replayOk : t.replayFailed}
            </h3>
            {replayReport.error ? (
              <p className="mt-2 text-[12px] leading-5 text-[var(--accent)]">{replayReport.error}</p>
            ) : null}
            <ul className="mt-3 space-y-1">
              {replayReport.checks.map((check) => (
                <li
                  key={check.tool}
                  className="flex items-center justify-between gap-3 font-mono text-[11px] uppercase tracking-[0.12em] text-[var(--muted)]"
                >
                  <span>{check.tool}</span>
                  <span>
                    {check.comparable ? (check.equal ? "=" : "≠") : t.notComparable}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {!live.done && live.precedents.length > 0 ? (
          <section className="border border-[var(--border)] bg-[var(--surface)] p-4">
            <PrecedentStrip precedents={live.precedents} t={t} />
          </section>
        ) : null}

        {!live.done && live.suggestions.length > 0 ? (
          <section className="border border-[var(--border)] bg-[var(--surface)] p-4">
            <SuggestionList
              suggestions={live.suggestions}
              stuckQuestion={live.stuck?.stuck_question ?? stuck?.stuck_question ?? ""}
              runId={live.runId}
              precedents={live.precedents}
              t={t}
              feedback={feedback}
              onFeedback={handleFeedback}
              onExpand={handleExpand}
            />
          </section>
        ) : null}
      </aside>
    </section>
  );
}
