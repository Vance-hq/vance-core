"use client";

import type { AgentInfo } from "@/index";

const STATUS_STYLES = {
  running: {
    dot:    "bg-green-400",
    label:  "text-green-400 font-bold",
    border: "border-green-800",
    bg:     "bg-green-950/30",
    name:   "text-white",
  },
  idle: {
    dot:    "bg-zinc-500",
    label:  "text-zinc-500",
    border: "border-zinc-700",
    bg:     "bg-zinc-900",
    name:   "text-zinc-300",
  },
  error: {
    dot:    "bg-red-500 animate-pulse",
    label:  "text-red-400 font-bold",
    border: "border-red-800",
    bg:     "bg-red-950/30",
    name:   "text-white",
  },
  unknown: {
    dot:    "bg-zinc-600",
    label:  "text-zinc-600",
    border: "border-zinc-800",
    bg:     "bg-zinc-900",
    name:   "text-zinc-400",
  },
} as const;

export default function AgentCard({ agent }: { agent: AgentInfo }) {
  const s = STATUS_STYLES[agent.status] ?? STATUS_STYLES.unknown;

  return (
    <div className={`rounded border px-3 py-2 flex flex-col gap-1 ${s.bg} ${s.border}`}>
      <div className="flex items-center gap-2">
        <span className={`w-2 h-2 rounded-full flex-shrink-0 ${s.dot}`} />
        <span className={`text-xs font-semibold truncate ${s.name}`}>
          {agent.label ?? agent.name}
        </span>
        <span className={`ml-auto text-[10px] uppercase tracking-widest ${s.label}`}>
          {agent.status}
        </span>
      </div>
      {agent.lastTask ? (
        <div className="pl-4 text-[11px] text-zinc-400 truncate">
          {agent.lastTask.action.replace(/_/g, " ")}
          {agent.lastTask.outcome && (
            <span className={agent.lastTask.outcome === "success" ? "text-green-500" : "text-red-400"}>
              {" "}· {agent.lastTask.outcome}
            </span>
          )}
        </div>
      ) : (
        <div className="pl-4 text-[11px] text-zinc-600">—</div>
      )}
    </div>
  );
}
