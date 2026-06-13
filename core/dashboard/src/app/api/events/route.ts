export const runtime = "nodejs";
export const dynamic = "force-dynamic";

import { createSubscriber } from "@/lib/redis";

export async function GET(request: Request) {
  const { signal } = request;
  const enc = new TextEncoder();

  const stream = new ReadableStream<Uint8Array>({
    async start(ctrl) {
      const sub = createSubscriber();

      const cleanup = () => {
        sub.unsubscribe("vance:events").catch(() => {});
        sub.quit().catch(() => {});
        try { ctrl.close(); } catch { /* ignore */ }
      };

      signal.addEventListener("abort", cleanup);

      try {
        await sub.subscribe("vance:events");
      } catch (err) {
        ctrl.enqueue(
          enc.encode(
            `data: ${JSON.stringify({ type: "ERROR", message: String(err) })}\n\n`
          )
        );
        cleanup();
        return;
      }

      sub.on("message", (_channel: string, message: string) => {
        try {
          ctrl.enqueue(enc.encode(`data: ${message}\n\n`));
        } catch { /* stream closed */ }
      });

      sub.on("error", () => cleanup());

      // Keep-alive so browser/proxy doesn't time out.
      const ka = setInterval(() => {
        try { ctrl.enqueue(enc.encode(": ka\n\n")); }
        catch { clearInterval(ka); }
      }, 20_000);

      signal.addEventListener("abort", () => clearInterval(ka));
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
