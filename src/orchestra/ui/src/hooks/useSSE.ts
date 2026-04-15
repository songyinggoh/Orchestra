import { useEffect, useRef, useCallback } from 'react';
import type { AnyEvent } from '../types/events';

interface UseSSEOptions {
  runId: string | null;
  onEvent: (event: AnyEvent) => void;
  onDone?: () => void;
  onError?: (err: Event) => void;
}

/**
 * Hook that connects to the SSE stream for a workflow run.
 * Automatically reconnects using Last-Event-ID.
 *
 * KNOWN LIMITATION: the browser's EventSource API cannot set request headers,
 * so this connection does not carry an Authorization bearer token. Against a
 * server started with ORCHESTRA_API_KEY / ORCHESTRA_SERVER_KEY set, the stream
 * will 401. Fixing this requires replacing EventSource with a fetch+
 * ReadableStream reader (or an EventSource polyfill that supports headers).
 */
export function useSSE({ runId, onEvent, onDone, onError }: UseSSEOptions) {
  const sourceRef = useRef<EventSource | null>(null);
  const lastIdRef = useRef<string>('0');

  const close = useCallback(() => {
    if (sourceRef.current) {
      sourceRef.current.close();
      sourceRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (!runId) return;

    const url = `/api/v1/runs/${runId}/stream`;
    const es = new EventSource(url);
    sourceRef.current = es;

    // Listen for all Orchestra event types
    const eventTypes = [
      'execution.started', 'execution.completed', 'execution.forked',
      'node.started', 'node.completed', 'state.updated', 'error.occurred',
      'llm.called', 'tool.called',
      'edge.traversed', 'parallel.started', 'parallel.completed',
      'interrupt.requested', 'interrupt.resumed', 'checkpoint.created',
      'security.violation', 'security.restricted_mode_entered',
      'input.rejected', 'output.rejected',
      'handoff.initiated', 'handoff.completed',
    ];

    const handler = (e: MessageEvent) => {
      lastIdRef.current = e.lastEventId || lastIdRef.current;
      try {
        const data = JSON.parse(e.data) as AnyEvent;
        onEvent(data);
      } catch {
        // ignore parse errors (config, ping)
      }
    };

    for (const type of eventTypes) {
      es.addEventListener(type, handler);
    }

    let retryCount = 0;

    const doneHandler = () => {
      onDone?.();
      close();
    };
    es.addEventListener('done', doneHandler);

    es.onerror = (err) => {
      onError?.(err);
      retryCount++;
      if (retryCount > 5) {
        close();
      }
    };

    return () => {
      for (const type of eventTypes) {
        es.removeEventListener(type, handler);
      }
      es.removeEventListener('done', doneHandler);
      close();
    };
  }, [runId, onEvent, onDone, onError, close]);

  return { close };
}
