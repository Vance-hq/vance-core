"use client";

import { useEffect, useState } from "react";

interface Stats {
  sends: number | null;
  open_rate: number | null;
  replies: number | null;
  unsubscribes: number | null;
  error?: string;
}

interface StatCardProps {
  label: string;
  value: number | string | null;
  suffix?: string;
  highlight?: "green" | "red" | "blue" | "default";
}

function StatCard({ label, value, suffix, highlight = "default" }: StatCardProps) {
  const colors = {
    green:   "text-green-400",
    red:     "text-red-400",
    blue:    "text-blue-400",
    default: "text-zinc-200",
  };

  return (
    <div className="rounded border border-zinc-800 bg-surface-2 px-4 py-3 flex flex-col gap-1">
      <span className="text-[10px] uppercase tracking-widest text-zinc-600">{label}</span>
      <span className={`text-xl font-semibold ${colors[highlight]}`}>
        {value === null ? (
          <span className="text-zinc-700 text-sm">—</span>
        ) : (
          <>
            {value}
            {suffix && <span className="text-sm text-zinc-500 ml-0.5">{suffix}</span>}
          </>
        )}
      </span>
    </div>
  );
}

export default function CampaignStats() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [lastFetch, setLastFetch] = useState<Date | null>(null);

  const fetch_stats = async () => {
    try {
      const res = await fetch("/api/marketing/stats");
      const data = (await res.json()) as Stats;
      setStats(data);
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
        <h2 className="text-xs uppercase tracking-widest text-zinc-500">
          Campaign Stats · Today
        </h2>
        {lastFetch && (
          <span className="text-[10px] text-zinc-700">
            {lastFetch.toLocaleTimeString()}
          </span>
        )}
      </div>

      {stats?.error ? (
        <div className="text-xs text-red-600">{stats.error}</div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          <StatCard
            label="Sends today"
            value={stats?.sends ?? null}
            highlight="default"
          />
          <StatCard
            label="Open rate"
            value={stats?.open_rate ?? null}
            suffix="%"
            highlight={
              stats?.open_rate == null
                ? "default"
                : stats.open_rate >= 30
                ? "green"
                : stats.open_rate < 10
                ? "red"
                : "default"
            }
          />
          <StatCard
            label="Replies"
            value={stats?.replies ?? null}
            highlight={stats?.replies ? "green" : "default"}
          />
          <StatCard
            label="Unsubscribes"
            value={stats?.unsubscribes ?? null}
            highlight={
              stats?.unsubscribes == null
                ? "default"
                : stats.unsubscribes > 5
                ? "red"
                : "default"
            }
          />
        </div>
      )}
    </section>
  );
}
