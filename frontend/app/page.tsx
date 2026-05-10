"use client";

import { useState, useRef, useEffect } from "react";
import { useAlphaStream } from "../src/hooks/useAlphaStream";

export default function AlphaEngineDashboard() {
  const { isStreaming, logs, tokens, signal, startStream } = useAlphaStream();
  const [query, setQuery] = useState("");
  const logsEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [logs]);

  const handleExecute = () => {
    if (!query.trim() || isStreaming) return;
    startStream(query);
  };

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100 font-mono flex flex-col p-4 md:p-6">
      <header className="mb-6 flex flex-col md:flex-row gap-4 items-center justify-between border-b border-neutral-800 pb-4">
        <h1 className="text-2xl font-bold text-emerald-500 tracking-tight">Alpha Engine</h1>
        <div className="flex w-full md:w-1/2 gap-2">
          <input
            type="text"
            placeholder="Enter analysis query..."
            className="flex-1 bg-neutral-900 border border-neutral-700 rounded p-2 text-sm focus:outline-none focus:border-emerald-500 transition-colors"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleExecute()}
          />
          <button
            onClick={handleExecute}
            disabled={isStreaming}
            className="bg-emerald-600 hover:bg-emerald-500 text-neutral-950 px-6 py-2 rounded font-semibold text-sm transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isStreaming ? "Running..." : "Execute"}
          </button>
        </div>
      </header>

      <main className="flex-1 grid grid-cols-1 md:grid-cols-2 gap-6 min-h-0">
        <section className="bg-neutral-900 border border-neutral-800 rounded-lg flex flex-col overflow-hidden">
          <div className="bg-neutral-800/50 px-4 py-2 border-b border-neutral-800 text-xs font-semibold text-neutral-400 uppercase tracking-widest">
            Agent Terminal
          </div>
          <div className="flex-1 overflow-y-auto p-4 space-y-3">
            {logs.length === 0 && (
              <p className="text-neutral-600 italic text-sm">System idle. Awaiting command...</p>
            )}
            {logs.map((log, i) => (
              <div key={i} className="text-sm">
                {log.type === "agent_status" && (
                  <span className="text-blue-400">
                    <span className="text-neutral-500 mr-2">[STATUS]</span>
                    {log.payload.message || JSON.stringify(log.payload)}
                  </span>
                )}
                {log.type === "agent_action" && (
                  <div className="text-yellow-400 mt-1">
                    <span className="text-neutral-500 mr-2">[ACTION]</span>
                    <pre className="inline-block align-top whitespace-pre-wrap break-all bg-neutral-950/50 p-2 rounded text-xs mt-1 border border-yellow-900/30">
                      {JSON.stringify(log.payload, null, 2)}
                    </pre>
                  </div>
                )}
              </div>
            ))}
            <div ref={logsEndRef} />
          </div>
        </section>

        <section className="flex flex-col gap-6 min-h-0">
          <div className="flex-1 bg-neutral-900 border border-neutral-800 rounded-lg flex flex-col overflow-hidden">
            <div className="bg-neutral-800/50 px-4 py-2 border-b border-neutral-800 text-xs font-semibold text-neutral-400 uppercase tracking-widest">
              Synthesis
            </div>
            <div className="flex-1 overflow-y-auto p-4 text-sm whitespace-pre-wrap text-neutral-300 leading-relaxed">
              {tokens || <span className="text-neutral-600 italic">No output yet...</span>}
            </div>
          </div>

          <div className="h-[35%] bg-neutral-900 border border-neutral-800 rounded-lg flex flex-col overflow-hidden">
            <div className="bg-neutral-800/50 px-4 py-2 border-b border-neutral-800 text-xs font-semibold text-neutral-400 uppercase tracking-widest flex items-center justify-between">
              <span>Alpha Signal</span>
              {signal && <span className="bg-emerald-500/20 text-emerald-400 px-2 py-0.5 rounded text-[10px]">Complete</span>}
            </div>
            <div className="flex-1 overflow-y-auto p-4 bg-neutral-950">
              {signal ? (
                <pre className="text-xs text-emerald-400 whitespace-pre-wrap">
                  {JSON.stringify(signal, null, 2)}
                </pre>
              ) : (
                <p className="text-neutral-600 italic text-sm">Awaiting final signal constraint...</p>
              )}
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
