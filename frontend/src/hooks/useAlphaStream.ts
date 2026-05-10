import { useState, useCallback } from 'react';

export type LogEntry = {
  type: 'agent_status' | 'agent_action';
  payload: any;
};

export function useAlphaStream() {
  const [isStreaming, setIsStreaming] = useState(false);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [tokens, setTokens] = useState('');
  const [signal, setSignal] = useState<any>(null);

  const startStream = useCallback(async (query: string) => {
    setIsStreaming(true);
    setLogs([]);
    setTokens('');
    setSignal(null);

    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/analyze`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'text/event-stream',
        },
        body: JSON.stringify({ query }),
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
          
          // The last element is either an empty string (if buffer ended exactly with \n\n)
          // or an incomplete chunk. Keep it in the buffer.
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
                    setLogs((prev) => [...prev, { type: event, payload: parsedData }]);
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
                }
              } catch (e) {
                console.error('Failure parsing stream event payload', data, e);
              }
            }
          }
        }

        if (done) break;
      }
    } catch (error) {
      console.error('Streaming request failed', error);
    } finally {
      setIsStreaming(false);
    }
  }, []);

  return { isStreaming, logs, tokens, signal, startStream };
}