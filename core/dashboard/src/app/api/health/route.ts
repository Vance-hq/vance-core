export const runtime = "nodejs";
export const dynamic = "force-dynamic";

import * as fs from "fs";
import * as net from "net";
import { getRedis } from "@/lib/redis";
import { DATABASE_URL, SMTP_HOST, SMTP_PORT } from "@/lib/env";

async function checkRedis(): Promise<boolean> {
  try {
    const redis = getRedis();
    const pong = await Promise.race([
      redis.ping(),
      new Promise<never>((_, rej) => setTimeout(() => rej(new Error("timeout")), 2_000)),
    ]);
    return pong === "PONG";
  } catch {
    return false;
  }
}

async function checkPostgres(): Promise<boolean> {
  try {
    const { Pool } = await import("pg");
    const pool = new Pool({ connectionString: DATABASE_URL, max: 1 });
    try {
      await pool.query("SELECT 1");
      return true;
    } finally {
      await pool.end();
    }
  } catch {
    return false;
  }
}

function checkWireGuard(): boolean {
  try {
    const dev = fs.readFileSync("/proc/net/dev", "utf8");
    return dev.includes("wg0:");
  } catch {
    return false;
  }
}

function checkTcp(host: string, port: number, timeoutMs = 3_000): Promise<boolean> {
  return new Promise((resolve) => {
    const socket = net.createConnection({ host, port });
    const timer = setTimeout(() => {
      socket.destroy();
      resolve(false);
    }, timeoutMs);
    socket.on("connect", () => {
      clearTimeout(timer);
      socket.destroy();
      resolve(true);
    });
    socket.on("error", () => {
      clearTimeout(timer);
      resolve(false);
    });
  });
}

export async function GET() {
  const [redis, postgres, mailcow] = await Promise.all([
    checkRedis(),
    checkPostgres(),
    checkTcp(SMTP_HOST, SMTP_PORT),
  ]);
  const wireguard = checkWireGuard();

  return Response.json({
    redis,
    postgres,
    wireguard,
    mailcow,
    checked_at: new Date().toISOString(),
  });
}
