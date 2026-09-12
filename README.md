# Institutional Valuation System (IVS)

**Can an automated fundamental valuation model identify stocks that beat the market?**

Final project for the Data Science & Machine Learning bootcamp. It combines a
production equity valuation system (FastAPI + React) with an empirical study
that tests whether its signal predicts future returns.

---

## The business problem

The financial sector devotes enormous resources to fundamental analysis. If a
discounted cash flow model, run systematically across thousands of companies,
had predictive power, it would be exploitable. And if it **doesn't**, that's
also a result: evidence in favor of the efficient market hypothesis.

This project builds that model, applies it to **2,305 companies**, and
empirically tests its predictive power.

## The data

| Source | Content | Volume |
|---|---|---|
| Yahoo Finance (screener endpoint) | US small/mid cap universe, $300M–$10B | 2,305 tickers |
| Yahoo Finance (`yfinance`) | Financial statements and prices | 1,437 valued |
| In-house valuation engine | DCF · Excess Return · AFFO | 1,437 rows × 32 features |
| Post-scan prices | Target variable | 1,421 labeled |

**Target variable:** `beats_market` — did the stock outperform the S&P 500
between the scan date (2026-08-04) and the following close (2026-08-26, 18
sessions)? Base rate: **45.1%**.

---

## Key results

### 1 · Margin of safety doesn't predict linearly

Pearson correlation between margin of safety and excess return: **−0.009**.
The deciles show no monotonic progression.

### 2 · But verdicts do separate returns

| Verdict | n | Median excess return |
|---|---|---|
| STRONG BUY | 298 | **+0.55%** |
| SELL/AVOID | 986 | **−1.06%** |

Mann-Whitney U: **p = 0.003**, a significant difference. A non-parametric test
is used because the return distribution has fat tails.

Results 1 and 2 don't contradict each other: if there is a signal, it's
**neither linear nor monotonic** — it lives at the tails of the distribution.

### 3 · The model reaches AUC 0.71 — and that's where the trap lies

| Model | ROC-AUC (test) |
|---|---|
| Baseline (majority class) | 0.500 |
| Logistic Regression | **0.722** |
| Random Forest | 0.698 |
| Gradient Boosting (tuned) | 0.707 |

Probability quintiles ordered monotonically, with a **+5.6 percentage point**
spread between the top and bottom quintiles.

### 4 · The ablation dismantles the previous result

| Feature block | AUC |
|---|---|
| All | 0.688 |
| **Sector and model only** | **0.620** |
| Price and size only | 0.598 |
| **Valuation only (the thesis)** | **0.578** |

**Sector alone predicts better than the entire valuation thesis combined.**

With a **single time window**, the "sector" variable doesn't measure a stable
business property: it memorizes *which sectors rose during those three
weeks*. Cross-validation can't detect this because all folds share the same
market regime.

> ### Conclusion
>
> The DCF margin of safety has **weak but non-zero** predictive power at 18
> sessions (AUC 0.578 in isolation). What **cannot** be claimed is that the
> full model predicts: most of its 0.71 AUC comes from a cross-sectional
> artifact.
>
> Detecting that artifact is the outcome of this project. Presenting the 0.71
> without the ablation would have been a serious mistake.

---

## Repository structure

```
├── README.md                    ← this file
├── GUIA_DEL_PROYECTO.md         ← what each file is and requirement status
├── requirements.txt
│
├── notebooks/
│   ├── 01_Recoleccion_de_Datos.ipynb        Problem, universe, label
│   ├── 02_Preparacion_y_Limpieza.ipynb      Nulls, outliers, encoding, features
│   ├── 03_Analisis_Exploratorio_EDA.ipynb   Distributions, correlations, tests
│   ├── 04_Machine_Learning.ipynb            Models, tuning, ablation
│   ├── 05_Gen_AI_Asistente.ipynb            RAG over investment theses
│   └── 99_Documentacion_del_Sistema.ipynb   How the application works
│
├── data/
│   ├── screener_dataset.csv     Raw dataset with label
│   ├── dataset_limpio.csv       Ready for modeling
│   └── tableau_export.csv       For the dashboard
│
├── backend/     FastAPI API — 19 modules, 8,487 lines, 28 endpoints
├── frontend/    React + TypeScript + Vite — 23 components
├── reports/     70 generated investment theses (RAG corpus)
│
├── IVS_Presentacion_TFM.pptx    Defense presentation (16 slides, ~11 min)
└── presentacion/                Code that generates that presentation
    ├── build_deck.py                Builds the .pptx
    ├── snippets.py                  Code fragments for the screenshots
    └── make_charts.py               Redraws the charts in dark theme
```

### What's versioned and what isn't

| Versioned | Why |
|---|---|
| `backend/screener_cache.json` (2.5 MB) | The 08-04-2026 scan that notebooks 01–04 are built on. **Without it the project isn't reproducible**: Yahoo no longer returns those prices. |
| `reports/*.md` (70 reports) | Corpus for the notebook 05 RAG. |
| `data/*.csv` | The three pipeline datasets. |

| Ignored | Why |
|---|---|
| `portfolio.db` | Contains **real** positions and purchase prices. The SQL component is demonstrated through the schema and queries in `backend/portfolio_db.py`, which is versioned. |
| `reports/Trade_Memo_*.pdf` | Record real portfolio transactions. |
| `node_modules/`, regenerable caches | Rebuilt with `npm install` / a rescan. |

---

## Methodology

### Collection
Yahoo's screener endpoint returns ~250 rows per query and caps pagination.
`backend/universe_fetcher.py` **splits the market-cap range into sub-bands**
and recursively subdivides any that come back full. The union of the leaf
bands is the complete universe.

### Cleaning
| Step | Decision |
|---|---|
| Domain exclusion | Preferred shares, warrants, units, and funds excluded: not common equity |
| No label | Removed — the target variable can't be imputed |
| Null beta / WACC | **Sector** median, not global |
| Market outliers | **Kept** — they're the phenomenon under study |
| Impossible outliers | MoS clipped to [−200, 100] |
| Data leakage | Removed before modeling |

### Modeling
Three model families, 5-fold stratified cross-validation, `GridSearchCV` on
the best candidate, and **ablation by feature block** to identify the true
source of the signal. Scaling done inside a `Pipeline` to prevent leakage
across folds.

**Main metric:** ROC-AUC, since it's threshold-independent and directly
answers whether the model ranks better than chance.

---

## Challenges encountered

| Challenge | Solution |
|---|---|
| Yahoo caps queries at 250 rows | Recursive partitioning of the market-cap range |
| Aggressive rate-limiting (HTTP 429) | Batch downloads + batches of 150 + exponential backoff |
| ADRs with accounts in another currency | `fx_engine`: caught a ~87,000× valuation error |
| Unrealistic yfinance betas (0.03) | Guardrails: β ∈ [0.35, 2.50] |
| Explosive terminal value | Minimum WACC − g spread of 2% |
| **A single time cut** | Declared as a limitation; motivates the ablation |
| **yfinance < 1.0 fails silently** | Pinned `yfinance>=1.2` in `requirements.txt` |

---

## Installation and setup

```bash
pip install -r requirements.txt
```

> ⚠ **`yfinance` must be >= 1.0.** Versions 0.2.x break all downloads
> **silently**: prices freeze and the portfolio shows a false +6%.
> Check: `GET /api/health` returns the interpreter and version in use.

**Notebooks** (in order 01 → 05):
```bash
jupyter notebook notebooks/
```

**Web application:**
```bash
./START_WINDOWS.bat          # backend :8011 + frontend :3016
```

**Regenerating the presentation** (only if it needs to change):
```bash
cd presentacion && python make_charts.py && python build_deck.py
```
The code screenshots aren't actual screenshots: they're generated with
Pygments from `presentacion/snippets.py`. To change a fragment, edit it there
and re-run — don't hand-edit the `.pptx` if you're going to regenerate it
later.

---

## Generative AI component

**RAG** system over the 70 generated investment theses. Chunked by Markdown
sections, TF-IDF index, retrieval with ticker filtering. The prompt forces
the model to answer **only** with the retrieved context, to prevent it from
inventing figures.

Status: retrieval and prompt construction implemented and runnable without an
API key; the LLM call is ready and requires `ANTHROPIC_API_KEY`. Details in
`notebooks/05`.

---

## Limitations

1. **A single scan date** → cross-sectional cut, not a panel. Rules out
   temporal validation, which is the correct approach in finance. **This is
   the study's main limitation.**
2. **18-session window** → value investing operates on a scale of years;
   three weeks is essentially noise.
3. **No transaction costs** → a small quintile spread disappears once fees
   are applied.
4. **No trade log** in the portfolio → historical reconstruction only sees
   current positions.

## Future work

1. **Monthly scanning over 12+ months** — turns the cross-section into a
   panel and enables real temporal validation. The top priority improvement.
2. **Sector-neutralize** — isolates the valuation signal from the sector
   rotation contaminating the current result.
3. **Add Altman Z-Score and Piotroski F-Score as features** — the
   application already calculates them.
4. **Migrate the RAG to semantic embeddings** and expose it as a chat tab.

---

## Stack

**Backend:** FastAPI · Pydantic · SQLite · yfinance · pandas · NumPy · SciPy
**ML:** scikit-learn · matplotlib · seaborn
**Frontend:** React · TypeScript · Vite · Tailwind · Recharts

## References

- Schoenmaker & Schramade (2023), *Risk-Return Analysis* — CAPM and WACC
- Damodaran — Excess Return and AFFO models
- Altman (1968) — Z-Score · Piotroski (2000) — F-Score
- Cava (2006), *El Arte de Especular* — technical analysis
