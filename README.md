# sandcastle

Predict candidate dates for making a sandcastle or digging a sand dam at the Belgian coast.

## Notebooks

- `sandcastle_dates_analysis.ipynb`: candidate days for a sandcastle / sand fort.
- `dammen_bouwen_aan_zee_dates_analysis.ipynb`: candidate days for digging a sand dam.

The notebooks keep the step-by-step visual style, but now use the OD Nature JSON endpoint directly instead of Selenium/Chrome scraping. That makes them easier to run locally, on Hermes, or in normal Jupyter.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m ipykernel install --user --name sandcastle --display-name "Python (sandcastle)"
```

Then open the notebooks in Jupyter and select the kernel `Python (sandcastle)`.

## Quick terminal run

```bash
source .venv/bin/activate
python sandcastle_results.py
```

## Parameters to change

At the top of each notebook:

- `START_DATE` / `END_DATE`: the year or period to analyze.
- `FUTURE_ONLY`: only show remaining dates from today onward.
- `ALLOWED_MONTHS`: default `[5, 6, 9, 10]`, so July/August are skipped.

Activity-specific filters:

- Sandcastle / sand fort: low tide between 11u00 and 13u00, Saturday/Sunday or Belgian public holiday.
- Sand dam: low tide between 15u00 and 17u00, Friday/Saturday/Sunday/Monday or Belgian public holiday.
