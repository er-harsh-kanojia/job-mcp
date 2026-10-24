// Server-Sent Events helpers.
// - GET task streams use the browser's EventSource (see http.ts subscribeTask).
// - The POST interview stream can't use EventSource, so readSse() parses a fetch() body.

export type SseMessage = { event: string; data: string };

/** Parse one SSE frame (the text between blank lines). Returns null for comment-only frames. */
export function parseSseFrame(frame: string): SseMessage | null {
  let event = 'message';
  const data: string[] = [];
  for (const raw of frame.split('\n')) {
    if (!raw || raw.startsWith(':')) continue;
    const i = raw.indexOf(':');
    const field = i === -1 ? raw : raw.slice(0, i);
    let value = i === -1 ? '' : raw.slice(i + 1);
    if (value.startsWith(' ')) value = value.slice(1);
    if (field === 'event') event = value;
    else if (field === 'data') data.push(value);
  }
  if (!data.length && event === 'message') return null;
  return { event, data: data.join('\n') };
}

/** Read a text/event-stream response body and call onMessage for each event, in order. */
export async function readSse(body: ReadableStream<Uint8Array>, onMessage: (m: SseMessage) => void): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true }).replace(/\r\n?/g, '\n');
      let idx: number;
      while ((idx = buf.indexOf('\n\n')) !== -1) {
        const msg = parseSseFrame(buf.slice(0, idx));
        buf = buf.slice(idx + 2);
        if (msg) onMessage(msg);
      }
    }
    buf += decoder.decode();
    const tail = parseSseFrame(buf.trim());
    if (tail) onMessage(tail);
  } finally {
    reader.releaseLock();
  }
}

export function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}
