"use client";

import { useEffect, useState, useCallback } from "react";
import type { AgentsResponse, AgentInfo } from "../index";
import { AGENT_LABELS, DOMAIN_LABELS } from "../index";

const ORCHESTRATOR_URL = process.env.NEXT_PUBLIC_ORCHESTRATOR_URL ?? "http://localhost:7700";
const POLL_MS = 10_000;

const DOMAIN_ORDER = ["revenue", "content", "product", "infra", "intelligence"] as const;

type Domain = (typeof DOMAIN_ORDER)[number];

const DOMAIN_COLORS: Record<Domain, string> = {
  revenue: "#4ade80",
  content: "#60a5fa",
  product: "#f59e0b",
  infra: "#a78bfa",
  intelligence: "#f472b6",
};

function statusDot(status: AgentInfo["status"]) {
  const color = status === "running" ? "#4ade80" : status === "error" ? "#f87171" : "#6b7280";
  return (
    <span
      style={{
        display: "inline-block",
        width: 8,
        height: 8,
        borderRadius: "50%",
        background: color,
        marginRight: 6,
        flexShrink: 0,
      }}
    />
  );
}

function AgentCard({ agent }: { agent: AgentInfo }) {
  const label = AGENT_LABELS[agent.name] ?? agent.name;
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 4,
        padding: "10px 14px",
        background: "#1a1a1a",
        borderRadius: 6,
        border: "1px solid #2a2a2a",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", fontSize: 13, fontWeight: 600 }}>
        {statusDot(agent.status)}
        {label}
      </div>
      {agent.lastTask ? (
        <div style={{ fontSize: 11, color: "#6b7280", paddingLeft: 14 }}>
          {agent.lastTask.action.replace(/_/g, " ")}
          {agent.lastTask.at ? ` · ${new Date(agent.lastTask.at).toLocaleTimeString()}` : ""}
        </div>
      ) : (
        <div style={{ fontSize: 11, color: "#3a3a3a", paddingLeft: 14 }}>no recent task</div>
      )}
    </div>
  );
}

function DomainPanel({
  domain,
  agents,
}: {
  domain: Domain;
  agents: AgentInfo[];
}) {
  const color = DOMAIN_COLORS[domain];
  const label = DOMAIN_LABELS[domain];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div
        style={{
          fontSize: 11,
          fontWeight: 700,
          letterSpacing: "0.1em",
          textTransform: "uppercase",
          color,
          borderBottom: `1px solid ${color}33`,
          paddingBottom: 6,
        }}
      >
        {label}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
        {agents.map((a) => (
          <AgentCard key={a.name} agent={a} />
        ))}
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const [data, setData] = useState<AgentsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const fetch_agents = useCallback(async () => {
    try {
      const res = await fetch(`${ORCHESTRATOR_URL}/agents`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = (await res.json()) as AgentsResponse;
      setData(json);
      setLastUpdated(new Date());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "fetch error");
    }
  }, []);

  useEffect(() => {
    fetch_agents();
    const id = setInterval(fetch_agents, POLL_MS);
    return () => clearInterval(id);
  }, [fetch_agents]);

  return (
    <div style={{ padding: "32px 40px", maxWidth: 1200, margin: "0 auto" }}>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          marginBottom: 32,
        }}
      >
        <h1 style={{ fontSize: 22, fontWeight: 700, letterSpacing: "0.05em", color: "#ffffff" }}>
          VANCE HQ
        </h1>
        <span style={{ fontSize: 11, color: "#4b5563" }}>
          {error
            ? `error: ${error}`
            : lastUpdated
            ? `updated ${lastUpdated.toLocaleTimeString()}`
            : "connecting…"}
        </span>
      </div>

      {data ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>
          {DOMAIN_ORDER.map((domain) => (
            <DomainPanel
              key={domain}
              domain={domain}
              agents={data.domains[domain] ?? []}
            />
          ))}
        </div>
      ) : (
        <div style={{ color: "#4b5563", fontSize: 13 }}>
          {error ? `Failed to connect: ${error}` : "Loading agent status…"}
        </div>
      )}
    </div>
  );
}
