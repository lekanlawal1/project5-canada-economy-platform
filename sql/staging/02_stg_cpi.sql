-- Consumer Price Index. The raw file mixes 11 index bases; every series kept here must be
-- 2002=100 so year-over-year ratios are valid. The base is carried as a column and the
-- data tests fail if any other base appears, rather than silently mixing them.
CREATE OR REPLACE TABLE stg_cpi AS
SELECT
    CAST(strptime(ref_date || '-01', '%Y-%m-%d') AS DATE) AS month,
    geo,
    product,
    uom                                                   AS index_base,
    value                                                 AS index_value
FROM raw_cpi
WHERE value IS NOT NULL;
