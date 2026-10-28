-- Mart: per day x engine for finished synthesis jobs.
-- Volume, failure rate, and nearest-rank p50/p95 of processing time and queue wait.
-- Percentiles use window functions + integer ceil(n*p) so the same SQL runs on
-- Postgres and SQLite (no percentile_cont in SQLite).
WITH synth AS (
    SELECT * FROM {{ ref("stg_jobs") }}
    WHERE job_type = 'synthesize' AND is_terminal = 1
),
proc_ranked AS (
    SELECT day, engine, processing_ms,
           ROW_NUMBER() OVER (PARTITION BY day, engine ORDER BY processing_ms) AS rnk,
           COUNT(*)     OVER (PARTITION BY day, engine)                        AS n
    FROM synth
    WHERE is_succeeded = 1 AND processing_ms IS NOT NULL
),
queue_ranked AS (
    SELECT day, engine, queue_ms,
           ROW_NUMBER() OVER (PARTITION BY day, engine ORDER BY queue_ms) AS rnk,
           COUNT(*)     OVER (PARTITION BY day, engine)                   AS n
    FROM synth
    WHERE queue_ms IS NOT NULL
),
proc_pct AS (
    SELECT day, engine,
           MAX(CASE WHEN rnk = (n * 50 + 99) / 100 THEN processing_ms END) AS p50_processing_ms,
           MAX(CASE WHEN rnk = (n * 95 + 99) / 100 THEN processing_ms END) AS p95_processing_ms
    FROM proc_ranked GROUP BY day, engine
),
queue_pct AS (
    SELECT day, engine,
           MAX(CASE WHEN rnk = (n * 50 + 99) / 100 THEN queue_ms END) AS p50_queue_ms,
           MAX(CASE WHEN rnk = (n * 95 + 99) / 100 THEN queue_ms END) AS p95_queue_ms
    FROM queue_ranked GROUP BY day, engine
),
agg AS (
    SELECT day, engine,
           COUNT(*)                                                 AS jobs,
           SUM(is_succeeded)                                        AS succeeded,
           SUM(is_failed)                                           AS failed,
           SUM(is_canceled)                                         AS canceled,
           SUM(CASE WHEN is_succeeded = 1 THEN char_count ELSE 0 END) AS chars,
           SUM(COALESCE(audio_seconds, 0))                          AS audio_seconds,
           AVG(synthesis_rtf)                                       AS avg_synthesis_rtf,
           COUNT(DISTINCT user_id)                                  AS users
    FROM synth GROUP BY day, engine
)
SELECT
    a.day, a.engine, a.jobs, a.succeeded, a.failed, a.canceled, a.chars, a.audio_seconds,
    a.avg_synthesis_rtf, a.users,
    CAST(a.failed AS DOUBLE PRECISION) / NULLIF(a.succeeded + a.failed, 0) AS failure_rate,
    p.p50_processing_ms, p.p95_processing_ms,
    q.p50_queue_ms, q.p95_queue_ms
FROM agg AS a
LEFT JOIN proc_pct AS p ON p.day = a.day AND p.engine = a.engine
LEFT JOIN queue_pct AS q ON q.day = a.day AND q.engine = a.engine
