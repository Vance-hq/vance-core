export const runtime = "nodejs";

import { getRedis } from "@/lib/redis";

// Celery revokes tasks by adding the task ID to the "celery-task-revoked" set.
// Workers check this set before executing.
export async function DELETE(
  _request: Request,
  { params }: { params: { id: string } }
) {
  const { id } = params;
  if (!id) {
    return Response.json({ error: "task id required" }, { status: 400 });
  }

  try {
    const redis = getRedis();
    // Celery's revoked set key — workers check this before consuming.
    await redis.sadd("celery-task-revoked", id);
    // Also publish a cancel event so the event feed shows it.
    await redis.publish(
      "vance:events",
      JSON.stringify({ type: "TASK_CANCELLED", task_id: id, at: new Date().toISOString() })
    );
    return Response.json({ cancelled: true, task_id: id });
  } catch (err) {
    return Response.json({ error: String(err) }, { status: 500 });
  }
}
