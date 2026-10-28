-- Staging: one row per job, typed and flattened.
-- Grain: job. Source: jobs (the queue table) incl. worker-reported metrics in result JSON.
SELECT
    j.id                                         AS job_id,
    j.user_id,
    j.engine,
    j.type                                       AS job_type,
    j.status,
    j.char_count,
    j.attempts,
    j.created_at,
    {{ day("j.created_at") }}                    AS day,
    -- time from enqueue to the (latest) claim; includes retries' back-off
    CASE WHEN j.started_at IS NOT NULL
         THEN {{ ms_between("j.started_at", "j.created_at") }} END AS queue_ms,
    {{ json_num("j.result", "metrics", "processing_ms") }}    AS processing_ms,
    {{ json_num("j.result", "metrics", "synthesis_rtf") }}    AS synthesis_rtf,
    {{ json_num("j.result", "duration_seconds") }}            AS audio_seconds,
    CASE WHEN j.status = 'succeeded' THEN 1 ELSE 0 END        AS is_succeeded,
    CASE WHEN j.status = 'failed' THEN 1 ELSE 0 END           AS is_failed,
    CASE WHEN j.status = 'canceled' THEN 1 ELSE 0 END         AS is_canceled,
    CASE WHEN j.status IN ('succeeded', 'failed', 'canceled') THEN 1 ELSE 0 END AS is_terminal
FROM jobs AS j
