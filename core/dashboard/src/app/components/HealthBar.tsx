"use client";

import { useEffect, useRef, useState } from "react";

interface HealthStatus {
  redis: boolean;
  postgres: boolean;
  wireguard: boolean;
  mailcow: boolean;
  checked_at: string;
}

const CHECKS: { key: keyof HealthStatus; label: string }[] = [
  { key: "redis",     label: "REDIS"     },
  { key: "postgres",  label: "POSTGRES"  },
  { key: "wireguard", label: "WIREGUARD" },
  { key: "mailcow",   label: "MAILCOW"   },
];

function Indicator({ label, ok }: { label: string; ok: boolean | undefined }) {
  return (
    <div className="flex items-center gap-1.5 text-xs">
      <span
        className={`inline-block w-2 h-2 rounded-full flex-shrink-0 ${
          ok === undefined
            ? "bg-zinc-600"
            : ok
            ? "bg-green-500"
            : "bg-red-500 animate-pulse"
        }`}
      />
      <span className={ok === false ? "text-red-400" : "text-zinc-400"}>
        {label}
      </span>
    </div>
  );
}

export default function HealthBar() {
  const [status, setStatus] = useState<HealthStatus | null>(null);
  const prevRef = useRef<HealthStatus | null>(null);

  const poll = async () => {
    try {
      const res = await fetch("/api/health");
      const data = (await res.json()) as HealthStatus;
      // Browser notification for any new failure.
      if (prevRef.current) {
        for (const { key, label } of CHECKS) {
          if (prevRef.current[key] && !data[key]) {
            if (Notification.permission === "granted") {
              new Notification(`Vance HQ — ${label} DOWN`, {
                body: `${label} health check failed at ${new Date().toLocaleTimeString()}`,
              });
            }
          }
        }
      }
      prevRef.current = data;
      setStatus(data);
    } catch { /* silent */ }
  };

  useEffect(() => {
    if (Notification.permission === "default") {
      Notification.requestPermission().catch(() => {});
    }
    poll();
    const id = setInterval(poll, 30_000);
    return () => clearInterval(id);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="sticky top-0 z-50 flex items-center justify-between px-4 py-2 bg-surface-1 border-b border-zinc-800">
      <span className="text-xs text-zinc-600 font-mono tracking-widest uppercase">
        vance hq
      </span>
      <div className="flex items-center gap-4">
        {CHECKS.map(({ key, label }) => (
          <Indicator
            key={key}
            label={label}
            ok={status ? (status[key] as boolean) : undefined}
          />
        ))}
        {status && (
          <span className="text-xs text-zinc-700 pl-2 border-l border-zinc-800">
            {new Date(status.checked_at).toLocaleTimeString()}
          </span>
        )}
      </div>
    </div>
  );
}
