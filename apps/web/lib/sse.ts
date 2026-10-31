export type SseEvent = { event: string; data: unknown };

export class SseHttpError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function parseFrame(frame: string): SseEvent | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const rawLine of frame.split("\n")) {
    const line = rawLine.replace(/\r$/, "");
    if (!line || line.startsWith(":")) continue;
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  }
  if (dataLines.length === 0) return null;
  const data = dataLines.join("\n");
  try {
    return { event, data: JSON.parse(data) as unknown };
  } catch {
    return { event, data };
  }
}

/**
 * Consume a server-sent event stream frame by frame.
 *
 * The backend keeps finished runs in memory, so a late connect still replays
 * the whole turn. When the connection drops, callers fall back to reloading the
 * thread detail rather than trying to resume with an event id.
 */
export async function streamSse(
  url: string,
  onEvent: (event: SseEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(url, {
    headers: { Accept: "text/event-stream" },
    signal,
  });
  if (!response.ok) {
    const detail = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new SseHttpError(response.status, detail.detail ?? `HTTP ${response.status}`);
  }
  if (!response.body) {
    throw new Error("this browser does not support streaming responses");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const drain = (flush: boolean) => {
    let separator = buffer.indexOf("\n\n");
    while (separator >= 0) {
      const frame = buffer.slice(0, separator);
      buffer = buffer.slice(separator + 2);
      const parsed = parseFrame(frame);
      if (parsed) onEvent(parsed);
      separator = buffer.indexOf("\n\n");
    }
    if (flush && buffer.trim()) {
      const parsed = parseFrame(buffer);
      buffer = "";
      if (parsed) onEvent(parsed);
    }
  };

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
    drain(false);
  }
  buffer += decoder.decode();
  drain(true);
}
