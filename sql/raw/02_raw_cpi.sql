-- Consumer Price Index (18-10-0004). 359 product groups and 30 geographies; we keep the
-- headline aggregate, the major components, and the series people actually ask about.
-- Geography: Canada and the 10 provinces. City series are dropped: many are short or
--   discontinued, and the province is the unit used across every other table here.
-- Base year: the file mixes 11 different index bases (UOM). The products below all use
--   2002=100; staging tests assert this so a silent StatCan rebase cannot corrupt YoY math.
CREATE OR REPLACE TABLE raw_cpi AS
SELECT
    REF_DATE                        AS ref_date,
    GEO                             AS geo,
    "Products and product groups"   AS product,
    UOM                             AS uom,
    VECTOR                          AS vector,
    VALUE                           AS value,
    STATUS                          AS status,
    TERMINATED                      AS terminated
FROM read_csv('{csv}', header = true, types = {'VALUE': 'DOUBLE', 'REF_DATE': 'VARCHAR'})
WHERE GEO IN ('Canada', 'Newfoundland and Labrador', 'Prince Edward Island', 'Nova Scotia',
              'New Brunswick', 'Quebec', 'Ontario', 'Manitoba', 'Saskatchewan', 'Alberta',
              'British Columbia')
  AND "Products and product groups" IN (
        'All-items',
        'All-items excluding food and energy',
        'Food', 'Food purchased from stores',
        'Shelter', 'Rent', 'Mortgage interest cost',
        'Household operations, furnishings and equipment',
        'Clothing and footwear',
        'Transportation', 'Gasoline',
        'Health and personal care',
        'Recreation, education and reading',
        'Alcoholic beverages, tobacco products and recreational cannabis',
        'Energy');
