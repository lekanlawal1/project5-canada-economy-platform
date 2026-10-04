-- Job vacancies, pivoted to one row per geography per month.
-- Cleaning:
--   * StatCan grades every estimate A (excellent) to F (too unreliable to publish). F rows
--     arrive with no value. The grade of each measure is kept next to it.
--   * These figures are NOT seasonally adjusted. Any join to LFS must use LFS 'Unadjusted'
--     to compare like with like.
CREATE OR REPLACE TABLE stg_job_vacancies AS
SELECT
    CAST(strptime(ref_date || '-01', '%Y-%m-%d') AS DATE)                     AS month,
    geo,
    max(value) FILTER (WHERE statistic = 'Job vacancies')                       AS job_vacancies,
    max(quality_grade) FILTER (WHERE statistic = 'Job vacancies')               AS job_vacancies_grade,
    max(value) FILTER (WHERE statistic = 'Payroll employees')                   AS payroll_employees,
    max(value) FILTER (WHERE statistic = 'Job vacancy rate')                    AS job_vacancy_rate,
    max(quality_grade) FILTER (WHERE statistic = 'Job vacancy rate')            AS job_vacancy_rate_grade
FROM raw_job_vacancies
GROUP BY ALL;
