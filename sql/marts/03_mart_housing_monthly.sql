-- New housing prices by geography and component (house, land, total), monthly.
-- The caution flag from StatCan ('E') is carried through so charts can mark weak points.
CREATE OR REPLACE TABLE mart_housing_monthly AS
WITH changes AS (
    SELECT
        cur.month, cur.geo, cur.component, cur.index_value, cur.use_with_caution,
        round(100 * (cur.index_value / m1.index_value - 1), 1)  AS mom_pct,
        round(100 * (cur.index_value / m12.index_value - 1), 1) AS yoy_pct
    FROM stg_nhpi cur
    LEFT JOIN stg_nhpi m1  ON m1.geo = cur.geo AND m1.component = cur.component
                          AND m1.month = cur.month - INTERVAL 1 MONTH
    LEFT JOIN stg_nhpi m12 ON m12.geo = cur.geo AND m12.component = cur.component
                          AND m12.month = cur.month - INTERVAL 12 MONTH
)
SELECT
    c.month, c.geo, g.geo_level, g.province_code, c.component, c.index_value,
    c.mom_pct, c.yoy_pct, c.use_with_caution,
    -- 1 = fastest price growth among provinces for that component and month.
    CASE WHEN g.geo_level = 'province' AND c.yoy_pct IS NOT NULL THEN
        rank() OVER (PARTITION BY c.month, c.component, g.geo_level, c.yoy_pct IS NULL
                     ORDER BY c.yoy_pct DESC) END AS province_rank_price_growth
FROM changes c
JOIN dim_geo g USING (geo);
