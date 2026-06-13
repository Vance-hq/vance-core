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
  success: "text-green-400",
  failed:  "text-red-400",
  pending: "text-amber-400",
};

export default function TaskQueueView() {
  const [data, setData] = useState<TasksData | null>(null);
  const [agentFilter, setAgentFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [cancelling, setCancelling] = useState<string | null>(null);

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
    if (agentFilter !== "all" && e.agent !== agentFilter) return false;
    if (statusFilter !== "all" && e.outcome !== statusFilter) return false;
    return true;
  });

  // Non-empty queues in descending order.
  const queueRows = Object.entries(data?.queue_depths ?? {})
    .filter(([, n]) => n > 0)
    .sort(([, a], [, b]) => b - a);

  return (
    <section className="flex flex-col gap-3 min-w-0">
      <h2 className="text-xs uppercase tracking-widest text-zinc-500">Task Queue</h2>

      {/* Queue depth badges */}
      {queueRows.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {queueRows.map(([q, n]) => (
            <span
              key={q}
              className="text-[10px] bg-amber-950/40 border border-amber-900/50 text-amber-400 rounded px-1.5 py-0.5"
            >
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
          className="bg-surface-3 border border-zinc-700 text-zinc-300 text-xs rounded px-2 py-1 outline-none focus:border-zinc-500"
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
              className={`text-[10px] uppercase tracking-wide px-2 py-1 rounded border transition-colors ${
                statusFilter === s
                  ? "bg-zinc-700 border-zinc-600 text-zinc-200"
                  : "bg-transparent border-zinc-800 text-zinc-600 hover:border-zinc-600 hover:text-zinc-400"
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto rounded border border-zinc-800">
        <table className="w-full text-[11px] border-collapse">
          <thead>
            <tr className="border-b border-zinc-800 text-zinc-500 text-left">
              <th className="px-3 py-2 font-normal">AGENT</th>
              <th className="px-3 py-2 font-normal">ACTION</th>
              <th className="px-3 py-2 font-normal">STATUS</th>
              <th className="px-3 py-2 font-normal">TIME</th>
              <th className="px-3 py-2 font-normal">TASK ID</th>
              <th className="px-3 py-2 font-normal w-16"></th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={6} className="px-3 py-4 text-zinc-700 text-center">
                  No tasks
                </td>
              </tr>
            )}
            {rows.map((entry, i) => {
              const taskId = entry.task_ids?.[0];
              return (
                <tr
                  key={i}
                  className="border-b border-zinc-900 hover:bg-zinc-900/50 transition-colors"
                >
                  <td className="px-3 py-2 text-zinc-300">{entry.agent}</td>
                  <td className="px-3 py-2 text-zinc-400">{entry.action?.replace(/_/g, " ")}</td>
                  <td className={`px-3 py-2 uppercase ${STATUS_COLORS[entry.outcome ?? "pending"] ?? "text-zinc-500"}`}>
                    {entry.outcome ?? "pending"}
                  </td>
                  <td className="px-3 py-2 text-zinc-600">
                    {entry.at ? new Date(entry.at).toLocaleTimeString() : "—"}
                  </td>
                  <td className="px-3 py-2 text-zinc-700 font-mono text-[10px] max-w-[120px] truncate">
                    {taskId ?? "—"}
                  </td>
                  <td className="px-3 py-2">
                    {taskId && (
                      <button
                        onClick={() => cancelTask(taskId)}
                        disabled={cancelling === taskId}
                        className="text-[10px] text-red-600 hover:text-red-400 disabled:opacity-40 transition-colors"
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
