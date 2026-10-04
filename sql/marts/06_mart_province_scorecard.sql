-- One row per province (plus Canada): the latest value of each headline indicator.
-- Every indicator carries its OWN reference month, because the tables are released on
-- different schedules (LFS, CPI and housing run a month ahead of vacancies and GDP).
-- Showing one shared "as of" date would be wrong for some of the numbers on the page.
CREATE OR REPLACE TABLE mart_province_scorecard AS
WITH lab AS (
    SELECT * FROM mart_labour_monthly
    WHERE gender = 'Total - Gender' AND age_group = '15 years and over'
      AND month = (SELECT max(month) FROM mart_labour_monthly)
),
cpi AS (
    SELECT * FROM mart_cpi_monthly
    WHERE product = 'All-items' AND month = (SELECT max(month) FROM mart_cpi_monthly)
),
hou AS (
    SELECT * FROM mart_housing_monthly
    WHERE component = 'Total (house and land)'
      AND month = (SELECT max(month) FROM mart_housing_monthly)
),
job AS (
    SELECT * FROM mart_job_market_monthly
    WHERE month = (SELECT max(month) FROM mart_job_market_monthly)
)
SELECT
    g.geo, g.geo_level, g.province_code, g.sort_order,
    lab.month                              AS labour_month,
    lab.unemployment_rate,
    lab.unemployment_rate_mom_pp,
    lab.unemployment_rate_mom_significant,
    lab.unemployment_rate_yoy_pp,
    lab.unemployment_rate_yoy_significant,
    lab.employment_rate,
    lab.province_rank_unemployment,
    cpi.month                              AS cpi_month,
    cpi.yoy_pct                            AS cpi_yoy_pct,
    cpi.province_rank_inflation,
    hou.month                              AS housing_month,
    hou.yoy_pct                            AS new_housing_price_yoy_pct,
    hou.use_with_caution                   AS housing_use_with_caution,
    job.month                              AS job_month,
    job.job_vacancy_rate,
    job.job_vacancy_rate_grade,
    job.unemployed_per_vacancy
FROM dim_geo g
LEFT JOIN lab USING (geo)
LEFT JOIN cpi USING (geo)
LEFT JOIN hou USING (geo)
LEFT JOIN job USING (geo)
WHERE g.geo_level IN ('country', 'province')
ORDER BY g.sort_order;
