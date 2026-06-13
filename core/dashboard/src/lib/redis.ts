import Redis from "ioredis";
import { REDIS_URL } from "./env";

declare global {
  // eslint-disable-next-line no-var
  var _redisClient: Redis | undefined;
}

export function getRedis(): Redis {
  if (!global._redisClient) {
    global._redisClient = new Redis(REDIS_URL, {
      maxRetriesPerRequest: 1,
      enableReadyCheck: false,
      lazyConnect: true,
    });
  }
  return global._redisClient;
}

/** Creates a dedicated subscriber client — caller is responsible for quit(). */
export function createSubscriber(): Redis {
  return new Redis(REDIS_URL, {
    maxRetriesPerRequest: 1,
    enableReadyCheck: false,
    lazyConnect: true,
  });
}
