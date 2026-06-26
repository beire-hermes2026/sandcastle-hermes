#!/usr/bin/env python3
"""Bereken kandidaatdagen voor zandkasteel en zanddam aan de Belgische kust.

Deze helper volgt dezelfde logica als de notebooks, maar haalt de getijden
rechtstreeks op via de JSON-endpoint van de OD Nature pagina. Daardoor is er
geen Selenium/Chrome nodig om de resultaten snel te testen.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from typing import Iterable

import pandas as pd
import requests
from holidays import Belgium

TIDES_URL = "https://odnature.naturalsciences.be/marine-forecasting-centre/nl/ajax/getHarmonicTides"
TIMEZONE = "Europe/Brussels"

START_DATE = "2026-01-01"
END_DATE = "2026-12-31"
FUTURE_ONLY = True

# Candidate months. July/August stay visible, but are flagged as busy-summer
# candidates. November is included because a good tide window can still be fun
# if the weather happens to cooperate.
ALLOWED_MONTHS = [5, 6, 7, 8, 9, 10, 11]
BUSY_SUMMER_MONTHS = [7, 8]
SHOW_BUSY_SUMMER = True

# Dam-specific timing model.
# The sea does not instantly pull back at high tide. We assume a practical
# dam-start time after the previous high water plus this retreat delay.
DAM_RETREAT_AFTER_HIGH_HOURS = 1.5
DAM_EARLIEST_PRACTICAL_START = time(10, 0)
DAM_LATEST_PRACTICAL_START = time(12, 30)
DAM_MIN_WORK_HOURS_BEFORE_LOW = 3.0
DAM_ACCEPTABLE_LOW_TIDE_START_HOUR = 14
DAM_ACCEPTABLE_LOW_TIDE_END_HOUR = 18
DAM_BEST_LOW_TIDE_START_HOUR = 15
DAM_BEST_LOW_TIDE_END_HOUR = 17
DAM_ALLOWED_WEEKDAYS = (4, 5, 6, 0)  # vrijdag, zaterdag, zondag, maandag


@dataclass(frozen=True)
class Activity:
    name: str
    low_tide_start_hour: int
    low_tide_end_hour: int
    weekdays: tuple[int, ...]
    explanation: str


ACTIVITIES = [
    Activity(
        name="zandkasteel / sand fort",
        low_tide_start_hour=11,
        low_tide_end_hour=13,
        weekdays=(5, 6),  # zaterdag, zondag
        explanation="laag water tussen 11u00 en 13u00; historisch goed voor namiddag-impact rond 16u",
    ),
]


def fetch_tides(start_date: str, end_date: str) -> pd.DataFrame:
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
    data = response.json()
    df = pd.DataFrame(data)
    df.columns = ["datum", "hoog_water", "hoog_tijd", "laag_water", "laag_tijd"]
    df = df.replace({"--.--": pd.NA})
    df["hoog_water"] = pd.to_numeric(df["hoog_water"], errors="coerce")
    df["laag_water"] = pd.to_numeric(df["laag_water"], errors="coerce")
    df["datum"] = pd.to_datetime(df["datum"])
    df["hoog_tijd"] = pd.to_datetime(df["datum"].dt.strftime("%Y-%m-%d") + " " + df["hoog_tijd"], errors="coerce")
    df["laag_tijd"] = pd.to_datetime(df["datum"].dt.strftime("%Y-%m-%d") + " " + df["laag_tijd"], errors="coerce")
    df["hoog_tijd"] = df["hoog_tijd"].dt.tz_localize("UTC").dt.tz_convert(TIMEZONE)
    df["laag_tijd"] = df["laag_tijd"].dt.tz_localize("UTC").dt.tz_convert(TIMEZONE)
    return df.drop(columns=["datum"])


def season_filter(df: pd.DataFrame, show_busy_summer: bool = SHOW_BUSY_SUMMER) -> pd.Series:
    months = list(ALLOWED_MONTHS)
    if show_busy_summer:
        months += BUSY_SUMMER_MONTHS
    months = list(dict.fromkeys(months))
    return df["laag_tijd"].dt.month.isin(months)


def belgian_holiday_filter(df: pd.DataFrame) -> pd.Series:
    unique_years = df["laag_tijd"].dropna().dt.year.unique().tolist()
    belgian_holidays = Belgium(years=unique_years)
    return df["laag_tijd"].dt.date.astype(str).isin([str(d) for d in belgian_holidays.keys()])


def candidates(df: pd.DataFrame, activity: Activity, future_only: bool = True) -> pd.DataFrame:
    low_tide_filter = (
        (df["laag_tijd"].dt.hour >= activity.low_tide_start_hour)
        & (df["laag_tijd"].dt.hour < activity.low_tide_end_hour)
    )
    weekend_filter = df["laag_tijd"].dt.weekday.isin(activity.weekdays)
    mask = low_tide_filter & season_filter(df) & (weekend_filter | belgian_holiday_filter(df))
    if future_only:
        mask &= df["laag_tijd"].dt.date >= date.today()
    return df.loc[mask].sort_values("laag_tijd").copy()


def add_tide_cycle_context(df: pd.DataFrame) -> pd.DataFrame:
    """Add previous/next high water and practical dam timing context.

    The source rows pair one high-water value and one low-water value, but the
    paired high water is not always the one before the low water. For damming we
    need the previous high tide, because the useful work starts after the sea has
    begun to retreat.
    """
    result = df.copy()
    high_events = (
        df[["hoog_tijd", "hoog_water"]]
        .dropna(subset=["hoog_tijd"])
        .rename(columns={"hoog_tijd": "high_time", "hoog_water": "high_water"})
        .sort_values("high_time")
        .reset_index(drop=True)
    )

    previous_high_times = []
    previous_high_levels = []
    next_high_times = []
    next_high_levels = []
    workable_start_times = []
    work_hours_before_low = []

    for low_time in result["laag_tijd"]:
        if pd.isna(low_time):
            previous_high_times.append(pd.NaT)
            previous_high_levels.append(pd.NA)
            next_high_times.append(pd.NaT)
            next_high_levels.append(pd.NA)
            workable_start_times.append(pd.NaT)
            work_hours_before_low.append(pd.NA)
            continue

        previous = high_events[high_events["high_time"] < low_time].tail(1)
        next_ = high_events[high_events["high_time"] > low_time].head(1)

        if previous.empty:
            previous_high_time = pd.NaT
            previous_high_level = pd.NA
            workable_start = pd.NaT
            hours_before_low = pd.NA
        else:
            previous_high_time = previous.iloc[0]["high_time"]
            previous_high_level = previous.iloc[0]["high_water"]
            workable_start = previous_high_time + pd.Timedelta(hours=DAM_RETREAT_AFTER_HIGH_HOURS)
            hours_before_low = (low_time - workable_start).total_seconds() / 3600

        if next_.empty:
            next_high_time = pd.NaT
            next_high_level = pd.NA
        else:
            next_high_time = next_.iloc[0]["high_time"]
            next_high_level = next_.iloc[0]["high_water"]

        previous_high_times.append(previous_high_time)
        previous_high_levels.append(previous_high_level)
        next_high_times.append(next_high_time)
        next_high_levels.append(next_high_level)
        workable_start_times.append(workable_start)
        work_hours_before_low.append(hours_before_low)

    result["vorig_hoog_tij"] = previous_high_times
    result["vorig_hoog_water"] = previous_high_levels
    result["volgend_hoog_tij"] = next_high_times
    result["volgend_hoog_water"] = next_high_levels
    result["praktische_start_vanaf"] = workable_start_times
    result["werkuren_tot_laag"] = work_hours_before_low
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
    low_hour = row["laag_tijd"].hour
    start_time = row["praktische_start_vanaf"].time() if pd.notna(row["praktische_start_vanaf"]) else None
    work_hours = row["werkuren_tot_laag"]

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


def dam_candidates(
    df: pd.DataFrame,
    future_only: bool = FUTURE_ONLY,
    show_busy_summer: bool = SHOW_BUSY_SUMMER,
) -> pd.DataFrame:
    timed = add_tide_cycle_context(df)
    low_tide_window = (
        (timed["laag_tijd"].dt.hour >= DAM_ACCEPTABLE_LOW_TIDE_START_HOUR)
        & (timed["laag_tijd"].dt.hour < DAM_ACCEPTABLE_LOW_TIDE_END_HOUR)
    )
    day_filter = timed["laag_tijd"].dt.weekday.isin(DAM_ALLOWED_WEEKDAYS) | belgian_holiday_filter(timed)
    practical_start_filter = timed["praktische_start_vanaf"].dt.time <= DAM_LATEST_PRACTICAL_START
    work_window_filter = timed["werkuren_tot_laag"] >= DAM_MIN_WORK_HOURS_BEFORE_LOW
    mask = low_tide_window & season_filter(timed, show_busy_summer) & day_filter & practical_start_filter & work_window_filter
    if future_only:
        mask &= timed["laag_tijd"].dt.date >= date.today()

    rows = timed.loc[mask].sort_values("laag_tijd").copy()
    rows["zomerdrukte"] = rows["laag_tijd"].dt.month.isin(BUSY_SUMMER_MONTHS)
    rows["waterstand_score"] = rows["laag_water"].apply(water_level_score)
    rows["timing_score"] = rows.apply(dam_timing_score, axis=1)
    return rows


def format_candidates(rows: pd.DataFrame) -> Iterable[str]:
    for _, row in rows.iterrows():
        day = row["laag_tijd"].strftime("%A %d %B %Y")
        low = row["laag_tijd"].strftime("%Hu%M")
        high = row["hoog_tijd"].strftime("%Hu%M") if pd.notna(row["hoog_tijd"]) else "onbekend"
        yield f"- {day}: laag water {low}, hoog water {high}, laagwaterstand {row['laag_water']:.2f} m TAW"


def format_dam_candidates(rows: pd.DataFrame) -> Iterable[str]:
    for _, row in rows.iterrows():
        day = row["laag_tijd"].strftime("%A %d %B %Y")
        low = row["laag_tijd"].strftime("%Hu%M")
        previous_high = row["vorig_hoog_tij"].strftime("%Hu%M") if pd.notna(row["vorig_hoog_tij"]) else "onbekend"
        start = row["praktische_start_vanaf"].strftime("%Hu%M") if pd.notna(row["praktische_start_vanaf"]) else "onbekend"
        busy = " — juli/augustus: druk" if row.get("zomerdrukte", False) else ""
        yield (
            f"- {day}: vorig hoog tij {previous_high}, praktische start vanaf {start}, "
            f"laag water {low}, {row['werkuren_tot_laag']:.1f}u schopvenster, "
            f"{row['laag_water']:.2f} m TAW ({row['waterstand_score']}), {row['timing_score']}{busy}"
        )


def main() -> None:
    df = fetch_tides(START_DATE, END_DATE)
    print("Getijden opgehaald:", len(df), "records")
    print("Bron:", TIDES_URL)
    print()

    for activity in ACTIVITIES:
        rows = candidates(df, activity, future_only=FUTURE_ONLY)
        print(activity.name)
        print(activity.explanation)
        if rows.empty:
            print("- Geen toekomstige kandidaten in 2026 volgens deze filters.")
        else:
            for line in format_candidates(rows):
                print(line)
        print()

    rows = dam_candidates(df, future_only=FUTURE_ONLY, show_busy_summer=SHOW_BUSY_SUMMER)
    print("zanddam / dam schuppen")
    print("vorig hoog tij + terugtrekvertraging, dan minstens 3 uur schopvenster vóór laag tij")
    if rows.empty:
        print("- Geen toekomstige kandidaten in 2026 volgens deze filters.")
    else:
        for line in format_dam_candidates(rows):
            print(line)


if __name__ == "__main__":
    main()
