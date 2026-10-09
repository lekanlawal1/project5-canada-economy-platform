-- CPI basket weights, latest basket only. StatCan updates the basket once a year; the weights
-- in force are the newest basket year, which applies from its link month onward.
CREATE OR REPLACE TABLE stg_cpi_weights AS
SELECT ref_date AS basket_year, geo, product, weight_pct
FROM raw_cpi_weights
WHERE weight_pct IS NOT NULL
  AND ref_date = (SELECT max(ref_date) FROM raw_cpi_weights);
