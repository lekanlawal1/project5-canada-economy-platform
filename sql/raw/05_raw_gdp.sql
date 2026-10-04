-- GDP by industry (36-10-0434), national only. The file carries three measures; we keep
-- "Seasonally adjusted at annual rates" in "Chained (2017) dollars", StatCan's headline real
-- GDP measure. Industries: the all-industry total, the 2 digit NAICS sectors, and StatCan's
-- special aggregates (codes starting with T, e.g. goods vs services, energy sector).
-- Sub-sector detail (3 and 4 digit codes) is dropped: too granular for a monthly overview.
CREATE OR REPLACE TABLE raw_gdp AS
SELECT
    REF_DATE                                                    AS ref_date,
    "North American Industry Classification System (NAICS)"   AS industry,
    regexp_extract("North American Industry Classification System (NAICS)",
                   '\[([^\]]+)\]$', 1)                          AS naics_code,
    UOM                                                         AS uom,
    SCALAR_FACTOR                                               AS scalar_factor,
    VECTOR                                                      AS vector,
    VALUE                                                       AS value,
    STATUS                                                      AS status
FROM read_csv('{csv}', header = true, types = {'VALUE': 'DOUBLE', 'REF_DATE': 'VARCHAR'})
WHERE "Seasonal adjustment" = 'Seasonally adjusted at annual rates'
  AND "Prices" = 'Chained (2017) dollars'
  AND regexp_matches("North American Industry Classification System (NAICS)",
                     '\[(T\d+|\d\d|\d\d-\d\d)\]$');
