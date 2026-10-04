-- Consumer prices by geography and product, monthly.
--
-- Method notes:
--   * Year-over-year % change is computed from the published index values and rounded to
--     1 decimal, the same method StatCan uses for its official inflation figures, so our
--     headline number should match theirs exactly.
--   * CPI is not seasonally adjusted, so the month-over-month change mixes real price moves
--     with normal seasonal swings (gasoline in summer, clothing in sales season). The
--     anomaly score is therefore computed on the monthly change in the YEAR-OVER-YEAR rate,
--     which cancels the seasonal pattern. Same robust z-score rules as the labour mart.
--   * Prior periods joined on calendar month, as in the labour mart.
CREATE OR REPLACE TABLE mart_cpi_monthly AS
WITH changes AS (
    SELECT
        cur.month, cur.geo, cur.product, cur.index_base, cur.index_value,
        round(100 * (cur.index_value / m1.index_value - 1), 1)  AS mom_pct,
        round(100 * (cur.index_value / m12.index_value - 1), 1) AS yoy_pct
    FROM stg_cpi cur
    LEFT JOIN stg_cpi m1  ON m1.geo = cur.geo AND m1.product = cur.product
                         AND m1.month = cur.month - INTERVAL 1 MONTH
    LEFT JOIN stg_cpi m12 ON m12.geo = cur.geo AND m12.product = cur.product
                         AND m12.month = cur.month - INTERVAL 12 MONTH
),
accel AS (
    SELECT c.*, round(c.yoy_pct - p.yoy_pct, 1) AS yoy_change_pp
    FROM changes c
    LEFT JOIN changes p ON p.geo = c.geo AND p.product = c.product
                       AND p.month = c.month - INTERVAL 1 MONTH
),
windowed AS (
    SELECT
        *,
        CASE WHEN count(yoy_pct) OVER w3 = 3 THEN round(avg(yoy_pct) OVER w3, 2) END AS yoy_pct_3mo_avg,
        median(yoy_change_pp) OVER w36 AS hist_median,
        mad(yoy_change_pp) OVER w36    AS hist_mad,
        count(yoy_change_pp) OVER w36  AS hist_n
    FROM accel
    WINDOW
        w3  AS (PARTITION BY geo, product ORDER BY month
                RANGE BETWEEN INTERVAL 2 MONTH PRECEDING AND CURRENT ROW),
        w36 AS (PARTITION BY geo, product ORDER BY month
                RANGE BETWEEN INTERVAL 36 MONTH PRECEDING AND INTERVAL 1 MONTH PRECEDING)
)
SELECT
    w.month, w.geo, g.geo_level, g.province_code, w.product, w.index_base, w.index_value,
    w.mom_pct, w.yoy_pct, w.yoy_pct_3mo_avg, w.yoy_change_pp,
    -- 1 = highest inflation among the 10 provinces for that product and month.
    CASE WHEN g.geo_level = 'province' AND w.yoy_pct IS NOT NULL THEN
        rank() OVER (PARTITION BY w.month, w.product, g.geo_level, w.yoy_pct IS NULL
                     ORDER BY w.yoy_pct DESC) END AS province_rank_inflation,
    CASE WHEN w.hist_n >= 24 AND w.hist_mad > 0 THEN
        round((w.yoy_change_pp - w.hist_median) / (1.4826 * w.hist_mad), 2) END AS yoy_change_robust_z,
    coalesce(abs((w.yoy_change_pp - w.hist_median) / nullif(1.4826 * w.hist_mad, 0)) >= 3.5
             AND w.hist_n >= 24, false) AS is_anomaly
FROM windowed w
JOIN dim_geo g USING (geo);
