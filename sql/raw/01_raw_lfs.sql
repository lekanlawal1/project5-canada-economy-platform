-- Labour Force Survey (14-10-0287). Source is 1.18 GB / 5.5M rows; DuckDB streams it and
-- the WHERE clause is applied during the scan, so the full file is never held in memory.
-- Kept:
--   Statistics: Estimate, plus StatCan's published standard errors of the estimate, of the
--     month-to-month change and of the year-over-year change (available from 2001). The
--     change errors are what decide whether a move is real or sampling noise. They cannot
--     be derived from the level error: LFS keeps 5/6 of its sample month to month, so
--     consecutive months are correlated and sqrt(2) x SE would overstate the noise.
--   Data type: Seasonally adjusted (what headlines report) and Unadjusted (raw signal for
--     forecasting). Trend-cycle dropped: StatCan revises its latest points heavily.
--   Age groups: 15+, youth 15-24, core working age 25-54, 55+. Overlapping groups dropped.
--   All 9 characteristics, all genders, all 11 geographies (Canada plus 10 provinces;
--     LFS in this table does not cover the territories).
CREATE OR REPLACE TABLE raw_lfs AS
SELECT
    REF_DATE                             AS ref_date,
    GEO                                  AS geo,
    "Labour force characteristics"       AS characteristic,
    "Gender"                             AS gender,
    "Age group"                          AS age_group,
    "Statistics"                         AS statistic,
    "Data type"                          AS data_type,
    UOM                                  AS uom,
    SCALAR_FACTOR                        AS scalar_factor,
    VECTOR                               AS vector,
    VALUE                                AS value,
    STATUS                               AS status
FROM read_csv('{csv}', header = true, types = {'VALUE': 'DOUBLE', 'REF_DATE': 'VARCHAR'})
WHERE "Statistics" IN ('Estimate', 'Standard error of estimate',
                       'Standard error of month-to-month change',
                       'Standard error of year-over-year change')
  AND "Data type" IN ('Seasonally adjusted', 'Unadjusted')
  AND "Age group" IN ('15 years and over', '15 to 24 years', '25 to 54 years', '55 years and over');
