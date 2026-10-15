# Market Gaps Interactive App

A Streamlit client for exploring Hedegreen Research Market Gaps cases and working with structured case packages.

## Status and Public Links

The source code is public. A hosted Streamlit app address is not recorded in this repository yet.

- [Public case register in TID](https://hedegreenresearch.com/tid/market-gaps/) — case status, articles, evidence boundaries and downloadable materials.
- [Source repository](https://github.com/DennisHedegreen/hr-market-gaps).
- [Hedegreen Research](https://hedegreenresearch.com/).

The TID register is not the interactive app. Publishing a case or its calculations does not establish commercial viability.

## What the App Does

The public catalogue contains reviewed TID cases. The interface also supports structured case packages in a session-based workspace. Private packages are not bundled in this repository or added to the public catalogue merely by importing them.

If you use a hosted instance, an imported file is processed in that hosted session. Do not upload confidential material unless that hosting boundary is acceptable. Running locally is a separate option.

## Run Locally

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run streamlit_app.py
```

The entrypoint is `streamlit_app.py`; the engine and adapters live in `src/hr_market_gaps/`. The public case registry is `public/market-gaps.json`.

## Read the Results as Scenarios

Results depend on the selected case, supplied evidence and model assumptions. A calculated result is not a guarantee of demand, funding, execution or profitability. Keep the case's original status and evidence limits with any result you share.
