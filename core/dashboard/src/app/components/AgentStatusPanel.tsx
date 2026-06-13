"use client";

import { useEffect, useState } from "react";
import type { AgentsResponse, AgentInfo } from "@/index";
import { AGENT_LABELS, DOMAIN_LABELS } from "@/index";
import AgentCard from "./AgentCard";

const DOMAIN_ORDER = ["revenue", "content", "product", "infra", "intelligence"] as const;
type Domain = (typeof DOMAIN_ORDER)[number];

const DOMAIN_ACCENT: Record<Domain, string> = {
  revenue:      "text-green-400",
  content:      "text-blue-400",
  product:      "text-amber-400",
  infra:        "text-violet-400",
  intelligence: "text-pink-400",
};

function enrichAgents(raw: AgentInfo[]): AgentInfo[] {
  return raw.map((a) => ({ ...a, label: AGENT_LABELS[a.name] ?? a.name }));
}

export default function AgentStatusPanel() {
  const [data, setData] = useState<AgentsResponse | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    const es = new EventSource("/api/agents/sse");
    es.onmessage = (e) => {
      try {
        const parsed = JSON.parse(e.data) as AgentsResponse & { error?: string };
        if (parsed.error) { setError(true); return; }
        setError(false);
        setData(parsed);
      } catch { /* ignore */ }
    };
    es.onerror = () => setError(true);
    return () => es.close();
  }, []);

  const totalAgents = data ? Object.values(data.domains).flat().length : 0;
  const running     = data ? Object.values(data.domains).flat().filter((a) => a.status === "running").length : 0;

  return (
    <section className="flex flex-col gap-4">
      <div className="flex items-baseline justify-between">
        <h2 className="text-sm font-bold uppercase tracking-widest text-white">Agent Status</h2>
        <span className="text-xs text-zinc-400">
          {data
            ? `${running} / ${totalAgents} running`
            : error
            ? <span className="text-red-400 font-semibold">orchestrator unreachable</span>
            : "connecting…"}
        </span>
      </div>

      {data && (
        <div className="flex flex-col gap-5">
          {DOMAIN_ORDER.map((domain) => {
            const agents = enrichAgents(data.domains[domain] ?? []);
            return (
              <div key={domain}>
                <div className={`text-xs font-bold uppercase tracking-widest mb-2 ${DOMAIN_ACCENT[domain]}`}>
                  {DOMAIN_LABELS[domain]}
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-2">
                  {agents.map((a) => <AgentCard key={a.name} agent={a} />)}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {!data && !error && (
        <div className="text-sm text-zinc-400 animate-pulse">Loading agent status…</div>
      )}
      {error && (
        <div className="text-sm font-semibold text-red-400 bg-red-950/30 border border-red-800 rounded px-3 py-2">
          ✕ Cannot reach orchestrator at localhost:7700
        </div>
      )}
    </section>
  );
}
