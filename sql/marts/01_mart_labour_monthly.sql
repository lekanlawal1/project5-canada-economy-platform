-- Labour market by geography, gender and age group, seasonally adjusted (the basis of
-- every LFS headline). One row per month.
--
-- Method notes (each is a deliberate choice):
--   * Prior-period values are joined on calendar month (month - 1 month, month - 12
--     months), NOT taken with LAG(). Suppressed months leave gaps inside small series, and
--     LAG() would silently compare against the wrong month.
--   * Changes are rounded to 1 decimal, the precision StatCan publishes, so float noise
--     like 5.1999999 never reaches the dashboard or the AI briefing.
--   * "Significant" means the change exceeds 1.96 x StatCan's own standard error of that
--     change (95% confidence). This is how StatCan itself describes LFS moves, and it stops
--     the dashboard from narrating sampling noise as news.
--   * Anomaly score is a robust z-score of the monthly change against the PRIOR 36 months
--     (median and MAD, not mean and standard deviation). Why: after 2020 the COVID spike
--     inflated the standard deviation for three years, so a classic z-score scored the
--     September 2020 drop of 1.0 points as -1.0 (normal), while the robust score gives -6.7.
--     The window excludes the current month so a spike cannot dilute its own score, and a
--     score needs at least 24 months of history. Threshold |z| >= 3.5 (Iglewicz and Hoaglin).
CREATE OR REPLACE TABLE mart_labour_monthly AS
WITH pivoted AS (
    SELECT
        month, geo, gender, age_group,
        max(estimate) FILTER (WHERE characteristic = 'Unemployment rate')  AS unemployment_rate,
        max(se_mom)   FILTER (WHERE characteristic = 'Unemployment rate')  AS unemployment_rate_se_mom,
        max(se_yoy)   FILTER (WHERE characteristic = 'Unemployment rate')  AS unemployment_rate_se_yoy,
        max(estimate) FILTER (WHERE characteristic = 'Employment rate')    AS employment_rate,
        max(estimate) FILTER (WHERE characteristic = 'Participation rate') AS participation_rate,
        max(estimate) FILTER (WHERE characteristic = 'Employment')         AS employment_k,
        max(se_mom)   FILTER (WHERE characteristic = 'Employment')         AS employment_se_mom_k,
        max(estimate) FILTER (WHERE characteristic = 'Full-time employment') AS full_time_employment_k,
        max(estimate) FILTER (WHERE characteristic = 'Part-time employment') AS part_time_employment_k,
        max(estimate) FILTER (WHERE characteristic = 'Unemployment')       AS unemployment_k,
        max(estimate) FILTER (WHERE characteristic = 'Labour force')       AS labour_force_k,
        max(estimate) FILTER (WHERE characteristic = 'Population')         AS population_k
    FROM stg_lfs
    WHERE data_type = 'Seasonally adjusted'
    GROUP BY ALL
),
changes AS (
    SELECT
        cur.*,
        round(cur.unemployment_rate - m1.unemployment_rate, 1)  AS unemployment_rate_mom_pp,
        round(cur.unemployment_rate - m12.unemployment_rate, 1) AS unemployment_rate_yoy_pp,
        round(cur.employment_k - m1.employment_k, 1)            AS employment_mom_k,
        round(100 * (cur.employment_k / m12.employment_k - 1), 1) AS employment_yoy_pct
    FROM pivoted cur
    LEFT JOIN pivoted m1  ON m1.geo = cur.geo AND m1.gender = cur.gender AND m1.age_group = cur.age_group
                         AND m1.month = cur.month - INTERVAL 1 MONTH
    LEFT JOIN pivoted m12 ON m12.geo = cur.geo AND m12.gender = cur.gender AND m12.age_group = cur.age_group
                         AND m12.month = cur.month - INTERVAL 12 MONTH
),
windowed AS (
    SELECT
        *,
        CASE WHEN count(unemployment_rate) OVER w3 = 3
             THEN round(avg(unemployment_rate) OVER w3, 2) END   AS unemployment_rate_3mo_avg,
        median(unemployment_rate_mom_pp) OVER w36                AS hist_median,
        mad(unemployment_rate_mom_pp) OVER w36                   AS hist_mad,
        count(unemployment_rate_mom_pp) OVER w36                 AS hist_n
    FROM changes
    WINDOW
        w3  AS (PARTITION BY geo, gender, age_group ORDER BY month
                RANGE BETWEEN INTERVAL 2 MONTH PRECEDING AND CURRENT ROW),
        w36 AS (PARTITION BY geo, gender, age_group ORDER BY month
                RANGE BETWEEN INTERVAL 36 MONTH PRECEDING AND INTERVAL 1 MONTH PRECEDING)
)
SELECT
    w.month, w.geo, g.geo_level, g.province_code, w.gender, w.age_group,
    w.unemployment_rate, w.unemployment_rate_3mo_avg,
    w.unemployment_rate_mom_pp, w.unemployment_rate_se_mom,
    abs(w.unemployment_rate_mom_pp) > 1.96 * w.unemployment_rate_se_mom AS unemployment_rate_mom_significant,
    w.unemployment_rate_yoy_pp, w.unemployment_rate_se_yoy,
    abs(w.unemployment_rate_yoy_pp) > 1.96 * w.unemployment_rate_se_yoy AS unemployment_rate_yoy_significant,
    w.employment_rate, w.participation_rate,
    w.employment_k, w.employment_mom_k, w.employment_se_mom_k,
    abs(w.employment_mom_k) > 1.96 * w.employment_se_mom_k AS employment_mom_significant,
    w.employment_yoy_pct,
    w.full_time_employment_k, w.part_time_employment_k,
    w.unemployment_k, w.labour_force_k, w.population_k,
    -- 1 = lowest unemployment among the 10 provinces that month; NULL for Canada.
    CASE WHEN g.geo_level = 'province' THEN
        rank() OVER (PARTITION BY w.month, w.gender, w.age_group, g.geo_level
                     ORDER BY w.unemployment_rate) END AS province_rank_unemployment,
    CASE WHEN w.hist_n >= 24 AND w.hist_mad > 0 THEN
        round((w.unemployment_rate_mom_pp - w.hist_median) / (1.4826 * w.hist_mad), 2) END
        AS unemployment_rate_mom_robust_z,
    coalesce(abs((w.unemployment_rate_mom_pp - w.hist_median) / nullif(1.4826 * w.hist_mad, 0)) >= 3.5
             AND w.hist_n >= 24, false) AS is_anomaly
FROM windowed w
JOIN dim_geo g USING (geo);
