export const runtime = "nodejs";
export const dynamic = "force-dynamic";

import { ORCHESTRATOR_URL } from "@/lib/env";
import { getRedis } from "@/lib/redis";

const AGENT_QUEUES = [
  "marketing", "outreach", "sales", "reviews", "ads", "content", "video",
  "viral", "seo", "support", "dev", "qa", "deploy", "security", "backup",
  "scaling", "onboarding", "launch", "research", "intel", "strategy",
  "finance", "analytics", "reporting", "memory", "forge", "localrankgrader",
  "integrations",
];

export async function GET() {
  // Session history from orchestrator (completed/recent tasks).
  let history: unknown[] = [];
  try {
    const res = await fetch(`${ORCHESTRATOR_URL}/status`, {
      signal: AbortSignal.timeout(3_000),
    });
    const data = (await res.json()) as { session?: { history?: unknown[] } };
    history = data.session?.history ?? [];
  } catch { /* orchestrator down */ }

  // Queue depths from Redis (pending tasks per agent).
  const redis = getRedis();
  const depths: Record<string, number> = {};
  await Promise.all(
    AGENT_QUEUES.map(async (q) => {
      try {
        depths[q] = await redis.llen(q);
      } catch {
        depths[q] = -1;
      }
    })
  );

  return Response.json({ history, queue_depths: depths });
}
