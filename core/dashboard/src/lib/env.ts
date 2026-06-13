export const ORCHESTRATOR_URL =
  process.env.ORCHESTRATOR_URL ?? "http://localhost:7700";

export const REDIS_URL =
  process.env.REDIS_URL ?? `redis://:${process.env.REDIS_PASSWORD ?? ""}@localhost:6379`;

export const DATABASE_URL =
  process.env.DATABASE_URL ??
  `postgresql://${process.env.POSTGRES_USER ?? "vance"}:${process.env.POSTGRES_PASSWORD ?? ""}@localhost:5432/${process.env.POSTGRES_DB ?? "vance"}`;

export const SMTP_HOST = process.env.SMTP_HOST ?? "localhost";
export const SMTP_PORT = parseInt(process.env.SMTP_PORT ?? "25", 10);
