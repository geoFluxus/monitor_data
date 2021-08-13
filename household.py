import pandas as pd
import logging
import numpy as np
import gc
import json
import variables as var

# find cbs data (2016-2019) for gemeenten & provincies
INWONERS = {
    'Groningen': 586813,
    'Friesland': 651459,
    'Drenthe': 494760,
    'Overijssel': 1166478,
    'Flevoland': 428264,
    'Gelderland': 2096620,
    'Utrecht': 1361093,
    'Noord-Holland': 2887906,
    'Zuid-Holland': 3726173,
    'Zeeland': 385379,
    'Noord-Brabant': 2573853,
    'Limburg': 1115895
}

DATA = {}

YEARS = var.YEARS


def import_household_data(areas=None, population=None):
    """
    Import & ready CBS household data for processing
    """

    # add gemeente & provincie
    df = pd.read_excel('./data/household/Huishoudelijk_Gemeenten_Utrecht.xlsx', sheet_name='Data')
    columns = list(df.columns)
    df = df.replace('?', np.nan)
    df = pd.merge(df, areas, left_on='Gebieden', right_on='Gemeente (post 2019)', how='left')
    columns.append('Provincie')
    df = df[columns]
    missing = {
        'Den Haag': 'Zuid-Holland',
        'Nuenen c.a.': 'Noord-Brabant',
    }
    for key, value in missing.items():
        df.loc[df['Gebieden'] == key, 'Provincie'] = value

    # add population
    def add_population(row):
        gemeente, year = row['Gebieden'], row['Perioden']
        res = population[population['Gemeente'] == gemeente][str(year)]
        if not res.empty:
            res = res.values[0]
            return res
        return np.nan
    df['Inwoners'] = df.apply(lambda x: add_population(x), axis=1)

    return df


def add_areas(df, areas=None, role=None):
    """
    Add gemeente & provincie to role based on postcode
    """
    columns = list(df)

    # join on postcode
    df = pd.merge(df, areas, left_on=f'{role}_PC4', right_on='PC4', how='left')
    df[f'{role}_Gemeente'] = df['Gemeente']
    df[f'{role}_Provincie'] = df['Provincie']
    columns.extend([f'{role}_Gemeente', f'{role}_Provincie'])
    df = df[columns]

    return df


def import_lma_flows(areas=None, year=None):
    """
    Import & ready LMA flows for processing
    """
    columns = [
        'EuralCode',
        'VerwerkingsmethodeCode',
        'Gewicht_KG',
        'Herkomst_Postcode',
        'Herkomst_Land',
        'Verwerker_Postcode',
        'Verwerker_Land'
    ]

    # import file
    path = '../../../../../media/geofluxus/DATA/national/ontvangst/processed'
    print(f'Import {year} data...')
    df = pd.read_csv(f'{path}/ontvangst_{year}_full.csv', usecols=columns, low_memory=False)

    # ewc code as 6-digit
    df['EuralCode'] = df['EuralCode'].astype(str).str.zfill(6)

    # add provincie/gemeente on herkomst & verwerker
    for role in ['Herkomst', 'Verwerker']:
        df.loc[df[f'{role}_Land'] == 'NEDERLAND', f'{role}_PC4'] = df[f'{role}_Postcode'].str[:4]
        df = add_areas(df, areas=areas, role=role)

    return df


def compute_lma_waste(df, role=None, apply=None, year=None):
    """
    Compute LMA waste
    """
    title = f'province\t{apply.__name__}\tmtn'
    print(title)

    columns = [
        f'{role}_Provincie',
        'Gewicht_KG'
    ]

    # apply filter function
    if apply: df = apply(df)

    # compute total
    df = df[columns].groupby(columns[:-1]).sum().reset_index()

    # add to data
    df[year] = df['Gewicht_KG'] / 10**9
    df['area'] = df[f'{role}_Provincie']
    DATA.setdefault(title, []).append(df[['area', year]])


def cbs_primary_waste(input, year=None, title=None):
    print(title)

    df = input.copy()
    columns = [
        "Provincie",
        "Gewicht_KG",
        "Inwoners"
    ]
    df['Gewicht_KG'] = df["Totaal aangeboden huishoudelijk afval [Kilo's per inwoner]"] * df['Inwoners']
    df = df[columns].groupby("Provincie").sum().reset_index()

    # add to data
    df[year] = df['Gewicht_KG'] / 10**9
    df['area'] = df[f'Provincie']
    DATA.setdefault(title, []).append(df[['area', year]])


def compute_cbs_waste(input, apply=None, year=None):
    title = f'{apply.__name__}\tkg'
    print(title)

    df = input.copy()

    # get provincie gemeenten
    df = df[df['Provincie'] == 'Utrecht']
    df['Gewicht_KG'] = df.apply(lambda x: apply(x), axis=1)

    # compute for the entire provincie
    df_total = df.copy()
    df = df[[
        'Gebieden',
        'Gewicht_KG',
        'Inwoners'
    ]]
    columns = [
        "Provincie",
        "Gewicht_KG",
        "Inwoners"
    ]
    df_total['Gewicht_KG'] = df_total['Gewicht_KG'] * df_total['Inwoners']
    df_total = df_total[columns].groupby("Provincie").sum().reset_index()
    df_total['Gewicht_KG'] = df_total['Gewicht_KG'] / df_total['Inwoners']

    # add to data
    df['area'] = df['Gebieden']
    df[year] = df['Gewicht_KG']
    df.reset_index(inplace=True)
    DATA.setdefault(f'municipality\t{title}', []).append(df[['area', year]])
    df_total['area'] = df_total['Provincie']
    df_total[year] = df_total['Gewicht_KG']
    df.reset_index(inplace=True)
    DATA.setdefault(f'province\t{title}', []).append(df_total[['area', year]])


if __name__ == '__main__':
    logging.basicConfig(filename="logs.txt",  # file name
                        filemode="w",  # overwrite
                        level=logging.INFO, # lowest warning level
                        format="%(message)s"
                        )

    # import postcodes
    postcodes = pd.read_excel('./data/areas/postcodesNL.xlsx')
    postcodes['PC4'] = postcodes['PC4'].astype(str)
    gemeenten = postcodes[['Gemeente (post 2019)', 'Provincie']].drop_duplicates()

    # import population data
    population = pd.read_csv('./data/areas/populationNL.csv', delimiter=';')

    # import household data
    print('Import household data...\n')
    household_data = import_household_data(areas=gemeenten, population=population)

    # import national ontvangst (2016-2019)
    for year in YEARS:
        print(f'Analyse {year}...')
        lma_flows = import_lma_flows(areas=postcodes, year=year)
        cbs_flows = household_data[household_data['Perioden'] == int(year)]

        # total primary waste (LMA)
        def total_primary_waste(df):
            return df[df['EuralCode'].str[:2] != '19']
        compute_lma_waste(lma_flows, role='Herkomst', apply=total_primary_waste, year=year)

        # total primary waste (CBS)
        title = 'prov\ttotal_household_primary_waste\tmtn'
        cbs_primary_waste(cbs_flows, year=year, title=title)

        # incineration waste (LMA)
        def incineration_waste(df):
            ewc = ['B04', 'F01', 'F02', 'F06', 'F07']
            return df[df['VerwerkingsmethodeCode'].isin(ewc)]
        compute_lma_waste(lma_flows, role='Herkomst', apply=incineration_waste, year=year)

        # landfill waste
        def landfill_waste(df):
            ewc = ['G01', 'G02']
            return df[df['VerwerkingsmethodeCode'].isin(ewc)]
        compute_lma_waste(lma_flows, role='Herkomst', apply=landfill_waste, year=year)

        # reuse of primary waste
        def reuse_primary_waste(df):
            ewc = ['B01', 'B03', 'B05']
            return df[(df['EuralCode'].str[:2] != '19') & (df['VerwerkingsmethodeCode'].isin(ewc))]
        compute_lma_waste(lma_flows, role='Herkomst', apply=reuse_primary_waste, year=year)

        # recycling of primary waste
        def recycling_primary_waste(df):
            ewc = ['C01', 'C02', 'C03', 'C04', 'D01',
                   'D02', 'D03', 'D04', 'D05', 'D06',
                   'E01', 'E02', 'E03',  'E04', 'E05',
                   'F03', 'F04' ]
            return df[(df['EuralCode'].str[:2] != '19') & (df['VerwerkingsmethodeCode'].isin(ewc))]
        compute_lma_waste(lma_flows, role='Herkomst', apply=recycling_primary_waste, year=year)

        # total household waste per inhabitant
        def household_waste_per_inhabitant(df):
            return df["Totaal aangeboden huishoudelijk afval [Kilo's per inwoner]"]
        compute_cbs_waste(cbs_flows, apply=household_waste_per_inhabitant, year=year)

        # household residual waste per inhabitant
        def residual_waste_per_inhabitant(df):
            return df["Hoeveelheid fijn huishoudelijk restafval [Kilo's per inwoner]"] + \
                   df["Hoeveelheid grof huishoudelijk restafval [Kilo's per inwoner]"]
        compute_cbs_waste(cbs_flows, apply=residual_waste_per_inhabitant, year=year)

        # separation of household waste (as % of household waste)
        def separation_waste_per_inhabitant(df):
            return df['Scheidingspercentage totaal huishoudelijk afval [Percentage]'] * 100
        compute_cbs_waste(cbs_flows, apply=separation_waste_per_inhabitant, year=year)

        # residual waste of companies, organisations & governments
        def company_residual_waste(df):
            ewc = ['200301', '200307', '200399']
            return df[df['EuralCode'].isin(ewc)]
        compute_lma_waste(lma_flows, role='Herkomst', apply=company_residual_waste, year=year)

        # reuse of construction & demolition waste
        def reuse_construction_waste(df):
            ewc = ['B01', 'B03', 'B05']
            return df[(df['EuralCode'].str[:2] == '17') & (df['VerwerkingsmethodeCode'].isin(ewc))]
        compute_lma_waste(lma_flows, role='Herkomst', apply=reuse_construction_waste, year=year)

        # recycling of construction & demolition waste
        def recycling_construction_waste(df):
            ewc = ['B01', 'B03', 'B05']
            return df[(df['EuralCode'].str[:2] == '17') & (df['VerwerkingsmethodeCode'].isin(ewc))]
        compute_lma_waste(lma_flows, role='Herkomst', apply=recycling_construction_waste, year=year)

        # food waste
        def food_waste(df):
            ewc = ['020102', '020103', '020201', '020202', '020203',
                   '020301', '020303', '020304', '020501', '020601',
                   '020701', '020702', '020704', '200301', '200399',
                   '200108', '200125', '200302']
            return df[df['EuralCode'].isin(ewc)]
        compute_lma_waste(lma_flows, role='Herkomst', apply=food_waste, year=year)

        # clean memory & collect garbage
        print('\n')
        del lma_flows
        gc.collect()

    results = {}
    for field, field_data in DATA.items():
        df = pd.concat(field_data, axis=1)
        df = df.loc[:, ~df.columns.duplicated()]
        results[field] = json.loads(df.to_json(orient="records"))

    final = {}
    with open('test/household.json', 'w') as outfile:
        for key, value in results.items():
            level, field, unit = key.split('\t')
            final[field] = []
            for item in value:
                name = item.pop('area')
                for year, amount in item.items():
                    final[field].append({
                        'name': name,
                        'level': level,
                        'period': year,
                        'values': {
                            'waste': {
                                unit: amount
                            }
                        }
                    })
        json.dump(final, outfile, indent=4)



