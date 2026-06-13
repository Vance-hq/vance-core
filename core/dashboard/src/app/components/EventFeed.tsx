"use client";

import { useEffect, useRef, useState } from "react";

interface VanceEvent {
  type: string;
  agent?: string;
  action?: string;
  task_id?: string;
  message?: string;
  at?: string;
  [key: string]: unknown;
}

const MAX_EVENTS = 200;

// System/infra events that should be muted, not suppressed entirely.
const SYSTEM_TYPES = new Set(["CONNECTED", "REDIS_UNAVAILABLE"]);

function eventClass(type: string): string {
  const t = type?.toUpperCase() ?? "";
  if (SYSTEM_TYPES.has(t))                                   return "event-system";
  if (t.includes("COMPLETE") || t.includes("SUCCESS"))       return "event-complete";
  if (t.includes("FAIL")     || t.includes("ERROR"))         return "event-failed";
  if (t.includes("ALERT")    || t.includes("CANCEL"))        return "event-alert";
  if (t.includes("STATUS")   || t.includes("UPDATE"))        return "event-status";
  return "event-default";
}

function formatEvent(ev: VanceEvent): string {
  const time   = ev.at ? new Date(ev.at).toLocaleTimeString() : new Date().toLocaleTimeString();
  const agent  = ev.agent  ? ` [${ev.agent}]`  : "";
  const action = ev.action ? `.${ev.action}`    : "";
  const msg    = ev.message ?? ev.task_id ?? "";
  return `${time}  ${ev.type}${agent}${action}${msg ? "  " + msg : ""}`;
}

export default function EventFeed() {
  const [events, setEvents]   = useState<{ line: string; cls: string }[]>([]);
  const [paused, setPaused]   = useState(false);
  const [connected, setConnected] = useState(false);
  const bottomRef  = useRef<HTMLDivElement>(null);
  const lastTypeRef = useRef<string>("");   // deduplicate consecutive system noise

  useEffect(() => {
    const es = new EventSource("/api/events");
    es.onopen  = () => setConnected(true);
    es.onerror = () => setConnected(false);

    es.onmessage = (e) => {
      if (!e.data || e.data.startsWith(":")) return;
      try {
        const ev = JSON.parse(e.data) as VanceEvent;
        const t  = ev.type?.toUpperCase() ?? "";

        // Drop repeated consecutive system events (REDIS_UNAVAILABLE spam).
        if (SYSTEM_TYPES.has(t) && lastTypeRef.current === t) return;
        lastTypeRef.current = t;

        setEvents((prev) => [
          ...prev.slice(-(MAX_EVENTS - 1)),
          { line: formatEvent(ev), cls: eventClass(t) },
        ]);
      } catch { /* ignore malformed */ }
    };

    return () => es.close();
  }, []);

  // Auto-scroll when not paused.
  useEffect(() => {
    if (!paused) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events, paused]);

  return (
    <section className="flex flex-col gap-3 min-w-0">
      <div className="flex items-center justify-between">
        <h2 className="text-xs uppercase tracking-widest text-zinc-400">Live Events</h2>
        <div className="flex items-center gap-3">
          <span className={`text-[10px] ${connected ? "text-green-400" : "text-red-400 animate-pulse"}`}>
            {connected ? "● LIVE" : "○ OFFLINE"}
          </span>
          <span className="text-[10px] text-zinc-500">{events.length} events</span>
          <button
            onClick={() => setPaused((p) => !p)}
            className={`text-[10px] uppercase px-2 py-0.5 rounded border transition-colors ${
              paused
                ? "border-amber-600 text-amber-300 bg-amber-950/40"
                : "border-zinc-700 text-zinc-400 hover:border-zinc-500 hover:text-zinc-300"
            }`}
          >
            {paused ? "resume" : "pause"}
          </button>
          <button
            onClick={() => setEvents([])}
            className="text-[10px] text-zinc-600 hover:text-zinc-400 transition-colors"
          >
            clear
          </button>
        </div>
      </div>

      <div
        onMouseEnter={() => setPaused(true)}
        onMouseLeave={() => setPaused(false)}
        className="h-64 overflow-y-auto rounded border border-zinc-700 bg-zinc-950 p-2 font-mono text-[11px] leading-5"
      >
        {events.length === 0 && (
          <span className="text-zinc-500">Waiting for events on vance:events…</span>
        )}
        {events.map((ev, i) => (
          <div key={i} className={ev.cls}>{ev.line}</div>
        ))}
        <div ref={bottomRef} />
      </div>
    </section>
  );
}
