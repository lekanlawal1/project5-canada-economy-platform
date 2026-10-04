-- Every flagged anomaly across domains in one long table: the input the AI briefing and the
-- Overview page read from. Scope is kept to headline series to avoid flooding it with noise
-- from small subgroups (for example, women 55+ in one province):
--   labour: ages 15+, total gender, Canada and provinces (subgroups are too noisy).
--   prices: Canada and provinces, all 15 product groups.
--   GDP: all industries kept.
CREATE OR REPLACE TABLE mart_anomalies AS
SELECT month, 'labour' AS domain, geo, 'Unemployment rate' AS series,
       unemployment_rate_mom_pp AS change_value, 'pp month over month' AS change_unit,
       unemployment_rate_mom_robust_z AS robust_z
FROM mart_labour_monthly
WHERE is_anomaly AND gender = 'Total - Gender' AND age_group = '15 years and over'
UNION ALL
SELECT month, 'prices', geo, 'CPI: ' || product,
       yoy_change_pp, 'pp change in yearly inflation', yoy_change_robust_z
FROM mart_cpi_monthly
WHERE is_anomaly
UNION ALL
SELECT month, 'gdp', 'Canada', 'GDP: ' || industry,
       mom_pct, '% month over month', mom_robust_z
FROM mart_gdp_monthly
WHERE is_anomaly;
