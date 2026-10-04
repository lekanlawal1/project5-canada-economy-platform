-- New Housing Price Index (18-10-0205). Small (66K rows), so every geography is kept:
-- Canada, regions, provinces and metro areas. Staging tags each with a geography level so
-- marts can compare like with like. STATUS is kept because x (suppressed) and E (use with
-- caution) are common in small metros.
CREATE OR REPLACE TABLE raw_nhpi AS
SELECT
    REF_DATE                        AS ref_date,
    GEO                             AS geo,
    "New housing price indexes"     AS component,
    UOM                             AS uom,
    VECTOR                          AS vector,
    VALUE                           AS value,
    STATUS                          AS status
FROM read_csv('{csv}', header = true, types = {'VALUE': 'DOUBLE', 'REF_DATE': 'VARCHAR'});
