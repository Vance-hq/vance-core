"use client";

import { useRef, useState } from "react";

interface IntentResult {
  task_ids?: string[];
  agents?: string[];
  actions?: string[];
  spoken_response?: string;
  error?: string;
  detail?: string;
}

export default function CommandInput() {
  const [command, setCommand] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult]   = useState<IntentResult | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const text = command.trim();
    if (!text) return;
    setLoading(true);
    setResult(null);
    try {
      const res = await fetch("/api/intent", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ raw_text: text, agent: null, action: null, confidence: 0 }),
      });
      setResult(await res.json());
    } catch (err) {
      setResult({ error: "request failed", detail: String(err) });
    } finally {
      setLoading(false);
      setCommand("");
      inputRef.current?.focus();
    }
  };

  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-sm font-bold uppercase tracking-widest text-white">Command</h2>

      <form onSubmit={submit} className="flex gap-2">
        <div className="flex-1 flex items-center gap-2 bg-zinc-900 border border-zinc-600 rounded px-3 focus-within:border-zinc-400 transition-colors">
          <span className="text-zinc-400 text-base select-none">›</span>
          <input
            ref={inputRef}
            type="text"
            value={command}
            onChange={(e) => setCommand(e.target.value)}
            placeholder="type a command…"
            disabled={loading}
            className="flex-1 bg-transparent outline-none text-white placeholder-zinc-600 py-2 text-sm font-mono"
          />
        </div>
        <button
          type="submit"
          disabled={loading || !command.trim()}
          className="px-4 py-2 rounded bg-zinc-700 hover:bg-zinc-500 disabled:opacity-40 text-white text-xs font-bold uppercase tracking-widest transition-colors"
        >
          {loading ? "…" : "SEND"}
        </button>
      </form>

      {result && (
        <div className="rounded border border-zinc-700 bg-zinc-900 p-3 font-mono text-xs flex flex-col gap-2">
          {result.error ? (
            <div className="text-red-400 font-semibold">
              error: {result.error}
              {result.detail && <span className="text-zinc-500 font-normal"> — {result.detail}</span>}
            </div>
          ) : (
            <>
              {result.spoken_response && (
                <div className="text-zinc-200 italic">"{result.spoken_response}"</div>
              )}
              {result.agents && result.agents.length > 0 && (
                <div className="flex flex-col gap-1">
                  <span className="text-zinc-500 text-[10px] uppercase tracking-widest">Routed to</span>
                  {result.agents.map((agent, i) => (
                    <div key={i} className="flex items-center gap-2">
                      <span className="text-green-400 font-bold">{agent}</span>
                      <span className="text-zinc-500">›</span>
                      <span className="text-zinc-300">{result.actions?.[i]?.replace(/_/g, " ")}</span>
                    </div>
                  ))}
                </div>
              )}
              {result.task_ids && result.task_ids.length > 0 && (
                <div className="flex flex-col gap-0.5">
                  <span className="text-zinc-500 text-[10px] uppercase tracking-widest">Task IDs</span>
                  {result.task_ids.map((id) => (
                    <span key={id} className="text-zinc-400">{id}</span>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </section>
  );
}
