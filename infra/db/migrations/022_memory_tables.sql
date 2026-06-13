-- Memory agent tables (requires pgvector extension)
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS agent_memories (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    context_key TEXT NOT NULL,        -- agent name or topic key
    content     TEXT NOT NULL,
    embedding   vector(1536),
    metadata    JSONB NOT NULL DEFAULT '{}',
    expires_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_agent_memories_context ON agent_memories (context_key, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_memories_embedding ON agent_memories USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
