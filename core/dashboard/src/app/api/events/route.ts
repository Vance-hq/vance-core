export const runtime = "nodejs";
export const dynamic = "force-dynamic";

import { createSubscriber } from "@/lib/redis";

const RETRY_DELAY_MS = 10_000;

export async function GET(request: Request) {
  const { signal } = request;
  const enc = new TextEncoder();

  const stream = new ReadableStream<Uint8Array>({
    async start(ctrl) {
      const enqueue = (data: string) => {
        try { ctrl.enqueue(enc.encode(data)); } catch { /* stream closed */ }
      };

      // Keep-alive ping — prevents browser/proxy from closing idle connections.
      const ka = setInterval(() => enqueue(": ka\n\n"), 20_000);

      // Retry loop: if Redis is down we stay open and retry every RETRY_DELAY_MS.
      // This stops EventSource from spamming reconnects every ~3 s.
      while (!signal.aborted) {
        const sub = createSubscriber();

        try {
          await sub.subscribe("vance:events");
          enqueue(`data: ${JSON.stringify({ type: "CONNECTED" })}\n\n`);

          // Block until the subscriber errors or the request is aborted.
          await new Promise<void>((resolve) => {
            sub.on("message", (_ch: string, msg: string) => enqueue(`data: ${msg}\n\n`));
            sub.on("error",   () => resolve());
            signal.addEventListener("abort", () => resolve(), { once: true });
          });
        } catch {
          enqueue(`data: ${JSON.stringify({ type: "REDIS_UNAVAILABLE" })}\n\n`);
        } finally {
          sub.unsubscribe().catch(() => {});
          sub.quit().catch(() => {});
        }

        if (!signal.aborted) {
          // Brief pause before retrying so we don't hammer a down Redis.
          await new Promise<void>((resolve) => {
            const t = setTimeout(resolve, RETRY_DELAY_MS);
            signal.addEventListener("abort", () => { clearTimeout(t); resolve(); }, { once: true });
          });
        }
      }

      clearInterval(ka);
      try { ctrl.close(); } catch { /* ignore */ }
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
