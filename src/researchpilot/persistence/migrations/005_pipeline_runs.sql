ALTER TABLE runs ADD COLUMN run_key TEXT;

CREATE UNIQUE INDEX runs_one_active_pipeline_idx
    ON runs(run_key)
    WHERE status = 'running' AND run_key IS NOT NULL;

CREATE TABLE run_steps (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    position INTEGER NOT NULL CHECK (position >= 0),
    status TEXT NOT NULL CHECK (status IN (
        'pending',
        'running',
        'succeeded',
        'failed',
        'skipped'
    )),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    result_json TEXT,
    error TEXT,
    started_at TEXT,
    finished_at TEXT,
    UNIQUE (run_id, name),
    UNIQUE (run_id, position)
);

CREATE INDEX run_steps_run_position_idx ON run_steps(run_id, position);
