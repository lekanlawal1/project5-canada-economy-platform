-- Real GDP by industry, monthly (seasonally adjusted, so month-over-month is meaningful).
-- share_of_total_pct is only filled for 2-digit sectors, which partition the economy;
-- StatCan's aggregates overlap each other and would not sum to 100.
-- Anomaly scoring follows the same robust z-score rules as the labour mart.
CREATE OR REPLACE TABLE mart_gdp_monthly AS
WITH changes AS (
    SELECT
        cur.month, cur.industry, cur.naics_code, cur.industry_type, cur.gdp_millions,
        round(100 * (cur.gdp_millions / m1.gdp_millions - 1), 2)  AS mom_pct,
        round(100 * (cur.gdp_millions / m12.gdp_millions - 1), 1) AS yoy_pct,
        CASE WHEN cur.industry_type = 'sector'
             THEN round(100 * cur.gdp_millions / t.gdp_millions, 2) END AS share_of_total_pct
    FROM stg_gdp cur
    LEFT JOIN stg_gdp m1  ON m1.naics_code = cur.naics_code AND m1.month = cur.month - INTERVAL 1 MONTH
    LEFT JOIN stg_gdp m12 ON m12.naics_code = cur.naics_code AND m12.month = cur.month - INTERVAL 12 MONTH
    LEFT JOIN stg_gdp t   ON t.naics_code = 'T001' AND t.month = cur.month
),
windowed AS (
    SELECT
        *,
        median(mom_pct) OVER w36 AS hist_median,
        mad(mom_pct) OVER w36    AS hist_mad,
        count(mom_pct) OVER w36  AS hist_n
    FROM changes
    WINDOW w36 AS (PARTITION BY naics_code ORDER BY month
                   RANGE BETWEEN INTERVAL 36 MONTH PRECEDING AND INTERVAL 1 MONTH PRECEDING)
)
SELECT
    month, industry, naics_code, industry_type, gdp_millions, mom_pct, yoy_pct, share_of_total_pct,
    CASE WHEN hist_n >= 24 AND hist_mad > 0 THEN
        round((mom_pct - hist_median) / (1.4826 * hist_mad), 2) END AS mom_robust_z,
    coalesce(abs((mom_pct - hist_median) / nullif(1.4826 * hist_mad, 0)) >= 3.5
             AND hist_n >= 24, false) AS is_anomaly
FROM windowed;
