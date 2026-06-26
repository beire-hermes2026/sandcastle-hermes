#!/usr/bin/env python3
"""Bereken kandidaatdagen voor zandkasteel en zanddam aan de Belgische kust.

Deze helper volgt dezelfde logica als de notebooks, maar haalt de getijden
rechtstreeks op via de JSON-endpoint van de OD Nature pagina. Daardoor is er
geen Selenium/Chrome nodig om de resultaten snel te testen.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable

import pandas as pd
import requests
from holidays import Belgium

TIDES_URL = "https://odnature.naturalsciences.be/marine-forecasting-centre/nl/ajax/getHarmonicTides"
TIMEZONE = "Europe/Brussels"


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
    Activity(
        name="zanddam / dam schuppen",
        low_tide_start_hour=15,
        low_tide_end_hour=17,
        weekdays=(4, 5, 6, 0),  # vrijdag, zaterdag, zondag, maandag
        explanation="laag water tussen 15u00 en 17u00; ochtend rijden, rond 10u30-11u starten, lang werkvenster",
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


def candidates(df: pd.DataFrame, activity: Activity, future_only: bool = True) -> pd.DataFrame:
    month_filter = (
        (df["laag_tijd"].dt.month >= 5)
        & (df["laag_tijd"].dt.month <= 10)
        & ~(df["laag_tijd"].dt.month.isin([7, 8]))
    )
    low_tide_filter = (
        (df["laag_tijd"].dt.hour >= activity.low_tide_start_hour)
        & (df["laag_tijd"].dt.hour < activity.low_tide_end_hour)
    )
    unique_years = df["laag_tijd"].dropna().dt.year.unique().tolist()
    belgian_holidays = Belgium(years=unique_years)
    feast_filter = df["laag_tijd"].dt.date.astype(str).isin([str(d) for d in belgian_holidays.keys()])
    weekend_filter = df["laag_tijd"].dt.weekday.isin(activity.weekdays)
    mask = low_tide_filter & month_filter & (weekend_filter | feast_filter)
    if future_only:
        mask &= df["laag_tijd"].dt.date >= date.today()
    return df.loc[mask].sort_values("laag_tijd").copy()


def format_candidates(rows: pd.DataFrame) -> Iterable[str]:
    for _, row in rows.iterrows():
        day = row["laag_tijd"].strftime("%A %d %B %Y")
        low = row["laag_tijd"].strftime("%Hu%M")
        high = row["hoog_tijd"].strftime("%Hu%M") if pd.notna(row["hoog_tijd"]) else "onbekend"
        yield f"- {day}: laag water {low}, hoog water {high}, laagwaterstand {row['laag_water']:.2f} m TAW"


def main() -> None:
    df = fetch_tides("2026-01-01", "2026-12-31")
    print("Getijden opgehaald:", len(df), "records")
    print("Bron:", TIDES_URL)
    print()
    for activity in ACTIVITIES:
        rows = candidates(df, activity, future_only=True)
        print(activity.name)
        print(activity.explanation)
        if rows.empty:
            print("- Geen toekomstige kandidaten in 2026 volgens deze filters.")
        else:
            for line in format_candidates(rows):
                print(line)
        print()


if __name__ == "__main__":
    main()
