CREATE TABLE repositories (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    full_name TEXT NOT NULL,
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    readme TEXT,
    url TEXT NOT NULL,
    default_branch TEXT NOT NULL,
    primary_language TEXT,
    topics_json TEXT NOT NULL,
    stars INTEGER NOT NULL CHECK (stars >= 0),
    forks INTEGER NOT NULL CHECK (forks >= 0),
    archived INTEGER NOT NULL CHECK (archived IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    pushed_at TEXT,
    discovered_at TEXT NOT NULL,
    UNIQUE (source, external_id)
);

CREATE INDEX repositories_updated_at_idx ON repositories(updated_at DESC);

CREATE TABLE repository_analysis_attempts (
    id INTEGER PRIMARY KEY,
    repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    result_json TEXT,
    raw_output TEXT,
    error TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE (repository_id, provider, model, attempt_number)
);

CREATE UNIQUE INDEX repository_analysis_one_success_idx
    ON repository_analysis_attempts(repository_id, provider, model)
    WHERE status = 'succeeded';

CREATE INDEX repository_analysis_status_idx
    ON repository_analysis_attempts(status, started_at DESC);
