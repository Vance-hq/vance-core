export const runtime = "nodejs";
export const dynamic = "force-dynamic";

import { DATABASE_URL } from "@/lib/env";

export async function GET() {
  try {
    const { Pool } = await import("pg");
    const pool = new Pool({ connectionString: DATABASE_URL, max: 1 });

    const today = new Date().toISOString().slice(0, 10); // YYYY-MM-DD

    const [sendsRes, openRes, repliesRes, unsubRes] = await Promise.all([
      pool.query(
        `SELECT COUNT(*) AS n FROM forge_emails WHERE sent_at >= $1::date`,
        [today]
      ),
      pool.query(
        `SELECT
           COUNT(*) FILTER (WHERE opened_at IS NOT NULL) AS opened,
           COUNT(*) AS total
         FROM forge_emails
         WHERE sent_at >= $1::date`,
        [today]
      ),
      pool.query(
        `SELECT COUNT(*) AS n FROM forge_emails WHERE replied_at >= $1::date`,
        [today]
      ),
      pool.query(
        `SELECT COUNT(*) AS n
         FROM outreach_sequences
         WHERE status = 'unsubscribed'
           AND created_at >= $1::date`,
        [today]
      ),
    ]);

    await pool.end();

    const sends = parseInt(sendsRes.rows[0]?.n ?? "0", 10);
    const opened = parseInt(openRes.rows[0]?.opened ?? "0", 10);
    const total = parseInt(openRes.rows[0]?.total ?? "0", 10);
    const open_rate = total > 0 ? Math.round((opened / total) * 100) : null;
    const replies = parseInt(repliesRes.rows[0]?.n ?? "0", 10);
    const unsubscribes = parseInt(unsubRes.rows[0]?.n ?? "0", 10);

    return Response.json({ sends, open_rate, replies, unsubscribes });
  } catch (err) {
    return Response.json(
      { error: String(err), sends: null, open_rate: null, replies: null, unsubscribes: null },
      { status: 500 }
    );
  }
}
