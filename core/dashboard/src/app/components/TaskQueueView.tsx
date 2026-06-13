"use client";

import { useCallback, useEffect, useState } from "react";

interface SessionEntry {
  intent: string;
  agent: string;
  action: string;
  at: string;
  outcome?: string;
  task_ids?: string[];
}

interface TasksData {
  history: SessionEntry[];
  queue_depths: Record<string, number>;
}

const STATUS_COLORS: Record<string, string> = {
  success: "text-green-400 font-semibold",
  failed:  "text-red-400 font-semibold",
  pending: "text-amber-400 font-semibold",
};

export default function TaskQueueView() {
  const [data, setData]               = useState<TasksData | null>(null);
  const [agentFilter, setAgentFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [cancelling, setCancelling]   = useState<string | null>(null);

  const fetchTasks = useCallback(async () => {
    try {
      const res = await fetch("/api/tasks");
      setData(await res.json());
    } catch { /* silent */ }
  }, []);

  useEffect(() => {
    fetchTasks();
    const id = setInterval(fetchTasks, 10_000);
    return () => clearInterval(id);
  }, [fetchTasks]);

  const cancelTask = async (taskId: string) => {
    setCancelling(taskId);
    try {
      await fetch(`/api/tasks/${encodeURIComponent(taskId)}`, { method: "DELETE" });
      await fetchTasks();
    } finally {
      setCancelling(null);
    }
  };

  const agents = data
    ? ["all", ...Array.from(new Set(data.history.map((e) => e.agent))).sort()]
    : ["all"];

  const rows = (data?.history ?? []).filter((e) => {
    if (agentFilter  !== "all" && e.agent   !== agentFilter)  return false;
    if (statusFilter !== "all" && e.outcome !== statusFilter) return false;
    return true;
  });

  const queueRows = Object.entries(data?.queue_depths ?? {})
    .filter(([, n]) => n > 0)
    .sort(([, a], [, b]) => b - a);

  return (
    <section className="flex flex-col gap-3 min-w-0">
      <h2 className="text-sm font-bold uppercase tracking-widest text-white">Task Queue</h2>

      {queueRows.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {queueRows.map(([q, n]) => (
            <span key={q} className="text-xs font-semibold bg-amber-900/50 border border-amber-700 text-amber-300 rounded px-2 py-0.5">
              {q} · {n}
            </span>
          ))}
        </div>
      )}

      {/* Filters */}
      <div className="flex items-center gap-2 flex-wrap">
        <select
          value={agentFilter}
          onChange={(e) => setAgentFilter(e.target.value)}
          className="bg-zinc-800 border border-zinc-600 text-zinc-200 text-xs rounded px-2 py-1 outline-none focus:border-zinc-400"
        >
          {agents.map((a) => (
            <option key={a} value={a}>{a === "all" ? "All agents" : a}</option>
          ))}
        </select>
        <div className="flex gap-1">
          {["all", "success", "failed", "pending"].map((s) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              className={`text-xs uppercase tracking-wide px-2 py-1 rounded border transition-colors ${
                statusFilter === s
                  ? "bg-zinc-600 border-zinc-500 text-white font-semibold"
                  : "bg-transparent border-zinc-700 text-zinc-400 hover:border-zinc-500 hover:text-zinc-200"
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto rounded border border-zinc-700">
        <table className="w-full text-xs border-collapse">
          <thead>
            <tr className="border-b border-zinc-700 bg-zinc-900 text-zinc-300 text-left">
              <th className="px-3 py-2 font-semibold uppercase tracking-wide">Agent</th>
              <th className="px-3 py-2 font-semibold uppercase tracking-wide">Action</th>
              <th className="px-3 py-2 font-semibold uppercase tracking-wide">Status</th>
              <th className="px-3 py-2 font-semibold uppercase tracking-wide">Time</th>
              <th className="px-3 py-2 font-semibold uppercase tracking-wide">Task ID</th>
              <th className="px-3 py-2 w-16"></th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={6} className="px-3 py-5 text-zinc-400 text-center">
                  No tasks
                </td>
              </tr>
            )}
            {rows.map((entry, i) => {
              const taskId = entry.task_ids?.[0];
              return (
                <tr key={i} className="border-b border-zinc-800 hover:bg-zinc-800/60 transition-colors">
                  <td className="px-3 py-2 text-zinc-200 font-semibold">{entry.agent}</td>
                  <td className="px-3 py-2 text-zinc-300">{entry.action?.replace(/_/g, " ")}</td>
                  <td className={`px-3 py-2 uppercase text-[11px] ${STATUS_COLORS[entry.outcome ?? "pending"] ?? "text-zinc-400"}`}>
                    {entry.outcome ?? "pending"}
                  </td>
                  <td className="px-3 py-2 text-zinc-400">
                    {entry.at ? new Date(entry.at).toLocaleTimeString() : "—"}
                  </td>
                  <td className="px-3 py-2 text-zinc-500 font-mono text-[10px] max-w-[120px] truncate">
                    {taskId ?? "—"}
                  </td>
                  <td className="px-3 py-2">
                    {taskId && (
                      <button
                        onClick={() => cancelTask(taskId)}
                        disabled={cancelling === taskId}
                        className="text-xs text-red-400 hover:text-red-300 disabled:opacity-40 font-semibold transition-colors"
                      >
                        {cancelling === taskId ? "…" : "cancel"}
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
