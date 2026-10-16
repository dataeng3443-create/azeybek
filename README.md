# FundAllocation AI Dashboard

A local-first, AI-assisted analytics prototype that simulates a SQL Server Analysis Services (SSAS) Tabular model. It transforms a natural-language analytics question into a validated, read-only DAX-like query, executes it over deterministic synthetic portfolio data, and renders an adaptive Plotly dashboard in Streamlit.

> All values in Phase 1 are synthetic. The application does not connect to an SSAS server until Phase 2 is explicitly enabled.

## Architecture

```text
Question → planner → relevant-schema retrieval → DAX generation → validator
         → SyntheticProvider → result-aware dashboard spec → Plotly + Streamlit
                         ↘ Ollama (local HTTP API) ↗
```

The AI produces structured plans, DAX proposals, and dashboard specifications only. It never produces or executes Python, Streamlit, Plotly, HTML, or arbitrary code. Every DAX query, including manually edited DAX, passes the same validation gate.

## Synthetic semantic model

The deterministic `FundAllocation` model contains:

- Dimensions: `Fund` (30 funds), `Date` (monthly 2024–2026), `Investor`, and `Asset`.
- Fact: `Allocation`, with allocation, target/actual allocation, units, NAV, and return.
- Relationships from each dimension to `Allocation`.
- Measures including Total Allocation, Average Return %, Allocation Variance %, MoM Growth %, and YoY Growth %.

The data intentionally models fund size/risk differences, investor-type behavior, asset allocation, a market drawdown, and recovery. It is cached for the process lifetime and repeatable through `SYNTHETIC_SEED`.

## Run locally

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
streamlit run app.py
```

On Windows activate the environment with `.venv\\Scripts\\activate`.

## Ollama setup

Install and run Ollama, then pull the model configured in `.env`:

```bash
ollama pull qwen3:8b
ollama serve
```

Set `OLLAMA_MODEL` to the exact local model name including its tag (default `qwen3:8b`). Requests are sent with `think: false` and Ollama's JSON output mode, so reasoning models such as Qwen3 return clean structured JSON; this requires a recent Ollama release. The UI reports the health state. If Ollama is unavailable or returns an invalid structured response, the application remains usable using deterministic planner/query/dashboard fallbacks; this is intentional for local demo reliability.

## Sample questions

- `Show total allocation by fund`
- `Show allocation trend over the last 12 months`
- `Compare allocation by risk level`
- `Show the top 10 funds`
- `Which investor segment has the highest allocation?`

## Safety model

- DAX-like input must begin with `EVALUATE`; query length, unknown schema fields, forbidden mutations, and multi-statement input are rejected.
- The prototype supports controlled summary, filtering, ranking, and ordering patterns rather than attempting to implement all DAX.
- Results are capped with `MAX_RESULT_ROWS`.
- Environment secrets are neither hard-coded nor logged.

`EVALUATE` validation alone is not a production security boundary. In real SSAS, combine it with read-only identities, server-side row-level security, timeouts, query/result limits, and audited access.

## Testing

```bash
pytest -q
```

Tests cover the semantic model, validator, synthetic aggregation/filtering, dashboard schema, and unavailable Ollama handling.

## Phase 2: SSAS and PBIT roadmap

The provider boundary is designed for replacement:

```text
SyntheticProvider → SSASProvider → pyadomd / MSOLAP → SQL Server Analysis Services
```

`SSASProvider` is an intentionally inactive Phase 2 scaffold. On a Windows host with the MSOLAP/ADOMD client and `pyadomd`, configure `APP_MODE=ssas`, `SSAS_SERVER`, and `SSAS_DATABASE`; add canonical schema discovery using SSAS metadata (`INFO.TABLES`, `INFO.COLUMNS`, and `INFO.MEASURES`). Keep the AI, dashboard designer, and renderer unchanged.

When a `.pbit` is available, parse its archive only after inspecting its actual contents. Convert its report layout and field bindings into a compact analytical reference; do not pass raw report JSON to the model or copy the template pixel-for-pixel.

## Power BI Report Server

This Streamlit app is a separate AI workspace and is not published directly to Power BI Report Server. The future delivery path is a Report Server-compatible Power BI Desktop `.pbix` with a live connection to the same SSAS Tabular model, published alongside this application. That preserves one governed semantic layer while serving two experiences.
