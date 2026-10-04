-- Job vacancies joined to unemployment: how many unemployed people per open job.
--
-- Method notes:
--   * Job vacancies are NOT seasonally adjusted, so they are joined to the LFS 'Unadjusted'
--     series. Mixing an adjusted numerator with an unadjusted denominator would build a
--     seasonal pattern into the ratio.
--   * LFS counts are in thousands; multiplied by 1000 to match vacancies (in persons).
--   * The ratio is only computed when both vacancy figures are graded A to D. Grades E (use
--     with caution) and F (unreliable) give NULL, and is_low_quality says why.
--   * LFS in this table has no territories, so the ratio is NULL there by construction.
CREATE OR REPLACE TABLE mart_job_market_monthly AS
WITH lfs AS (
    SELECT month, geo, estimate * 1000 AS unemployed
    FROM stg_lfs
    WHERE data_type = 'Unadjusted' AND characteristic = 'Unemployment'
      AND gender = 'Total - Gender' AND age_group = '15 years and over'
)
SELECT
    j.month, j.geo, g.geo_level, g.province_code,
    j.job_vacancies, j.job_vacancies_grade,
    j.payroll_employees,
    j.job_vacancy_rate, j.job_vacancy_rate_grade,
    round(j.job_vacancy_rate - p.job_vacancy_rate, 1) AS job_vacancy_rate_yoy_pp,
    l.unemployed,
    j.job_vacancies_grade IN ('E', 'F') OR j.job_vacancy_rate_grade IN ('E', 'F') AS is_low_quality,
    CASE WHEN j.job_vacancies_grade IN ('A', 'B', 'C', 'D') AND j.job_vacancies > 0
         THEN round(l.unemployed / j.job_vacancies, 2) END AS unemployed_per_vacancy
FROM stg_job_vacancies j
JOIN dim_geo g USING (geo)
LEFT JOIN stg_job_vacancies p ON p.geo = j.geo AND p.month = j.month - INTERVAL 12 MONTH
LEFT JOIN lfs l ON l.geo = j.geo AND l.month = j.month;
