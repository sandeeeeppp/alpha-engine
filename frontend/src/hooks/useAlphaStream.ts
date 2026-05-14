import { useState, useCallback, useRef } from 'react';

export type LogEntry = {
  type: 'agent_status' | 'agent_action';
  payload: any;
};

export function useAlphaStream() {
  const [isStreaming, setIsStreaming] = useState(false);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [tokens, setTokens] = useState('');
  const [signal, setSignal] = useState<any>(null);
  // AbortController ref — persists across renders without triggering re-renders
  const controllerRef = useRef<AbortController | null>(null);

  const startStream = useCallback(async (query: string) => {
    // Cancel any in-flight request before starting a new one
    if (controllerRef.current) {
      controllerRef.current.abort();
    }
    controllerRef.current = new AbortController();

    setIsStreaming(true);
    setLogs([]);
    setTokens('');
    setSignal(null);

    try {
      const response = await fetch('/api/analyze', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'text/event-stream',
        },
        body: JSON.stringify({ query }),
        signal: controllerRef.current.signal, // bind cancellation token
      });

      if (!response.body) throw new Error('No readable stream available.');

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();

        if (value) {
          buffer += decoder.decode(value, { stream: true });
          const parts = buffer.split('\n\n');

          // The last element is either empty (buffer ended exactly with \n\n)
          // or an incomplete chunk — keep it in the buffer.
          buffer = parts.pop() || '';

          for (const part of parts) {
            const lines = part.split('\n');
            let event = '';
            let data = '';

            for (const line of lines) {
              if (line.startsWith('event: ')) {
                event = line.slice(7).trim();
              } else if (line.startsWith('data: ')) {
                data = line.slice(6).trim();
              }
            }

            if (event && data) {
              try {
                const parsedData = JSON.parse(data);

                switch (event) {
                  case 'agent_status':
                  case 'agent_action':
                    setLogs((prev) => [...prev, { type: event as LogEntry['type'], payload: parsedData }]);
                    break;
                  case 'agent_token':
                    setTokens((prev) => prev + (parsedData.content || ''));
                    break;
                  case 'alpha_signal':
                    setSignal(parsedData);
                    break;
                  case 'done':
                    setIsStreaming(false);
                    return;
                  case 'agent_error':
                    console.error('[alpha-stream] Agent error:', parsedData);
                    setIsStreaming(false);
                    return;
                }
              } catch (e) {
                // Partial line — will be reassembled in the next iteration
                console.warn('[alpha-stream] Failed to parse stream event payload:', data, e);
              }
            }
          }
        }

        if (done) break;
      }
    } catch (err: any) {
      if (err.name === 'AbortError') {
        // Expected — user navigated away or triggered a new query
        console.info('[alpha-stream] Stream aborted.');
      } else {
        console.error('[alpha-stream] Streaming request failed:', err);
      }
    } finally {
      setIsStreaming(false);
    }
  }, []);

  const stopStream = useCallback(() => {
    if (controllerRef.current) {
      controllerRef.current.abort();
      controllerRef.current = null;
    }
    setIsStreaming(false);
  }, []);

  return { isStreaming, logs, tokens, signal, startStream, stopStream };
}