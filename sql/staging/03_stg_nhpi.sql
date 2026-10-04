-- New Housing Price Index (December 2016 = 100).
-- Cleaning:
--   * '..' (not available) and 'x' (suppressed) rows have no value and are dropped.
--   * 'E' (use with caution) rows are KEPT with a caution flag. They are 28% of rows, mostly
--     smaller metros; dropping them would erase whole cities, and hiding the flag would
--     overstate confidence. The dashboard shows the flag instead.
CREATE OR REPLACE TABLE stg_nhpi AS
SELECT
    CAST(strptime(ref_date || '-01', '%Y-%m-%d') AS DATE) AS month,
    geo,
    component,
    value                                                 AS index_value,
    status = 'E'                                          AS use_with_caution
FROM raw_nhpi
WHERE value IS NOT NULL;
