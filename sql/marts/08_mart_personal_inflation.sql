-- The personal inflation calculator: ten spending categories a person can fill in, each with
-- its latest 12-month price change and its official share of household spending.
--
-- Method:
--   * A personal rate is the spending-weighted average of category price changes. With the
--     official weights this reproduces the published all-items rate to within about 0.1 points
--     (a data test holds it under 0.35): weights are refreshed yearly, so it is not exact.
--   * Two categories split a published group, because they are where people differ most:
--     rent versus other home costs (renters versus owners), and gasoline versus the rest of
--     transportation (drivers versus transit users). The "other" part is derived from the
--     published group and its sub-series by their official weights:
--       other = (w_group * change_group - w_part * change_part) / (w_group - w_part)
--     This is the same contribution arithmetic the CPI aggregates use, applied in reverse.
CREATE OR REPLACE TABLE mart_personal_inflation AS
WITH latest AS (
    SELECT geo, product, yoy_pct, month FROM mart_cpi_monthly
    WHERE month = (SELECT max(month) FROM mart_cpi_monthly)
),
w AS (SELECT geo, product, weight_pct, basket_year FROM stg_cpi_weights),
p AS (
    SELECT l.geo, l.product, l.yoy_pct, l.month, w.weight_pct, w.basket_year
    FROM latest l JOIN w USING (geo, product)
),
pv AS (
    SELECT geo, any_value(month) AS month, any_value(basket_year) AS basket_year,
        max(weight_pct) FILTER (WHERE product = 'Shelter')        AS w_shelter,
        max(yoy_pct)    FILTER (WHERE product = 'Shelter')        AS y_shelter,
        max(weight_pct) FILTER (WHERE product = 'Rent')           AS w_rent,
        max(yoy_pct)    FILTER (WHERE product = 'Rent')           AS y_rent,
        max(weight_pct) FILTER (WHERE product = 'Transportation') AS w_transport,
        max(yoy_pct)    FILTER (WHERE product = 'Transportation') AS y_transport,
        max(weight_pct) FILTER (WHERE product = 'Gasoline')       AS w_gas,
        max(yoy_pct)    FILTER (WHERE product = 'Gasoline')       AS y_gas
    FROM p GROUP BY geo
),
categories(category, sort_order, label, hint, product) AS (VALUES
    ('rent',        1, 'Rent', 'Your monthly rent, if you rent', 'Rent'),
    ('home',        2, 'Other home costs', 'Utilities, mortgage interest, property tax, home insurance, upkeep', NULL),
    ('food',        3, 'Food', 'Groceries and eating out', 'Food'),
    ('gas',         4, 'Gas', 'Fuel for your car', 'Gasoline'),
    ('transport',   5, 'Other transportation', 'Car payments, insurance, repairs, transit, flights', NULL),
    ('household',   6, 'Household', 'Phone and internet, furniture, cleaning, childcare', 'Household operations, furnishings and equipment'),
    ('clothing',    7, 'Clothing and shoes', 'Clothing, footwear, accessories', 'Clothing and footwear'),
    ('health',      8, 'Health and personal care', 'Medicine, dental, haircuts, toiletries', 'Health and personal care'),
    ('recreation',  9, 'Recreation and education', 'Streaming, sports, travel tours, tuition, books', 'Recreation, education and reading'),
    ('alcohol',    10, 'Alcohol, tobacco and cannabis', '', 'Alcoholic beverages, tobacco products and recreational cannabis')
)
SELECT pv.geo, pv.month, pv.basket_year, c.category, c.sort_order, c.label, c.hint,
    CASE c.category
        WHEN 'home'      THEN round(pv.w_shelter - pv.w_rent, 2)
        WHEN 'transport' THEN round(pv.w_transport - pv.w_gas, 2)
        ELSE p.weight_pct END AS weight_pct,
    CASE c.category
        WHEN 'home'      THEN round((pv.w_shelter * pv.y_shelter - pv.w_rent * pv.y_rent) / (pv.w_shelter - pv.w_rent), 2)
        WHEN 'transport' THEN round((pv.w_transport * pv.y_transport - pv.w_gas * pv.y_gas) / (pv.w_transport - pv.w_gas), 2)
        ELSE p.yoy_pct END AS yoy_pct,
    c.product IS NULL AS derived
FROM pv
CROSS JOIN categories c
LEFT JOIN p ON p.geo = pv.geo AND p.product = c.product;
