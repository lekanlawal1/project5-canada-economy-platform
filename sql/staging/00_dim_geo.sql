-- Geography dimension shared by every mart. StatCan tables name places inconsistently
-- (provinces, regions, metro areas, one metro split across two provinces), so each name is
-- tagged once here with a level and a two-letter province code. Marts then filter on
-- geo_level = 'province' instead of repeating hand-typed lists that can drift apart.
CREATE OR REPLACE TABLE dim_geo AS
WITH provinces(geo, province_code, sort_order) AS (
    VALUES ('Newfoundland and Labrador', 'NL', 1), ('Prince Edward Island', 'PE', 2),
           ('Nova Scotia', 'NS', 3), ('New Brunswick', 'NB', 4), ('Quebec', 'QC', 5),
           ('Ontario', 'ON', 6), ('Manitoba', 'MB', 7), ('Saskatchewan', 'SK', 8),
           ('Alberta', 'AB', 9), ('British Columbia', 'BC', 10), ('Yukon', 'YT', 11),
           ('Northwest Territories', 'NT', 12), ('Nunavut', 'NU', 13)
),
all_geos AS (
    SELECT geo FROM raw_lfs UNION SELECT geo FROM raw_cpi UNION SELECT geo FROM raw_nhpi
    UNION SELECT geo FROM raw_job_vacancies
)
SELECT
    g.geo,
    CASE
        WHEN g.geo = 'Canada' THEN 'country'
        WHEN p.geo IS NOT NULL AND p.sort_order <= 10 THEN 'province'
        WHEN p.geo IS NOT NULL THEN 'territory'
        WHEN g.geo LIKE '% Region' THEN 'region'
        ELSE 'metro'
    END AS geo_level,
    COALESCE(
        p.province_code,
        -- Metro names end in ", <Province>". Ottawa-Gatineau is published as two parts.
        CASE
            WHEN g.geo LIKE '%Ontario part%' THEN 'ON'
            WHEN g.geo LIKE '%Quebec part%' THEN 'QC'
        END,
        (SELECT p2.province_code FROM provinces p2
          WHERE g.geo LIKE '%, ' || p2.geo)
    ) AS province_code,
    COALESCE(p.sort_order, 0) AS sort_order
FROM all_geos g
LEFT JOIN provinces p USING (geo);
