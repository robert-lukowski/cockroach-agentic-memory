SET CLUSTER SETTING feature.vector_index.enabled = true;

CREATE TABLE IF NOT EXISTS incident_memories (
    id UUID PRIMARY KEY,
    scope STRING NOT NULL,
    service STRING NOT NULL,
    environment STRING NOT NULL,
    title STRING NOT NULL,
    symptoms STRING NOT NULL,
    root_cause STRING NOT NULL,
    resolution STRING NOT NULL,
    tags JSONB NOT NULL DEFAULT '[]'::JSONB,
    metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
    embedding VECTOR(1024) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    VECTOR INDEX incident_memories_scope_embedding_idx (
        scope,
        embedding vector_cosine_ops
    )
);
