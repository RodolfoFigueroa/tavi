CREATE OR REPLACE VIEW demographics AS
SELECT
    ageb.cvegeo,
    mun.cve_met AS metropolitan_zone_code,
    ageb.pobtot AS total_pop,
    ageb.pobfem AS female_pop,
    ageb.pobmas AS male_pop,
    ageb.p_60ymas AS elderly_pop,
    ageb.p_0a2 + ageb.p_3a5 + ageb.p_6a11 + ageb.p_12a14 + ageb.p_15a17 AS underage_pop,
    income.income AS quarterly_income,
    income.income_pc AS quarterly_income_per_capita,
    ageb.geometry
FROM pg_db.census_2020_ageb ageb
LEFT JOIN pg_db.income_2020 income
    ON ageb.cvegeo = income.cvegeo
LEFT JOIN pg_db.census_2020_mun mun
    ON ageb.cve_mun = mun.cvegeo;
