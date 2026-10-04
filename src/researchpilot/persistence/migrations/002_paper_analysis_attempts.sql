CREATE TABLE paper_analysis_attempts (
    id INTEGER PRIMARY KEY,
    paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    result_json TEXT,
    raw_output TEXT,
    error TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE (paper_id, provider, model, attempt_number)
);

CREATE UNIQUE INDEX paper_analysis_one_success_idx
    ON paper_analysis_attempts(paper_id, provider, model)
    WHERE status = 'succeeded';

CREATE INDEX paper_analysis_status_idx
    ON paper_analysis_attempts(status, started_at DESC);
