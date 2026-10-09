-- CPI basket weights (18-10-0007): each product group's share of household spending, as
-- StatCan uses it to combine the price indexes. Used by the personal inflation calculator.
-- Kept: weights at basket link month prices (the ones in force for the current index) and
-- distributed to each geography (a province's own spending pattern, not its share of Canada).
CREATE OR REPLACE TABLE raw_cpi_weights AS
SELECT
    REF_DATE                        AS ref_date,        -- the basket year
    GEO                             AS geo,
    "Products and product groups"   AS product,
    VALUE                           AS weight_pct
FROM read_csv('{csv}', header = true, types = {'VALUE': 'DOUBLE', 'REF_DATE': 'INTEGER'})
WHERE "Price period of weight" = 'Weight at basket link month prices'
  AND "Geographic distribution of weight" = 'Distribution to selected geographies'
  AND GEO IN ('Canada', 'Newfoundland and Labrador', 'Prince Edward Island', 'Nova Scotia',
              'New Brunswick', 'Quebec', 'Ontario', 'Manitoba', 'Saskatchewan', 'Alberta',
              'British Columbia')
  AND "Products and product groups" IN (
        'All-items', 'Food', 'Shelter', 'Rent',
        'Household operations, furnishings and equipment', 'Clothing and footwear',
        'Transportation', 'Gasoline', 'Health and personal care',
        'Recreation, education and reading',
        'Alcoholic beverages, tobacco products and recreational cannabis');
