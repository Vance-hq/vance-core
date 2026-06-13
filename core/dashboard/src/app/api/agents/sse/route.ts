export const runtime = "nodejs";
export const dynamic = "force-dynamic";

import { ORCHESTRATOR_URL } from "@/lib/env";

export async function GET(request: Request) {
  const { signal } = request;
  const enc = new TextEncoder();

  const stream = new ReadableStream<Uint8Array>({
    async start(ctrl) {
      const send = async () => {
        try {
          const res = await fetch(`${ORCHESTRATOR_URL}/agents`, {
            signal: AbortSignal.timeout(4_000),
          });
          const data = await res.json();
          ctrl.enqueue(enc.encode(`data: ${JSON.stringify(data)}\n\n`));
        } catch {
          ctrl.enqueue(
            enc.encode(`data: ${JSON.stringify({ error: "orchestrator_unreachable" })}\n\n`)
          );
        }
      };

      await send();

      const iv = setInterval(async () => {
        if (signal.aborted) {
          clearInterval(iv);
          try { ctrl.close(); } catch { /* already closed */ }
          return;
        }
        await send();
      }, 5_000);

      // Keep-alive comment every 20 s so proxies don't close the connection.
      const ka = setInterval(() => {
        try { ctrl.enqueue(enc.encode(": ka\n\n")); } catch { clearInterval(ka); }
      }, 20_000);

      signal.addEventListener("abort", () => {
        clearInterval(iv);
        clearInterval(ka);
        try { ctrl.close(); } catch { /* ignore */ }
      });
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
}
