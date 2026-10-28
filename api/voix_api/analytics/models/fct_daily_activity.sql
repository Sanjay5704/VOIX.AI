-- Mart: platform activity per day (all job types, all statuses).
-- DAU = distinct users who created at least one job that day.
SELECT
    day,
    COUNT(DISTINCT user_id)                                            AS active_users,
    COUNT(*)                                                           AS jobs,
    SUM(CASE WHEN job_type = 'synthesize' THEN char_count ELSE 0 END)  AS chars_requested,
    SUM(CASE WHEN is_succeeded = 1 AND job_type = 'synthesize'
             THEN COALESCE(audio_seconds, 0) ELSE 0 END)               AS audio_seconds,
    SUM(is_failed)                                                     AS failed,
    SUM(CASE WHEN job_type = 'prepare_voice' THEN 1 ELSE 0 END)        AS voice_clones
FROM {{ ref("stg_jobs") }}
GROUP BY day
