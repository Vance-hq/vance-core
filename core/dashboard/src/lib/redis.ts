import Redis from "ioredis";
import { REDIS_URL } from "./env";

declare global {
  // eslint-disable-next-line no-var
  var _redisClient: Redis | undefined;
}

const BASE_OPTIONS = {
  maxRetriesPerRequest: 0,  // fail fast per command; don't block callers
  enableReadyCheck: false,
  lazyConnect: true,
  // Exponential back-off: 2s → 4s → … capped at 30s, stop after 10 attempts.
  retryStrategy: (times: number) =>
    times > 10 ? null : Math.min(2 ** times * 1_000, 30_000),
} as const;

function silence(client: Redis): Redis {
  // Must attach a listener or Node.js treats emitted 'error' as uncaught exception.
  client.on("error", () => {});
  return client;
}

export function getRedis(): Redis {
  if (!global._redisClient) {
    global._redisClient = silence(new Redis(REDIS_URL, BASE_OPTIONS));
  }
  return global._redisClient;
}

/** Dedicated subscriber — caller must call quit() when done. */
export function createSubscriber(): Redis {
  return silence(new Redis(REDIS_URL, BASE_OPTIONS));
}
