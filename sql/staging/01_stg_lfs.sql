-- Labour Force Survey, one row per series per month, with StatCan's three standard errors
-- pivoted alongside the estimate so later math never has to re-join them.
-- Cleaning:
--   * ref_date 'YYYY-MM' becomes a DATE (first of month) so date arithmetic works.
--   * Rows whose estimate is missing are dropped: '..' (not available for that period) and
--     'x' (suppressed by StatCan for confidentiality). Counts are in the decision log.
--   * Counts stay in thousands of persons, as published, and the column names say so.
--     Converting to persons would imply a precision the survey does not have.
CREATE OR REPLACE TABLE stg_lfs AS
SELECT
    CAST(strptime(ref_date || '-01', '%Y-%m-%d') AS DATE)                AS month,
    geo,
    characteristic,
    gender,
    age_group,
    data_type,
    CASE WHEN any_value(uom) = 'Percent' THEN 'percent' ELSE 'thousands' END AS unit,
    max(value) FILTER (WHERE statistic = 'Estimate')                         AS estimate,
    max(value) FILTER (WHERE statistic = 'Standard error of estimate')       AS se_level,
    max(value) FILTER (WHERE statistic = 'Standard error of month-to-month change') AS se_mom,
    max(value) FILTER (WHERE statistic = 'Standard error of year-over-year change') AS se_yoy
FROM raw_lfs
GROUP BY ALL
HAVING max(value) FILTER (WHERE statistic = 'Estimate') IS NOT NULL;
