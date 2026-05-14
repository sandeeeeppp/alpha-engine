"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useAlphaStream } from "../src/hooks/useAlphaStream";

// ── Ingestion state type ──────────────────────────────────────────────────────
type IngestStatus =
  | { kind: "idle" }
  | { kind: "uploading" }
  | { kind: "success"; message: string }
  | { kind: "error"; message: string };

export default function AlphaEngineDashboard() {
  // ── Analysis stream state ─────────────────────────────────────────────────
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

  // ── Ingestion state ───────────────────────────────────────────────────────
  const [ticker, setTicker] = useState("");
  const [fiscalYear, setFiscalYear] = useState<number | "">(
    new Date().getFullYear()
  );
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [ingestStatus, setIngestStatus] = useState<IngestStatus>({
    kind: "idle",
  });
  const [ingestLogs, setIngestLogs] = useState<string[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const pushIngestLog = (msg: string) => {
    const ts = new Date().toLocaleTimeString("en-US", { hour12: false });
    setIngestLogs((prev) => [...prev, `[${ts}] ${msg}`]);
  };

  const handleIngest = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();

      if (!pdfFile) {
        setIngestStatus({ kind: "error", message: "No PDF selected." });
        return;
      }
      if (!ticker.trim()) {
        setIngestStatus({ kind: "error", message: "Ticker is required." });
        return;
      }
      if (!fiscalYear || fiscalYear < 1900 || fiscalYear > 2100) {
        setIngestStatus({ kind: "error", message: "Invalid fiscal year." });
        return;
      }

      setIngestStatus({ kind: "uploading" });
      setIngestLogs([]);
      pushIngestLog(
        `Uploading ${pdfFile.name} → ${ticker.toUpperCase()} FY${fiscalYear}...`
      );

      const formData = new FormData();
      formData.append("file", pdfFile);
      formData.append("ticker", ticker.trim().toUpperCase());
      formData.append("fiscal_year", String(fiscalYear));

      try {
        const res = await fetch("/api/ingest", {
          method: "POST",
          body: formData,
        });

        const data = await res.json().catch(() => ({}));

        if (res.status === 202) {
          pushIngestLog(
            `✓ Accepted — ${data.filename ?? pdfFile.name} queued for ingestion.`
          );
          pushIngestLog(
            `  Ticker: ${data.ticker}  |  FY: ${data.fiscal_year}`
          );
          pushIngestLog("  Background processing started. Monitor server logs.");
          setIngestStatus({
            kind: "success",
            message: `${pdfFile.name} accepted for ingestion.`,
          });
          // Reset file input
          setPdfFile(null);
          if (fileInputRef.current) fileInputRef.current.value = "";
        } else {
          const detail =
            data?.detail ?? data?.error ?? `HTTP ${res.status}`;
          pushIngestLog(`✗ Error: ${detail}`);
          setIngestStatus({ kind: "error", message: detail });
        }
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Network error.";
        pushIngestLog(`✗ ${msg}`);
        setIngestStatus({ kind: "error", message: msg });
      }
    },
    [pdfFile, ticker, fiscalYear]
  );

  // ── Derived UI helpers ────────────────────────────────────────────────────
  const isUploading = ingestStatus.kind === "uploading";

  const statusBadge = () => {
    if (ingestStatus.kind === "success")
      return (
        <span className="bg-emerald-500/20 text-emerald-400 px-2 py-0.5 rounded text-[10px]">
          Accepted
        </span>
      );
    if (ingestStatus.kind === "error")
      return (
        <span className="bg-red-500/20 text-red-400 px-2 py-0.5 rounded text-[10px]">
          Error
        </span>
      );
    if (ingestStatus.kind === "uploading")
      return (
        <span className="bg-yellow-500/20 text-yellow-400 px-2 py-0.5 rounded text-[10px] animate-pulse">
          Uploading…
        </span>
      );
    return null;
  };

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100 font-mono flex flex-col p-4 md:p-6 gap-6">
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <header className="flex flex-col md:flex-row gap-4 items-center justify-between border-b border-neutral-800 pb-4">
        <h1 className="text-2xl font-bold text-emerald-500 tracking-tight">
          Alpha Engine
        </h1>
        <div className="flex w-full md:w-1/2 gap-2">
          <input
            type="text"
            placeholder="Analyze NVDA for fiscal year 2024..."
            className="flex-1 bg-neutral-900 border border-neutral-700 rounded p-2 text-sm focus:outline-none focus:border-emerald-500 transition-colors placeholder:text-neutral-600"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleExecute()}
          />
          <button
            onClick={handleExecute}
            disabled={isStreaming}
            className="bg-emerald-600 hover:bg-emerald-500 text-neutral-950 px-6 py-2 rounded font-semibold text-sm transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isStreaming ? "Running…" : "Execute"}
          </button>
        </div>
      </header>

      {/* ── Main grid ──────────────────────────────────────────────────────── */}
      <main className="flex-1 grid grid-cols-1 lg:grid-cols-3 gap-6 min-h-0">
        {/* Left column — spans 2/3 on large screens */}
        <div className="lg:col-span-2 grid grid-rows-[1fr_auto] gap-6 min-h-0">
          {/* Agent Terminal */}
          <section className="bg-neutral-900 border border-neutral-800 rounded-lg flex flex-col overflow-hidden min-h-[320px]">
            <div className="bg-neutral-800/50 px-4 py-2 border-b border-neutral-800 text-xs font-semibold text-neutral-400 uppercase tracking-widest">
              Agent Terminal
            </div>
            <div className="flex-1 overflow-y-auto p-4 space-y-3">
              {logs.length === 0 && (
                <p className="text-neutral-600 italic text-sm">
                  System idle. Awaiting command…
                </p>
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

          {/* Synthesis */}
          <section className="bg-neutral-900 border border-neutral-800 rounded-lg flex flex-col overflow-hidden min-h-[180px]">
            <div className="bg-neutral-800/50 px-4 py-2 border-b border-neutral-800 text-xs font-semibold text-neutral-400 uppercase tracking-widest">
              Synthesis
            </div>
            <div className="flex-1 overflow-y-auto p-4 text-sm whitespace-pre-wrap text-neutral-300 leading-relaxed">
              {tokens || (
                <span className="text-neutral-600 italic">
                  No output yet…
                </span>
              )}
            </div>
          </section>
        </div>

        {/* Right column */}
        <div className="flex flex-col gap-6 min-h-0">
          {/* Alpha Signal */}
          <section className="bg-neutral-900 border border-neutral-800 rounded-lg flex flex-col overflow-hidden">
            <div className="bg-neutral-800/50 px-4 py-2 border-b border-neutral-800 text-xs font-semibold text-neutral-400 uppercase tracking-widest flex items-center justify-between">
              <span>Alpha Signal</span>
              {signal && (
                <span className="bg-emerald-500/20 text-emerald-400 px-2 py-0.5 rounded text-[10px]">
                  Complete
                </span>
              )}
            </div>
            <div className="flex-1 overflow-y-auto p-4 bg-neutral-950">
              {signal ? (
                <pre className="text-xs text-emerald-400 whitespace-pre-wrap">
                  {JSON.stringify(signal, null, 2)}
                </pre>
              ) : (
                <p className="text-neutral-600 italic text-sm">
                  Awaiting final signal…
                </p>
              )}
            </div>
          </section>

          {/* Document Ingestion */}
          <section className="bg-neutral-900 border border-neutral-800 rounded-lg flex flex-col overflow-hidden">
            <div className="bg-neutral-800/50 px-4 py-2 border-b border-neutral-800 text-xs font-semibold text-neutral-400 uppercase tracking-widest flex items-center justify-between">
              <span>Document Ingestion</span>
              {statusBadge()}
            </div>

            <form onSubmit={handleIngest} className="p-4 flex flex-col gap-3">
              {/* Ticker + Fiscal Year row */}
              <div className="flex gap-2">
                <div className="flex-1 flex flex-col gap-1">
                  <label className="text-[10px] text-neutral-500 uppercase tracking-widest">
                    Ticker
                  </label>
                  <input
                    type="text"
                    placeholder="NVDA"
                    maxLength={10}
                    value={ticker}
                    onChange={(e) => setTicker(e.target.value.toUpperCase())}
                    disabled={isUploading}
                    className="bg-neutral-950 border border-neutral-700 rounded px-3 py-2 text-sm text-emerald-400 placeholder:text-neutral-600 focus:outline-none focus:border-emerald-600 transition-colors disabled:opacity-50 uppercase"
                  />
                </div>
                <div className="flex-1 flex flex-col gap-1">
                  <label className="text-[10px] text-neutral-500 uppercase tracking-widest">
                    Fiscal Year
                  </label>
                  <input
                    type="number"
                    placeholder="2024"
                    min={1900}
                    max={2100}
                    value={fiscalYear}
                    onChange={(e) =>
                      setFiscalYear(
                        e.target.value === "" ? "" : Number(e.target.value)
                      )
                    }
                    disabled={isUploading}
                    className="bg-neutral-950 border border-neutral-700 rounded px-3 py-2 text-sm text-neutral-300 placeholder:text-neutral-600 focus:outline-none focus:border-emerald-600 transition-colors disabled:opacity-50"
                  />
                </div>
              </div>

              {/* PDF file input */}
              <div className="flex flex-col gap-1">
                <label className="text-[10px] text-neutral-500 uppercase tracking-widest">
                  SEC Filing (PDF)
                </label>
                <label
                  className={`flex items-center gap-3 bg-neutral-950 border rounded px-3 py-2 cursor-pointer transition-colors ${
                    isUploading
                      ? "border-neutral-800 opacity-50 cursor-not-allowed"
                      : pdfFile
                      ? "border-emerald-700 hover:border-emerald-500"
                      : "border-neutral-700 hover:border-neutral-500 border-dashed"
                  }`}
                >
                  <span className="text-neutral-500 text-xs shrink-0">
                    {pdfFile ? "📄" : "📁"}
                  </span>
                  <span className="text-xs text-neutral-400 truncate">
                    {pdfFile ? pdfFile.name : "Click to select PDF…"}
                  </span>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".pdf,application/pdf"
                    className="hidden"
                    disabled={isUploading}
                    onChange={(e) =>
                      setPdfFile(e.target.files?.[0] ?? null)
                    }
                  />
                </label>
                {pdfFile && (
                  <p className="text-[10px] text-neutral-600 pl-1">
                    {(pdfFile.size / 1024 / 1024).toFixed(2)} MB
                  </p>
                )}
              </div>

              {/* Submit button */}
              <button
                type="submit"
                disabled={isUploading || !pdfFile}
                className="mt-1 w-full bg-neutral-800 hover:bg-neutral-700 border border-neutral-700 hover:border-emerald-700 text-neutral-200 px-4 py-2 rounded text-sm font-semibold transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {isUploading ? (
                  <span className="animate-pulse">Uploading…</span>
                ) : (
                  "Upload & Ingest"
                )}
              </button>
            </form>

            {/* Ingestion log output */}
            {ingestLogs.length > 0 && (
              <div className="border-t border-neutral-800 p-4 bg-neutral-950/60 flex flex-col gap-1">
                {ingestLogs.map((line, i) => (
                  <p
                    key={i}
                    className={`text-[11px] font-mono leading-snug ${
                      line.includes("✗")
                        ? "text-red-400"
                        : line.includes("✓")
                        ? "text-emerald-400"
                        : "text-neutral-500"
                    }`}
                  >
                    {line}
                  </p>
                ))}
              </div>
            )}
          </section>
        </div>
      </main>
    </div>
  );
}
