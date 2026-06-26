#!/usr/bin/env python3
from __future__ import annotations

import nbformat as nbf

COMMON_SETUP = '''from datetime import date, time

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

# Candidate months. July/August stay visible, but are flagged as busy-summer
# candidates. November is included because a good tide window can still be fun
# if the weather happens to cooperate.
ALLOWED_MONTHS = [5, 6, 7, 8, 9, 10, 11]
BUSY_SUMMER_MONTHS = [7, 8]
SHOW_BUSY_SUMMER = True
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

COMMON_FILTERS = '''unique_years = df['laag_tijd'].dropna().dt.year.unique().tolist()
belgian_holidays = Belgium(years=unique_years)
feestdagen = [str(day) for day in belgian_holidays.keys()]

months_to_show = list(ALLOWED_MONTHS)
if SHOW_BUSY_SUMMER:
    months_to_show += BUSY_SUMMER_MONTHS
months_to_show = list(dict.fromkeys(months_to_show))

month_filter = df['laag_tijd'].dt.month.isin(months_to_show)
feestdag_filter = df['laag_tijd'].dt.date.astype(str).isin(feestdagen)

print(f"Belgian holidays loaded for: {unique_years}")
print(f"Allowed months: {months_to_show}")
print(f"Show July/August as busy candidates: {SHOW_BUSY_SUMMER}")
'''

SANDCASTLE_FILTER = '''# Sandcastle / sand fort: low tide between 11u00 and 13u00 local time.
low_tide_filter = (df['laag_tijd'].dt.hour >= 11) & (df['laag_tijd'].dt.hour < 13)

# Keep this strict: Saturday or Sunday, plus Belgian public holidays.
weekend_filter = df['laag_tijd'].dt.weekday.isin([5, 6])
weekend_feestdag = weekend_filter | feestdag_filter

combined_filter = low_tide_filter & month_filter & weekend_feestdag
if FUTURE_ONLY:
    combined_filter = combined_filter & (df['laag_tijd'].dt.date >= date.today())

best_days = df[combined_filter].sort_values('laag_tijd').copy()
best_days
'''

SANDCASTLE_PRINT = '''if best_days.empty:
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

DAM_PARAMETERS = '''# Dam timing parameters.
# We do NOT want to start at low tide. We want to start while the sea is already dropping,
# after it has pulled back enough to pick a good spot and dig while it keeps dropping.
DAM_RETREAT_AFTER_HIGH_HOURS = 1.5       # first practical moment after previous high tide
DAM_LATEST_PRACTICAL_START = time(12, 30)
DAM_MIN_WORK_HOURS_BEFORE_LOW = 3.0
DAM_ACCEPTABLE_LOW_TIDE_START_HOUR = 14
DAM_ACCEPTABLE_LOW_TIDE_END_HOUR = 18
DAM_BEST_LOW_TIDE_START_HOUR = 15
DAM_BEST_LOW_TIDE_END_HOUR = 17
DAM_ALLOWED_WEEKDAYS = [4, 5, 6, 0]      # Friday, Saturday, Sunday, Monday
'''

DAM_CONTEXT = '''def add_tide_cycle_context(df: pd.DataFrame) -> pd.DataFrame:
    """Find the previous high tide before every low tide.

    This matters for damming: the useful window starts after high tide, when the
    sea has begun to retreat. The low-tide time alone is not enough.
    """
    result = df.copy()
    high_events = (
        df[['hoog_tijd', 'hoog_water']]
        .dropna(subset=['hoog_tijd'])
        .rename(columns={'hoog_tijd': 'high_time', 'hoog_water': 'high_water'})
        .sort_values('high_time')
        .reset_index(drop=True)
    )

    previous_high_times = []
    workable_start_times = []
    work_hours_before_low = []

    for low_time in result['laag_tijd']:
        previous = high_events[high_events['high_time'] < low_time].tail(1)
        if previous.empty:
            previous_high = pd.NaT
            workable_start = pd.NaT
            hours_before_low = np.nan
        else:
            previous_high = previous.iloc[0]['high_time']
            workable_start = previous_high + pd.Timedelta(hours=DAM_RETREAT_AFTER_HIGH_HOURS)
            hours_before_low = (low_time - workable_start).total_seconds() / 3600

        previous_high_times.append(previous_high)
        workable_start_times.append(workable_start)
        work_hours_before_low.append(hours_before_low)

    result['vorig_hoog_tij'] = previous_high_times
    result['praktische_start_vanaf'] = workable_start_times
    result['werkuren_tot_laag'] = work_hours_before_low
    return result


def water_level_score(low_water: float) -> str:
    if pd.isna(low_water):
        return "onbekend waterpeil"
    if low_water <= 1.0:
        return "zeer laag water"
    if low_water <= 1.25:
        return "goed laag water"
    if low_water <= 1.5:
        return "matig laag water"
    return "hoog laagwater"


def dam_timing_score(row: pd.Series) -> str:
    low_hour = row['laag_tijd'].hour
    start_time = row['praktische_start_vanaf'].time() if pd.notna(row['praktische_start_vanaf']) else None
    work_hours = row['werkuren_tot_laag']

    if start_time is None or pd.isna(work_hours):
        return "onzeker: vorig hoog tij ontbreekt"
    if (
        DAM_BEST_LOW_TIDE_START_HOUR <= low_hour < DAM_BEST_LOW_TIDE_END_HOUR
        and start_time <= time(12, 0)
        and work_hours >= 3.5
    ):
        return "zeer goed: dalend water + ruim schopvenster"
    if start_time <= DAM_LATEST_PRACTICAL_START and work_hours >= DAM_MIN_WORK_HOURS_BEFORE_LOW:
        return "goed: realistisch schopvenster vóór laag tij"
    return "mogelijk maar krap"
'''

DAM_FILTER = '''timed = add_tide_cycle_context(df)

low_tide_window = (
    (timed['laag_tijd'].dt.hour >= DAM_ACCEPTABLE_LOW_TIDE_START_HOUR)
    & (timed['laag_tijd'].dt.hour < DAM_ACCEPTABLE_LOW_TIDE_END_HOUR)
)

day_filter = timed['laag_tijd'].dt.weekday.isin(DAM_ALLOWED_WEEKDAYS) | feestdag_filter
practical_start_filter = timed['praktische_start_vanaf'].dt.time <= DAM_LATEST_PRACTICAL_START
work_window_filter = timed['werkuren_tot_laag'] >= DAM_MIN_WORK_HOURS_BEFORE_LOW

combined_filter = low_tide_window & month_filter & day_filter & practical_start_filter & work_window_filter
if FUTURE_ONLY:
    combined_filter = combined_filter & (timed['laag_tijd'].dt.date >= date.today())

best_days = timed[combined_filter].sort_values('laag_tijd').copy()
best_days['zomerdrukte'] = best_days['laag_tijd'].dt.month.isin(BUSY_SUMMER_MONTHS)
best_days['waterstand_score'] = best_days['laag_water'].apply(water_level_score)
best_days['timing_score'] = best_days.apply(dam_timing_score, axis=1)

best_days[['vorig_hoog_tij', 'praktische_start_vanaf', 'laag_tijd', 'werkuren_tot_laag', 'laag_water', 'waterstand_score', 'timing_score', 'zomerdrukte']]
'''

DAM_PRINT = '''if best_days.empty:
    print("No candidate days found with these parameters.")
else:
    max_length = max([len(row['laag_tijd'].strftime("%A %d %B %Y")) for _, row in best_days.iterrows()])

    for _, row in best_days.iterrows():
        date_str = row['laag_tijd'].strftime("%A %d %B %Y")
        previous_high = row['vorig_hoog_tij'].strftime("%Hu%M") if pd.notna(row['vorig_hoog_tij']) else "onbekend"
        start = row['praktische_start_vanaf'].strftime("%Hu%M") if pd.notna(row['praktische_start_vanaf']) else "onbekend"
        low_time = row['laag_tijd'].strftime("%Hu%M")
        busy = " — juli/augustus: druk" if row['zomerdrukte'] else ""
        print(
            f"{date_str:<{max_length}} "
            f"(vorig hoog tij {previous_high}, praktische start vanaf {start}, "
            f"laag water {low_time}, {row['werkuren_tot_laag']:.1f}u schopvenster, "
            f"{row['laag_water']:.2f} m TAW — {row['waterstand_score']}, "
            f"{row['timing_score']}{busy})"
        )
'''


def base_cells(banner: str, title: str, intro: str) -> list[nbf.NotebookNode]:
    return [
        nbf.v4.new_markdown_cell(f"![banner image](./{banner})"),
        nbf.v4.new_markdown_cell(f"# {title}\n\n{intro}\n\nThis notebook keeps the step-by-step visual style, but no longer needs Selenium or Chrome. It calls the same JSON data endpoint that the OD Nature tide website uses behind the table button."),
        nbf.v4.new_markdown_cell("## 1. Setup and parameters\n\nChange `START_DATE`, `END_DATE`, `FUTURE_ONLY`, `ALLOWED_MONTHS`, or `SHOW_BUSY_SUMMER` here when you want another run. The tide times are converted from UTC to `Europe/Brussels`."),
        nbf.v4.new_code_cell(COMMON_SETUP),
        nbf.v4.new_markdown_cell("## 2. Download the tide table\n\nThe website builds its table from a JSON endpoint. Calling that directly is cleaner and more robust than opening a browser with Selenium."),
        nbf.v4.new_code_cell(FETCH_CODE),
        nbf.v4.new_markdown_cell("## 3. Clean and prepare the data\n\nWe rename the columns, convert water levels to numbers, combine date + time, and convert UTC tide times to Belgian local time."),
        nbf.v4.new_code_cell(CLEAN_CODE),
        nbf.v4.new_markdown_cell("## 4. Common filters\n\nWe keep the useful season months and Belgian public holidays. July and August are optional via `SHOW_BUSY_SUMMER`."),
        nbf.v4.new_code_cell(COMMON_FILTERS),
    ]


def make_sandcastle_notebook() -> nbf.NotebookNode:
    nb = nbf.v4.new_notebook()
    nb.cells = base_cells(
        "sandcastle_intro_banner.png",
        "Sandcastle / sand fort candidate dates",
        "We look for low tide around midday. Earlier tests showed that predicted low tide around 12u can give a useful afternoon moment when the sea reaches the castle again.",
    ) + [
        nbf.v4.new_markdown_cell("## 5. Sandcastle filter"),
        nbf.v4.new_code_cell(SANDCASTLE_FILTER),
        nbf.v4.new_markdown_cell("## 6. Human-readable result"),
        nbf.v4.new_code_cell(SANDCASTLE_PRINT),
    ]
    return nb


def make_dam_notebook() -> nbf.NotebookNode:
    nb = nbf.v4.new_notebook()
    nb.cells = base_cells(
        "seadam.png",
        "Zanddam / dam schuppen candidate dates",
        "We do not simply look for low tide. We model the useful work window: previous high tide, some time for the sea to pull back, then enough time to dig while the water keeps dropping before low tide.",
    ) + [
        nbf.v4.new_markdown_cell("## 5. Dam timing parameters\n\nThe important idea: starting at exact low tide is too late. We want previous high tide in the morning, then a practical start once the sea has pulled back, then at least a few hours before low tide."),
        nbf.v4.new_code_cell(DAM_PARAMETERS),
        nbf.v4.new_markdown_cell("## 6. Add tide-cycle context\n\nThe source table has high and low values per row, but the high value is not always the high tide before that low tide. So we explicitly find the previous high tide for every low tide."),
        nbf.v4.new_code_cell(DAM_CONTEXT),
        nbf.v4.new_markdown_cell("## 7. Candidate dam days\n\nFilters: acceptable low tide between 14u and 18u, enough work time before low tide, Friday/Saturday/Sunday/Monday or Belgian holiday, allowed months, optionally July/August."),
        nbf.v4.new_code_cell(DAM_FILTER),
        nbf.v4.new_markdown_cell("## 8. Human-readable result"),
        nbf.v4.new_code_cell(DAM_PRINT),
    ]
    return nb


nbf.write(make_sandcastle_notebook(), "sandcastle_dates_analysis.ipynb")
nbf.write(make_dam_notebook(), "dammen_bouwen_aan_zee_dates_analysis.ipynb")
print("Updated notebooks")
