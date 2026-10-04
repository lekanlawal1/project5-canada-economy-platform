-- Job vacancies (14-10-0371). Tiny, kept whole. STATUS here is a data quality grade from
-- A (excellent) to F (unreliable); it is kept so the dashboard can grey out weak estimates
-- instead of presenting them with false confidence. Unlike LFS, this covers the territories.
CREATE OR REPLACE TABLE raw_job_vacancies AS
SELECT
    REF_DATE        AS ref_date,
    GEO             AS geo,
    "Statistics"    AS statistic,
    UOM             AS uom,
    VECTOR          AS vector,
    VALUE           AS value,
    STATUS          AS quality_grade
FROM read_csv('{csv}', header = true, types = {'VALUE': 'DOUBLE', 'REF_DATE': 'VARCHAR'});
