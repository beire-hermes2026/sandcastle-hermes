#!/usr/bin/env python3
from __future__ import annotations

import nbformat as nbf

COMMON_SETUP = '''from datetime import date

import pandas as pd
import numpy as np
import requests
from holidays import Belgium

TIDES_URL = "https://odnature.naturalsciences.be/marine-forecasting-centre/nl/ajax/getHarmonicTides"
TIMEZONE = "Europe/Brussels"

# Parameters: change these first when you want another year or another season.
START_DATE = "2026-01-01"
END_DATE = "2026-12-31"
FUTURE_ONLY = True  # True = only show dates from today onward

# Season filter: nice months, but skip the busy summer months.
ALLOWED_MONTHS = [5, 6, 9, 10]
'''

FETCH_CODE = '''def fetch_tides(start_date: str, end_date: str) -> pd.DataFrame:
    """Download harmonic tide predictions as JSON.

    This replaces the older Selenium/Chrome scraping step. It uses the same data
    behind the website button "Tabel actualiseren", but is easier to run in
    Jupyter, on Hermes, and later on another laptop.
    """
    response = requests.get(
        TIDES_URL,
        params={
            "start_date": start_date,
            "end_date": end_date,
            "action": "harmonic-tides",
            "format": "json",
        },
        timeout=30,
    )
    response.raise_for_status()
    return pd.DataFrame(response.json())

raw_df = fetch_tides(START_DATE, END_DATE)
print(f"Downloaded {len(raw_df)} tide records from {START_DATE} until {END_DATE}")
raw_df.head()
'''

CLEAN_CODE = '''df = raw_df.copy()
df.columns = ['datum', 'hoog_water', 'hoog_tijd', 'laag_water', 'laag_tijd']

# Replace missing tide values and turn water levels into numbers.
df = df.replace({"--.--": np.nan})
df = df.astype({'hoog_water': 'float', 'laag_water': 'float'})

# The website gives tide times in UTC. Convert them to local Belgian coast time.
df['datum'] = pd.to_datetime(df['datum'])
df['hoog_tijd'] = pd.to_datetime(df['datum'].dt.strftime('%Y-%m-%d') + ' ' + df['hoog_tijd'], errors='coerce')
df['laag_tijd'] = pd.to_datetime(df['datum'].dt.strftime('%Y-%m-%d') + ' ' + df['laag_tijd'], errors='coerce')
df['hoog_tijd'] = df['hoog_tijd'].dt.tz_localize('UTC').dt.tz_convert(TIMEZONE)
df['laag_tijd'] = df['laag_tijd'].dt.tz_localize('UTC').dt.tz_convert(TIMEZONE)
df.drop(['datum'], axis=1, inplace=True)

df.to_csv('getijden.csv', index=False)
print('Stored cleaned tide table as getijden.csv')
df.head()
'''

HOLIDAY_CODE = '''unique_years = df['laag_tijd'].dropna().dt.year.unique().tolist()
belgian_holidays = Belgium(years=unique_years)
feestdagen = [str(day) for day in belgian_holidays.keys()]

month_filter = df['laag_tijd'].dt.month.isin(ALLOWED_MONTHS)
feestdag_filter = df['laag_tijd'].dt.date.astype(str).isin(feestdagen)

print(f"Belgian holidays loaded for: {unique_years}")
print(f"Allowed months: {ALLOWED_MONTHS}")
'''

RESULT_CODE = '''combined_filter = low_tide_filter & month_filter & weekend_feestdag

if FUTURE_ONLY:
    combined_filter = combined_filter & (df['laag_tijd'].dt.date >= date.today())

best_days = df[combined_filter].sort_values('laag_tijd').copy()
best_days
'''

PRINT_CODE = '''if best_days.empty:
    print("No candidate days found with these parameters.")
else:
    max_length = max([len(row['laag_tijd'].strftime("%A %d %B %Y")) for _, row in best_days.iterrows()])

    for _, row in best_days.iterrows():
        date_str = row['laag_tijd'].strftime("%A %d %B %Y")
        low_time = row['laag_tijd'].strftime("%Hu%M")
        high_time = row['hoog_tijd'].strftime("%Hu%M") if pd.notna(row['hoog_tijd']) else "onbekend"
        low_level = row['laag_water']
        print(f"{date_str:<{max_length}} (laag water {low_time}, hoog water {high_time}, laagwaterstand {low_level:.2f} m TAW)")
'''


def make_notebook(kind: str) -> nbf.NotebookNode:
    if kind == "sandcastle":
        banner = "sandcastle_intro_banner.png"
        title = "Sandcastle / sand fort candidate dates"
        intro = "We look for low tide around midday. Earlier tests showed that predicted low tide around 12u can give a useful afternoon moment when the sea reaches the castle again."
        low_code = '''# Sandcastle / sand fort: low tide between 11u00 and 13u00 local time.
low_tide_filter = (df['laag_tijd'].dt.hour >= 11) & (df['laag_tijd'].dt.hour < 13)

# Keep this strict: Saturday or Sunday, plus Belgian public holidays.
weekend_filter = df['laag_tijd'].dt.weekday.isin([5, 6])
weekend_feestdag = weekend_filter | feestdag_filter
'''
    else:
        banner = "seadam.png"
        title = "Zanddam / dam schuppen candidate dates"
        intro = "We look for low tide later in the afternoon. The idea is: drive in the morning, arrive around 9u30, start around 10u30-11u00, and get a long useful water-flow window."
        low_code = '''# Zanddam / dam schuppen: low tide between 15u00 and 17u00 local time.
low_tide_filter = (df['laag_tijd'].dt.hour >= 15) & (df['laag_tijd'].dt.hour < 17)

# Dam activity can also work with a long weekend rhythm: Friday, Saturday, Sunday or Monday,
# plus Belgian public holidays.
weekend_filter = df['laag_tijd'].dt.weekday.isin([4, 5, 6, 0])
weekend_feestdag = weekend_filter | feestdag_filter
'''

    nb = nbf.v4.new_notebook()
    nb.cells = [
        nbf.v4.new_markdown_cell(f"![banner image](./{banner})"),
        nbf.v4.new_markdown_cell(f"# {title}\n\n{intro}\n\nThis notebook keeps the step-by-step visual style, but no longer needs Selenium or Chrome. It calls the same JSON data endpoint that the OD Nature tide website uses behind the table button."),
        nbf.v4.new_markdown_cell("## 1. Setup and parameters\n\nChange `START_DATE`, `END_DATE`, `FUTURE_ONLY`, or `ALLOWED_MONTHS` here when you want another run. The tide times are converted from UTC to `Europe/Brussels`."),
        nbf.v4.new_code_cell(COMMON_SETUP),
        nbf.v4.new_markdown_cell("## 2. Download the tide table\n\nThe website builds its table from a JSON endpoint. Calling that directly is cleaner and more robust than opening a browser with Selenium."),
        nbf.v4.new_code_cell(FETCH_CODE),
        nbf.v4.new_markdown_cell("## 3. Clean and prepare the data\n\nWe rename the columns, convert water levels to numbers, combine date + time, and convert UTC tide times to Belgian local time."),
        nbf.v4.new_code_cell(CLEAN_CODE),
        nbf.v4.new_markdown_cell("## 4. Build the common filters\n\nWe keep the useful season months and Belgian public holidays. July and August stay excluded by default because the coast is busier."),
        nbf.v4.new_code_cell(HOLIDAY_CODE),
        nbf.v4.new_markdown_cell("## 5. Activity-specific filter"),
        nbf.v4.new_code_cell(low_code),
        nbf.v4.new_markdown_cell("## 6. Candidate days"),
        nbf.v4.new_code_cell(RESULT_CODE),
        nbf.v4.new_markdown_cell("## 7. Human-readable result"),
        nbf.v4.new_code_cell(PRINT_CODE),
    ]
    return nb


nbf.write(make_notebook("sandcastle"), "sandcastle_dates_analysis.ipynb")
nbf.write(make_notebook("dam"), "dammen_bouwen_aan_zee_dates_analysis.ipynb")
print("Updated notebooks")
