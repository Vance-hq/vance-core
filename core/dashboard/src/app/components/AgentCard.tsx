"use client";

import type { AgentInfo } from "@/index";

const STATUS_STYLES = {
  running: {
    dot: "bg-green-500",
    label: "text-green-400",
    border: "border-green-900",
    bg: "bg-green-950/20",
  },
  idle: {
    dot: "bg-zinc-600",
    label: "text-zinc-500",
    border: "border-zinc-800",
    bg: "bg-surface-2",
  },
  error: {
    dot: "bg-red-500 animate-pulse",
    label: "text-red-400",
    border: "border-red-900",
    bg: "bg-red-950/20",
  },
  unknown: {
    dot: "bg-zinc-700",
    label: "text-zinc-600",
    border: "border-zinc-800",
    bg: "bg-surface-2",
  },
} as const;

interface Props {
  agent: AgentInfo;
}

export default function AgentCard({ agent }: Props) {
  const style = STATUS_STYLES[agent.status] ?? STATUS_STYLES.unknown;

  return (
    <div
      className={`rounded border px-3 py-2 flex flex-col gap-1 ${style.bg} ${style.border}`}
    >
      <div className="flex items-center gap-2">
        <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${style.dot}`} />
        <span className="text-xs font-semibold tracking-wide text-zinc-200 truncate">
          {agent.label ?? agent.name}
        </span>
        <span className={`ml-auto text-[10px] uppercase tracking-widest ${style.label}`}>
          {agent.status}
        </span>
      </div>

      {agent.lastTask ? (
        <div className="pl-3.5 text-[11px] text-zinc-500 truncate">
          {agent.lastTask.action.replace(/_/g, " ")}
          {agent.lastTask.outcome && (
            <span
              className={
                agent.lastTask.outcome === "success"
                  ? "text-green-600"
                  : "text-red-600"
              }
            >
              {" "}· {agent.lastTask.outcome}
            </span>
          )}
        </div>
      ) : (
        <div className="pl-3.5 text-[11px] text-zinc-700">—</div>
      )}
    </div>
  );
}
