-- Backup agent tables

CREATE TABLE IF NOT EXISTS backup_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    backup_type     TEXT NOT NULL,   -- postgres | files | mailcow | restore_verify
    file_path       TEXT NOT NULL,   -- storage key (or empty for restore_verify)
    size_bytes      BIGINT NOT NULL DEFAULT 0,
    duration_seconds NUMERIC(10, 2) NOT NULL DEFAULT 0,
    verified        BOOLEAN NOT NULL DEFAULT FALSE,
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_backup_log_type_created ON backup_log (backup_type, created_at DESC);
