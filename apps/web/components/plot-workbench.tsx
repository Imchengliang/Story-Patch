"use client";

import { useState } from "react";

import { FirstRunPanel } from "@/components/first-run-panel";
import { SessionList } from "@/components/session-list";
import { ThreadView } from "@/components/thread-view";
import type { Language } from "@/lib/copy";

type Session = { threadId: string; runId: string };

export function PlotWorkbench({ language }: { language: Language }) {
  const [session, setSession] = useState<Session | null>(null);

  if (!session) {
    return (
      <>
        <SessionList
          language={language}
          onOpen={(threadId) => setSession({ threadId, runId: "" })}
        />
        <FirstRunPanel
          language={language}
          onStarted={(threadId, runId) => setSession({ threadId, runId })}
        />
      </>
    );
  }

  return (
    <ThreadView
      language={language}
      threadId={session.threadId}
      initialRunId={session.runId}
      onNewSession={() => setSession(null)}
    />
  );
}
