export type AgentStatus = "running" | "idle" | "error" | "unknown";

export interface AgentInfo {
  name: string;
  label: string;
  status: AgentStatus;
  lastTask?: {
    action: string;
    at: string;
    outcome?: string;
  } | null;
}

export interface AgentDomain {
  key: string;
  label: string;
  agents: AgentInfo[];
}

export type AgentsResponse = {
  timestamp: string;
  domains: {
    revenue: AgentInfo[];
    content: AgentInfo[];
    product: AgentInfo[];
    infra: AgentInfo[];
    intelligence: AgentInfo[];
  };
};

export const AGENT_LABELS: Record<string, string> = {
  sales: "Sales",
  finance: "Finance",
  analytics: "Analytics",
  ads: "Ads",
  forge: "Forge",
  marketing: "Marketing",
  content: "Content",
  viral: "Viral",
  seo: "SEO",
  video: "Video",
  onboarding: "Onboarding",
  support: "Support",
  reviews: "Reviews",
  outreach: "Outreach",
  research: "Research",
  dev: "Dev",
  qa: "QA",
  deploy: "Deploy",
  security: "Security",
  backup: "Backup",
  scaling: "Scaling",
  integrations: "Integrations",
  local_rank_grader: "LocalRankGrader",
  intel: "Intel",
  strategy: "Strategy",
  reporting: "Reporting",
  memory: "Memory",
  launch: "Launch",
};

export const DOMAIN_LABELS: Record<string, string> = {
  revenue: "Revenue",
  content: "Content",
  product: "Product",
  infra: "Infra",
  intelligence: "Intelligence",
};
