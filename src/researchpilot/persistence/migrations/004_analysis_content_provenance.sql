ALTER TABLE paper_analysis_attempts
    ADD COLUMN content_kind TEXT NOT NULL DEFAULT 'abstract'
    CHECK (content_kind IN ('abstract', 'full_paper'));

ALTER TABLE paper_analysis_attempts
    ADD COLUMN content_trace_json TEXT NOT NULL
    DEFAULT '{"kind":"abstract","references":[],"truncated":false,"warnings":[]}';

DROP INDEX paper_analysis_one_success_idx;

CREATE UNIQUE INDEX paper_analysis_one_success_idx
    ON paper_analysis_attempts(paper_id, provider, model, content_kind)
    WHERE status = 'succeeded';

ALTER TABLE repository_analysis_attempts
    ADD COLUMN content_kind TEXT NOT NULL DEFAULT 'readme'
    CHECK (content_kind IN (
        'readme',
        'source_files',
        'readme_and_source_files'
    ));

ALTER TABLE repository_analysis_attempts
    ADD COLUMN content_trace_json TEXT NOT NULL
    DEFAULT '{"kind":"readme","references":[],"truncated":false,"warnings":[]}';

DROP INDEX repository_analysis_one_success_idx;

CREATE UNIQUE INDEX repository_analysis_one_success_idx
    ON repository_analysis_attempts(
        repository_id,
        provider,
        model,
        content_kind
    )
    WHERE status = 'succeeded';
