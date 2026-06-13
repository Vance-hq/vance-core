"use client";

import { useEffect, useState } from "react";

interface Stats {
  sends: number | null;
  open_rate: number | null;
  replies: number | null;
  unsubscribes: number | null;
  error?: string;
}

function StatCard({
  label,
  value,
  suffix,
  highlight = "default",
}: {
  label: string;
  value: number | null;
  suffix?: string;
  highlight?: "green" | "red" | "default";
}) {
  const valueColor = {
    green:   "text-green-400",
    red:     "text-red-400",
    default: "text-white",
  }[highlight];

  return (
    <div className="rounded border border-zinc-700 bg-zinc-900 px-4 py-3 flex flex-col gap-1">
      <span className="text-xs font-bold uppercase tracking-widest text-zinc-400">{label}</span>
      <span className={`text-2xl font-bold ${valueColor}`}>
        {value === null
          ? <span className="text-zinc-600 text-lg">—</span>
          : <>{value}{suffix && <span className="text-base text-zinc-400 ml-0.5">{suffix}</span>}</>}
      </span>
    </div>
  );
}

export default function CampaignStats() {
  const [stats, setStats]       = useState<Stats | null>(null);
  const [lastFetch, setLastFetch] = useState<Date | null>(null);

  const fetch_stats = async () => {
    try {
      const res = await fetch("/api/marketing/stats");
      setStats(await res.json());
      setLastFetch(new Date());
    } catch { /* silent */ }
  };

  useEffect(() => {
    fetch_stats();
    const id = setInterval(fetch_stats, 60_000);
    return () => clearInterval(id);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between">
        <h2 className="text-sm font-bold uppercase tracking-widest text-white">Campaign Stats · Today</h2>
        {lastFetch && <span className="text-xs text-zinc-500">{lastFetch.toLocaleTimeString()}</span>}
      </div>

      {stats?.error ? (
        <div className="text-xs text-red-400 bg-red-950/30 border border-red-800 rounded px-3 py-2">
          {stats.error}
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          <StatCard label="Sends today" value={stats?.sends ?? null} />
          <StatCard
            label="Open rate"
            value={stats?.open_rate ?? null}
            suffix="%"
            highlight={stats?.open_rate == null ? "default" : stats.open_rate >= 30 ? "green" : stats.open_rate < 10 ? "red" : "default"}
          />
          <StatCard label="Replies" value={stats?.replies ?? null} highlight={stats?.replies ? "green" : "default"} />
          <StatCard
            label="Unsubscribes"
            value={stats?.unsubscribes ?? null}
            highlight={stats?.unsubscribes != null && stats.unsubscribes > 5 ? "red" : "default"}
          />
        </div>
      )}
    </section>
  );
}
