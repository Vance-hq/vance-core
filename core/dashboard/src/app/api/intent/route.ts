export const runtime = "nodejs";

import { ORCHESTRATOR_URL } from "@/lib/env";

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: "invalid json" }, { status: 400 });
  }

  try {
    const res = await fetch(`${ORCHESTRATOR_URL}/intent`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(10_000),
    });
    const data = await res.json();
    return Response.json(data, { status: res.status });
  } catch (err) {
    return Response.json(
      { error: "orchestrator_unreachable", detail: String(err) },
      { status: 502 }
    );
  }
}
