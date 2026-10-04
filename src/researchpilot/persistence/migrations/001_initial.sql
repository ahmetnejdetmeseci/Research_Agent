CREATE TABLE papers (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    abstract TEXT NOT NULL,
    authors_json TEXT NOT NULL,
    published_at TEXT NOT NULL,
    updated_at TEXT,
    url TEXT NOT NULL,
    pdf_url TEXT,
    categories_json TEXT NOT NULL,
    discovered_at TEXT NOT NULL,
    UNIQUE (source, external_id)
);

CREATE INDEX papers_published_at_idx ON papers(published_at DESC);

CREATE TABLE runs (
    id INTEGER PRIMARY KEY,
    command TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    error TEXT
);

CREATE INDEX runs_started_at_idx ON runs(started_at DESC);
