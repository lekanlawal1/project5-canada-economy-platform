-- Real GDP by industry, chained 2017 dollars, seasonally adjusted at annual rates,
-- millions of dollars.
-- Cleaning:
--   * The NAICS code is split from the industry name so marts can filter by code.
--   * Each industry is typed: 'total' (T001, all industries), 'aggregate' (StatCan's other
--     T-codes such as goods-producing or energy sector) or 'sector' (2-digit NAICS).
--     Sectors sum to roughly the total; aggregates overlap sectors and each other, so
--     summing across types would double count. The type column makes that hard to do.
--   * '..' rows have no value and are dropped; see the decision log for which series.
CREATE OR REPLACE TABLE stg_gdp AS
SELECT
    CAST(strptime(ref_date || '-01', '%Y-%m-%d') AS DATE)     AS month,
    trim(regexp_replace(industry, '\s*\[[^\]]+\]$', ''))      AS industry,
    naics_code,
    CASE WHEN naics_code = 'T001' THEN 'total'
         WHEN naics_code LIKE 'T%' THEN 'aggregate'
         ELSE 'sector' END                                    AS industry_type,
    value                                                     AS gdp_millions
FROM raw_gdp
WHERE value IS NOT NULL;
