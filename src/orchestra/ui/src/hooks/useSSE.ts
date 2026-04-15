import { useEffect, useRef, useCallback } from 'react';
import type { AnyEvent } from '../types/events';
import { authHeaders } from './auth';

interface UseSSEOptions {
  runId: string | null;
  onEvent: (event: AnyEvent) => void;
  onDone?: () => void;
  onError?: (err: Error) => void;
}

const EVENT_TYPES = new Set([
  'execution.started', 'execution.completed', 'execution.forked',
  'node.started', 'node.completed', 'state.updated', 'error.occurred',
  'llm.called', 'tool.called',
  'edge.traversed', 'parallel.started', 'parallel.completed',
  'interrupt.requested', 'interrupt.resumed', 'checkpoint.created',
  'security.violation', 'security.restricted_mode_entered',
  'input.rejected', 'output.rejected',
  'handoff.initiated', 'handoff.completed',
  'done',
]);

const MAX_RETRIES = 5;
const RETRY_BASE_MS = 500;

/**
 * Hook that connects to the SSE stream for a workflow run.
 *
 * Implemented with fetch + ReadableStream rather than the native EventSource
 * API so it can send an Authorization header (ORCHESTRA_API_KEY /
 * ORCHESTRA_SERVER_KEY). Reconnects on transient errors using Last-Event-ID.
 */
export function useSSE({ runId, onEvent, onDone, onError }: UseSSEOptions) {
  const abortRef = useRef<AbortController | null>(null);
  const lastIdRef = useRef<string>('0');
  const closedRef = useRef<boolean>(false);

  const close = useCallback(() => {
    closedRef.current = true;
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (!runId) return;

    closedRef.current = false;
    lastIdRef.current = '0';

    const dispatchRecord = (eventType: string, dataLines: string[], id: string) => {
      if (id) lastIdRef.current = id;
      if (eventType === 'done') {
        onDone?.();
        close();
        return;
      }
      if (!EVENT_TYPES.has(eventType)) return;
      const raw = dataLines.join('\n');
      if (!raw) return;
      try {
        const data = JSON.parse(raw) as AnyEvent;
        onEvent(data);
      } catch {
        // ignore parse errors (pings, malformed payloads)
      }
    };

    const parseAndDispatch = (buffer: string): string => {
      // SSE messages are separated by a blank line. Keep trailing fragment.
      let remaining = buffer;
      while (true) {
        const sep = remaining.indexOf('\n\n');
        if (sep === -1) return remaining;
        const record = remaining.slice(0, sep);
        remaining = remaining.slice(sep + 2);

        let eventType = 'message';
        let id = '';
        const dataLines: string[] = [];
        for (const line of record.split('\n')) {
          if (line.startsWith(':') || line.length === 0) continue;
          const colon = line.indexOf(':');
          const field = colon === -1 ? line : line.slice(0, colon);
          const value =
            colon === -1
              ? ''
              : line.slice(colon + 1).startsWith(' ')
                ? line.slice(colon + 2)
                : line.slice(colon + 1);
          if (field === 'event') eventType = value;
          else if (field === 'data') dataLines.push(value);
          else if (field === 'id') id = value;
        }
        dispatchRecord(eventType, dataLines, id);
      }
    };

    const connect = async (attempt: number): Promise<void> => {
      if (closedRef.current) return;
      const controller = new AbortController();
      abortRef.current = controller;
      const url = `/api/v1/runs/${encodeURIComponent(runId)}/stream`;
      const headers: Record<string, string> = {
        Accept: 'text/event-stream',
        ...authHeaders(),
      };
      if (lastIdRef.current && lastIdRef.current !== '0') {
        headers['Last-Event-ID'] = lastIdRef.current;
      }

      try {
        const res = await fetch(url, { headers, signal: controller.signal });
        if (!res.ok) {
          throw new Error(`SSE HTTP ${res.status}`);
        }
        if (!res.body) {
          throw new Error('SSE response has no body');
        }
        const reader = res.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '';
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          buffer = parseAndDispatch(buffer);
        }
        // Stream ended cleanly without a `done` event — treat as completion.
        if (!closedRef.current) {
          onDone?.();
          close();
        }
      } catch (err) {
        if (closedRef.current || (err instanceof DOMException && err.name === 'AbortError')) {
          return;
        }
        const error = err instanceof Error ? err : new Error(String(err));
        onError?.(error);
        if (attempt >= MAX_RETRIES) {
          close();
          return;
        }
        const delay = RETRY_BASE_MS * 2 ** attempt;
        await new Promise((r) => setTimeout(r, delay));
        if (!closedRef.current) {
          void connect(attempt + 1);
        }
      }
    };

    void connect(0);

    return () => {
      close();
    };
  }, [runId, onEvent, onDone, onError, close]);

  return { close };
}
