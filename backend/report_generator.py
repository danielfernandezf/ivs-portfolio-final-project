"""
Report Generator — Investment Committee Documentation
======================================================
Generates two Markdown reports to disk inside /reports/:

  Factsheet_{TICKER}.md         — one-page summary (Bloomberg-style data sheet)
  Investment_Thesis_{TICKER}.md — full investment committee memo

Design principle: this module is purely I/O + formatting.
It receives a pre-computed snapshot dict and writes files.
No calculations are performed here.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    Paragraph, Spacer, Table, TableStyle, SimpleDocTemplate, KeepTogether
)


# Reports live one level above the backend package, in valuation-system/reports/
REPORTS_DIR = Path(__file__).parent.parent / "reports"


def _ensure_reports_dir() -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return REPORTS_DIR


def _fmt_large(n: float) -> str:
    abs_n = abs(n)
    if abs_n >= 1e12:
        return f"${n / 1e12:.2f}T"
    if abs_n >= 1e9:
        return f"${n / 1e9:.2f}B"
    if abs_n >= 1e6:
        return f"${n / 1e6:.2f}M"
    return f"${n:,.0f}"


def _pct(n: float) -> str:
    return f"{n * 100:.2f}%"


def _verdict_emoji(verdict: str) -> str:
    return {"STRONG BUY": "🟢", "HOLD/MONITOR": "🟡", "SELL/AVOID": "🔴"}.get(verdict, "⚪")


def generate_factsheet(
    snapshot: dict[str, Any],
    allocated_weight_pct: Optional[float] = None,
    is_manual_override: bool = False,
) -> Path:
    """
    Generate Factsheet_{TICKER}.md — a dense, Bloomberg-style one-pager.
    Returns the path to the written file.
    """
    reports_dir = _ensure_reports_dir()
    f = snapshot["fundamental"]
    t = snapshot.get("technical")
    v = f["verdict"]
    assum = f["assumptions"]
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M UTC")
    ticker = f["ticker"]

    verdict_emoji = _verdict_emoji(v["verdict"])

    lines: list[str] = [
        f"# {ticker} — Investment Factsheet",
        f"> Generated: {date_str}  |  Engine: Institutional Valuation System v1.0",
        "",
        "---",
        "",
        "## Company Overview",
        "",
        f"| Field | Value |",
        f"|-------|-------|",
        f"| **Company** | {f['company_name']} |",
        f"| **Ticker** | `{ticker}` |",
        f"| **Sector** | {f['sector']} |",
        f"| **Currency** | {f['currency']} |",
        "",
        "---",
        "",
        "## Market Data",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Current Price | **${f['current_price']:,.2f}** |",
        f"| Market Capitalisation | {_fmt_large(f['market_cap'])} |",
        f"| Enterprise Value | {_fmt_large(f['enterprise_value'])} |",
        f"| Total Debt | {_fmt_large(f['total_debt'])} |",
        f"| Cash & Equivalents | {_fmt_large(f['cash'])} |",
        f"| Net Debt | {_fmt_large(f['net_debt'])} |",
        f"| Shares Outstanding | {_fmt_large(f['shares_outstanding'])} |",
        "",
        "---",
        "",
        "## CAPM & WACC Decomposition",
        "",
        "> *Source: Risk-Return Analysis, Schoenmaker & Schramade (2023)*",
        "> *CAPM (Eq. 12.15): r_i = r_f + β × (E[r_MKT] − r_f)*",
        "",
        "| Component | Value |",
        "|-----------|-------|",
        f"| Risk-Free Rate (r_f) | {_pct(f['risk_free_rate'])} — 10Y US Treasury (^TNX) |",
        f"| Beta (β) | {f['beta']:.4f} |",
        f"| Equity Risk Premium | {_pct(f['market_risk_premium'])} — Historical avg (Table 12.1) |",
        f"| **Cost of Equity (CAPM)** | **{_pct(f['cost_of_equity'])}** |",
        f"| Cost of Debt (after-tax) | {_pct(f['cost_of_debt_aftertax'])} |",
        f"| Effective Tax Rate | {_pct(f['effective_tax_rate'])} |",
        f"| Equity Weight (E/V) | {f['equity_weight'] * 100:.1f}% |",
        f"| Debt Weight (D/V) | {f['debt_weight'] * 100:.1f}% |",
        f"| **WACC** | **{_pct(f['wacc'])}** |",
        "",
        "---",
        "",
        "## DCF Valuation Summary",
        "",
        "> *5-year FCF projection + Gordon Growth Terminal Value*",
        "",
        "| Scenario Parameter | Value |",
        "|--------------------|-------|",
        f"| Base FCF (T0) | {_fmt_large(f['base_fcf'])} |",
        f"| FCF Growth Rate (Y1–5) | {_pct(assum['revenue_growth_rate'])} |",
        f"| Terminal Growth Rate | {_pct(assum['terminal_growth_rate'])} |",
        f"| WACC (discount rate) | {_pct(f['wacc'])} |",
        "",
        "| Output | Value |",
        "|--------|-------|",
        f"| **Enterprise Value** | **{_fmt_large(f['enterprise_value'])}** |",
        f"| Net Debt | {_fmt_large(f['net_debt'])} |",
        f"| **Equity Value** | **{_fmt_large(f['equity_value'])}** |",
        f"| **Intrinsic Price / Share** | **${f['intrinsic_price_per_share']:,.2f}** |",
        f"| Current Price | ${f['current_price']:,.2f} |",
        f"| Upside / Downside | {f['upside_downside_pct'] * 100:+.1f}% |",
        "",
    ]

    # FCF projection table
    lines += [
        "### 5-Year FCF Projection",
        "",
        "| Year | Projected FCF | PV of FCF | Weight in EV |",
        "|------|--------------|-----------|--------------|",
    ]
    ev = f["enterprise_value"]
    for i, (fcf, pv) in enumerate(zip(f["projected_fcfs"], f["pv_fcfs"])):
        weight = pv / ev * 100 if ev > 0 else 0
        lines.append(f"| Y{i+1} | {_fmt_large(fcf)} | {_fmt_large(pv)} | {weight:.1f}% |")
    pv_tv_weight = f["pv_terminal_value"] / ev * 100 if ev > 0 else 0
    lines += [
        f"| Terminal | {_fmt_large(f['terminal_value'])} | {_fmt_large(f['pv_terminal_value'])} | {pv_tv_weight:.1f}% |",
        "",
    ]

    # Technical risk (if available)
    if t:
        lines += [
            "---",
            "",
            "## Technical Risk Indicators",
            "> *El Arte de Especular methodology (Cava, 2006) — isolated from fundamental DCF*",
            "",
            "| Indicator | Value |",
            "|-----------|-------|",
            f"| Trend | {t['trend_direction']} / {t['trend_strength']} |",
            f"| MACD Signal | {t['macd_signal']} |",
            f"| RSI (14) | {t['rsi_14']:.1f} — {t['rsi_signal']} |",
            f"| Annualised Volatility | {t['annualised_volatility'] * 100:.1f}% ({t['volatility_regime']}) |",
            f"| Composite Risk Score | {t['risk_score']:.0f}/100 — **{t['risk_label']}** |",
            "",
            "### Fibonacci Support / Resistance (52-Week Range)",
            "",
            "| Level | Price |",
            "|-------|-------|",
            f"| 23.6% | ${t['fib_236']:.2f} |",
            f"| 38.2% | ${t['fib_382']:.2f} |",
            f"| 50.0% | ${t['fib_500']:.2f} |",
            f"| 61.8% | ${t['fib_618']:.2f} |",
            f"| 78.6% | ${t['fib_786']:.2f} |",
            "",
        ]

    # Verdict banner
    # Portfolio allocation line (if available)
    if allocated_weight_pct is not None:
        origin = "Ajuste Manual del Gestor" if is_manual_override else "Recomendación del Sistema"
        lines += [
            "---",
            "",
            f"## Portfolio Allocation",
            "",
            f"| | |",
            f"|---|---|",
            f"| **Peso asignado en cartera** | **{allocated_weight_pct:.2f}%** |",
            f"| Límite institucional (máx.) | 10.00% |",
            f"| **Origen de la Operación** | **{origin}** |",
            "",
        ]

    lines += [
        "---",
        "",
        f"## Investment Committee Verdict: {verdict_emoji} {v['verdict']}",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Margin of Safety | **{v['margin_of_safety']:+.1f}%** |",
        f"| Expected Return | {v['expected_return'] * 100:+.1f}% |",
        f"| CAPM Hurdle Rate | {v['hurdle_rate'] * 100:.2f}% |",
        f"| Clears Hurdle | {'✅ Yes' if v['clears_hurdle'] else '❌ No'} |",
        "",
        f"**Primary Risk:** {v['key_risk']}",
        "",
        "---",
        f"*Factsheet generated by Institutional Valuation System — {date_str}*",
    ]

    out_path = reports_dir / f"Factsheet_{ticker}.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def generate_thesis(
    snapshot: dict[str, Any],
    allocated_weight_pct: Optional[float] = None,
    is_manual_override: bool = False,
) -> Path:
    """
    Generate Investment_Thesis_{TICKER}.md — full investment committee memo.
    Returns the path to the written file.
    """
    reports_dir = _ensure_reports_dir()
    f = snapshot["fundamental"]
    t = snapshot.get("technical")
    v = f["verdict"]
    assum = f["assumptions"]
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M UTC")
    ticker = f["ticker"]
    verdict_emoji = _verdict_emoji(v["verdict"])

    # Determine implied P/FCF multiple at current price
    base_fcf = f["base_fcf"]
    p_fcf = f["market_cap"] / base_fcf if base_fcf and base_fcf > 0 else None
    intrinsic_p_fcf = f["equity_value"] / base_fcf if base_fcf and base_fcf > 0 else None

    historical_fcfs = f.get("fcf_history", [])
    fcf_history_str = " → ".join([f"${v/1e9:.1f}B" for v in historical_fcfs]) if historical_fcfs else "N/A"

    lines: list[str] = [
        f"# Investment Thesis — {ticker}",
        f"## {f['company_name']}",
        "",
        f"> **Verdict: {verdict_emoji} {v['verdict']}**  ",
        f"> Date: {date_str}  ",
        f"> Analyst: IVS Quantitative Engine v1.0",
        "",
        "---",
        "",
        "## Executive Summary",
        "",
        v["rationale"],
        "",
        f"The intrinsic value per share derived from our 5-year DCF model is **${f['intrinsic_price_per_share']:,.2f}**, "
        f"versus a current market price of **${f['current_price']:,.2f}**, "
        f"implying a margin of safety of **{v['margin_of_safety']:+.1f}%**.",
        "",
        "---",
        "",
        "## 1. Business Overview",
        "",
        f"| | |",
        f"|---|---|",
        f"| **Company** | {f['company_name']} |",
        f"| **Ticker** | `{ticker}` |",
        f"| **Sector** | {f['sector']} |",
        f"| **Currency** | {f['currency']} |",
        f"| **Market Cap** | {_fmt_large(f['market_cap'])} |",
        "",
        f"{f['company_name']} operates in the **{f['sector']}** sector. "
        f"With {_fmt_large(f['shares_outstanding'])} shares outstanding and a market capitalisation of "
        f"{_fmt_large(f['market_cap'])}, this analysis applies a fundamental DCF framework "
        f"to assess whether the current market price adequately reflects the company's long-term "
        f"free cash flow generation capacity.",
        "",
        "---",
        "",
        "## 2. Detailed Valuation",
        "",
        "### 2.1 CAPM Cost of Equity",
        "",
        "> *Eq. 12.15 — Risk-Return Analysis, Schoenmaker & Schramade (2023)*",
        "",
        "```",
        f"r_e  = r_f + β × (r_m − r_f)",
        f"     = {f['risk_free_rate']*100:.3f}% + {f['beta']:.4f} × {f['market_risk_premium']*100:.2f}%",
        f"     = {f['cost_of_equity']*100:.3f}%",
        "```",
        "",
        f"The risk-free rate of **{_pct(f['risk_free_rate'])}** is sourced from the current 10-year "
        f"US Treasury yield (^TNX). The equity risk premium of **{_pct(f['market_risk_premium'])}** "
        f"represents the historical average excess return of equities over bills (Jorda et al., 2019 — "
        f"Table 12.1). With a beta of **{f['beta']:.4f}**, the CAPM cost of equity is **{_pct(f['cost_of_equity'])}**.",
        "",
        "### 2.2 WACC",
        "",
        "```",
        f"WACC = (E/V) × r_e  +  (D/V) × r_d × (1 − T)",
        f"     = {f['equity_weight']*100:.1f}% × {f['cost_of_equity']*100:.2f}%",
        f"     + {f['debt_weight']*100:.1f}% × {f['cost_of_debt_aftertax']*100:.2f}%",
        f"     = {f['wacc']*100:.3f}%",
        "```",
        "",
        f"The company's capital structure is **{f['equity_weight']*100:.0f}% equity / {f['debt_weight']*100:.0f}% debt** "
        f"(market-value weighted). The after-tax cost of debt is **{_pct(f['cost_of_debt_aftertax'])}**, "
        f"reflecting an effective tax rate of **{_pct(f['effective_tax_rate'])}**.",
        "",
        "### 2.3 Free Cash Flow History",
        "",
        f"Historical FCF trajectory: **{fcf_history_str}**",
        "",
        f"Base FCF (T0 anchor): **{_fmt_large(base_fcf)}**  ",
        f"5-year growth assumption: **{_pct(assum['revenue_growth_rate'])}** p.a. (calibrated at 70% of historical CAGR)  ",
        f"Terminal growth rate: **{_pct(assum['terminal_growth_rate'])}** (≤ long-run nominal GDP)",
        "",
        "### 2.4 DCF Bridge",
        "",
        "| Year | Projected FCF | PV of FCF |",
        "|------|--------------|-----------|",
    ]

    ev = f["enterprise_value"]
    for i, (fcf, pv) in enumerate(zip(f["projected_fcfs"], f["pv_fcfs"])):
        lines.append(f"| Y{i+1} | {_fmt_large(fcf)} | {_fmt_large(pv)} |")
    lines += [
        f"| Terminal Value | {_fmt_large(f['terminal_value'])} | {_fmt_large(f['pv_terminal_value'])} |",
        f"| **Enterprise Value** | | **{_fmt_large(ev)}** |",
        f"| Less: Net Debt | | ({_fmt_large(f['net_debt'])}) |",
        f"| **Equity Value** | | **{_fmt_large(f['equity_value'])}** |",
        f"| **Intrinsic Price / Share** | | **${f['intrinsic_price_per_share']:,.2f}** |",
        "",
    ]

    if p_fcf and intrinsic_p_fcf:
        lines += [
            "### 2.5 Implied Multiples",
            "",
            "| Multiple | Market Price | Intrinsic Value |",
            "|----------|-------------|-----------------|",
            f"| Price / FCF | {p_fcf:.1f}x | {intrinsic_p_fcf:.1f}x |",
            "",
        ]

    lines += [
        "---",
        "",
        "## 3. Risk Analysis",
        "",
        "### 3.1 Primary Risk",
        "",
        f"{v['key_risk']}",
        "",
        "### 3.2 Sensitivity Analysis",
        "",
        "The table below shows intrinsic price sensitivity to WACC and growth rate changes:",
        "",
        "| WACC \\ Growth | -5% | Base | +5% |",
        "|---------------|-----|------|-----|",
    ]

    # Build a mini sensitivity matrix
    from valuation_engine import ValuationEngine
    _eng = ValuationEngine()
    base_wacc = f["wacc"]
    base_growth = assum["revenue_growth_rate"]
    base_tg = assum["terminal_growth_rate"]
    net_debt_val = f["net_debt"]
    shares = f["shares_outstanding"]

    for wacc_delta in [-0.01, 0.0, +0.01]:
        w = base_wacc + wacc_delta
        row_label = f"WACC {w*100:.1f}%"
        cells = []
        for g_delta in [-0.05, 0.0, 0.05]:
            g = base_growth + g_delta
            tg = min(base_tg, w - 0.001)
            projected = _eng.project_fcfs(base_fcf, g, 5)
            pvs = _eng.present_value(projected, w)
            tv = _eng.terminal_value(projected[-1], tg, w)
            pv_tv = tv / (1 + w) ** 5
            eq_val = sum(pvs) + pv_tv - net_debt_val
            price = eq_val / shares if shares > 0 else 0
            cells.append(f"${price:,.2f}")
        lines.append(f"| {row_label} | {cells[0]} | {cells[1]} | {cells[2]} |")

    lines += [
        "",
        "### 3.3 Key Risk Factors",
        "",
        f"1. **Valuation risk**: Terminal value represents "
        f"{f['pv_terminal_value'] / ev * 100 if ev > 0 else 0:.0f}% of enterprise value — "
        f"small changes in the terminal growth assumption have outsized impact.",
        f"2. **Market risk**: Beta of {f['beta']:.2f} implies the stock moves approximately "
        f"{f['beta']*100:.0f}% for every 100bps move in the broad market.",
        f"3. **Leverage risk**: Net debt of {_fmt_large(f['net_debt'])} represents "
        f"{f['net_debt']/f['market_cap']*100:.0f}% of market cap." if f['market_cap'] > 0 else
        "3. **Leverage risk**: Debt load requires monitoring against earnings power.",
        f"4. **Estimation risk**: FCF projections assume constant growth of {_pct(assum['revenue_growth_rate'])} "
        f"— structural business model changes are not captured by this model.",
        "",
    ]

    # ── Phase 5: Survival Analysis (Z-Score + F-Score) ────────────────────
    quality_data = snapshot.get("quality")
    if quality_data:
        qz = quality_data.get("altman", {})
        qp = quality_data.get("piotroski", {})
        qb = quality_data.get("benchmark", {})
        ql = quality_data.get("liquidity", {})

        # Altman Z-Score section
        z_zone = qz.get("zone", "N/A")
        z_score = qz.get("z_score", 0.0)
        z_icon = {"SAFE": "🟢", "GREY": "🟡", "DISTRESS": "🔴", "N/A": "⚪"}.get(z_zone, "⚪")
        z_interp = {
            "SAFE": "Zona Segura (Z > 2.99): empresa financieramente sólida.",
            "GREY": "Zona Gris (1.81 ≤ Z ≤ 2.99): monitorear evolución — riesgo moderado.",
            "DISTRESS": "ZONA DE PELIGRO (Z < 1.81): riesgo elevado de insolvencia. VEREDICTO INVALIDADO.",
            "N/A": qz.get("note", "No aplicable para este sector."),
        }.get(z_zone, "")

        lines += [
            "---",
            "",
            "## 3b. Análisis de Supervivencia y Calidad Financiera",
            "",
            "> *Filtros institucionales para Small & Mid Cap — Phase 5 Quality Engine*",
            "",
            f"### {z_icon} Altman Z-Score: **{z_score:.2f}** ({z_zone})",
            "",
        ]

        if z_zone not in ("N/A",):
            lines += [
                "| Componente | Fórmula | Valor | Peso |",
                "|------------|---------|-------|------|",
                f"| X1 — Capital de Trabajo / Activos Totales | WC/TA | {qz.get('x1_wc_to_assets', 0):.4f} | 1.2× |",
                f"| X2 — Ganancias Retenidas / Activos Totales | RE/TA | {qz.get('x2_re_to_assets', 0):.4f} | 1.4× |",
                f"| X3 — EBIT / Activos Totales | EBIT/TA | {qz.get('x3_ebit_to_assets', 0):.4f} | 3.3× |",
                f"| X4 — Cap. Bursátil / Pasivos Totales | MCap/TL | {qz.get('x4_mktcap_to_liab', 0):.4f} | 0.6× |",
                f"| X5 — Ventas / Activos Totales | Rev/TA | {qz.get('x5_rev_to_assets', 0):.4f} | 1.0× |",
                f"| **Z-Score** | 1.2×X1+1.4×X2+3.3×X3+0.6×X4+1.0×X5 | **{z_score:.3f}** | — |",
                "",
            ]

        lines.append(f"*Interpretación: {z_interp}*")
        lines.append("")

        # Piotroski F-Score section
        p_score = qp.get("score", 0)
        p_label = "FUERTE (7–9)" if p_score >= 7 else "MODERADO (4–6)" if p_score >= 4 else "DÉBIL (0–3)"
        p_icon = "🟢" if p_score >= 7 else "🟡" if p_score >= 4 else "🔴"
        p_override_note = "  \n> ⚠ **F-Score < 5: VEREDICTO INVALIDADO automáticamente.**" if qp.get("triggers_override") else ""

        FSIG = [
            ("F1", "ROA > 0 (rentabilidad positiva)", "f1_roa_positive"),
            ("F2", "Flujo de Caja Operativo > 0", "f2_ocf_positive"),
            ("F3", "ROA mejorando interanualmente", "f3_roa_improving"),
            ("F4", "Calidad del Accrual (OCF/TA > ROA)", "f4_accruals_quality"),
            ("F5", "Ratio de Deuda a LP mejorando", "f5_leverage_improving"),
            ("F6", "Ratio corriente mejorando", "f6_liquidity_improving"),
            ("F7", "Sin dilución accionarial", "f7_no_dilution"),
            ("F8", "Margen bruto mejorando", "f8_gross_margin_improving"),
            ("F9", "Rotación de activos mejorando", "f9_asset_turnover_improving"),
        ]

        lines += [
            f"### {p_icon} Piotroski F-Score: **{p_score}/9** ({p_label}){p_override_note}",
            "",
            f"*(Señales computadas: {qp.get('signals_computed', 0)}/9)*",
            "",
            "| # | Señal | Resultado |",
            "|---|-------|-----------|",
        ]
        for code, desc, key in FSIG:
            val = qp.get(key, False)
            lines.append(f"| {code} | {desc} | {'✅ Pasa' if val else '❌ Falla'} |")

        lines.append("")

        # Benchmark comparison
        if qb.get("pe_ratio") or qb.get("ev_ebitda"):
            lines += [
                "### Comparación vs. Sector",
                "",
                "| Múltiplo | Empresa | Media Sector | Diferencia |",
                "|----------|---------|--------------|------------|",
            ]
            if qb.get("pe_ratio"):
                diff_pe = qb.get("pe_vs_sector_pct")
                diff_str = f"{diff_pe:+.1f}%" if diff_pe is not None else "—"
                lines.append(f"| P/E Ratio | {qb['pe_ratio']:.1f}× | {qb['sector_pe']:.1f}× | {diff_str} |")
            if qb.get("ev_ebitda"):
                diff_ev = qb.get("ev_ebitda_vs_sector_pct")
                diff_str = f"{diff_ev:+.1f}%" if diff_ev is not None else "—"
                lines.append(f"| EV/EBITDA | {qb['ev_ebitda']:.1f}× | {qb['sector_ev_ebitda']:.1f}× | {diff_str} |")
            lines.append("")

        # Liquidity alert
        if ql.get("alert"):
            lines += [
                "### ⚠ Alerta de Liquidez",
                "",
                f"> {ql['alert']}",
                "",
                f"*(Volumen diario medio: {ql.get('avg_volume_10d', 0):,} acciones | "
                f"Posición máxima: {ql.get('max_shares_in_position', 0):,} acciones | "
                f"Impacto: {ql.get('volume_impact_pct', 0):.1f}% del volumen)*",
                "",
            ]

    if t:
        lines += [
            "---",
            "",
            "## 4. Technical Risk Context",
            "",
            "> *Supplementary analysis — El Arte de Especular, José Luis Cava (2006)*  ",
            "> *This section is INFORMATIONAL ONLY and does not modify the fundamental DCF verdict.*",
            "",
            f"- **Trend**: {t['trend_direction']} / {t['trend_strength']} — "
            f"Price is {t['price_vs_ma50']*100:+.1f}% vs 50-day MA, {t['price_vs_ma200']*100:+.1f}% vs 200-day MA",
            f"- **Momentum (MACD)**: {t['macd_signal']} signal",
            f"- **RSI(14)**: {t['rsi_14']:.1f} — {t['rsi_signal']}",
            f"- **Volatility**: {t['annualised_volatility']*100:.1f}% annualised ({t['volatility_regime']} regime)",
            f"- **Composite Risk Score**: {t['risk_score']:.0f}/100 — **{t['risk_label']}**",
            "",
            "#### 3-Scenario Probability Analysis",
            "",
            "| Scenario | Probability | 12M Price Target |",
            "|----------|-------------|------------------|",
            f"| Bull | {t['bull_probability']*100:.0f}% | ${t['bull_price_target']:.2f} |",
            f"| Base | {t['base_probability']*100:.0f}% | ${t['base_price_target']:.2f} |",
            f"| Bear | {t['bear_probability']*100:.0f}% | ${t['bear_price_target']:.2f} |",
            f"| **Probability-Weighted** | 100% | **${t['probability_weighted_price']:.2f}** |",
            "",
        ]

    # Allocated weight section
    if allocated_weight_pct is not None:
        lines += [
            "---",
            "",
            "## 4b. Portfolio Allocation Decision",
            "",
            f"| Parámetro | Valor |",
            f"|-----------|-------|",
            f"| **Peso asignado en cartera** | **{allocated_weight_pct:.2f}%** |",
            f"| Límite institucional máximo | 10.00% por posición |",
            (f"| Estado | {'⚠ Límite de diversificación institucional alcanzado' if allocated_weight_pct >= 9.99 else '✅ Dentro del límite'} |"),
            f"| **Origen de la Operación** | **{'Ajuste Manual del Gestor' if is_manual_override else 'Recomendación del Sistema'}** |",
            "",
        ]

    lines += [
        "---",
        "",
        "## 5. Investment Committee Conclusion",
        "",
        f"### {verdict_emoji} Verdict: {v['verdict']}",
        "",
        f"| Decision Metric | Value | Threshold | Pass |",
        f"|-----------------|-------|-----------|------|",
        f"| Margin of Safety | {v['margin_of_safety']:+.1f}% | > 20% | {'✅' if v['margin_of_safety'] > 20 else '❌'} |",
        f"| Expected Return | {v['expected_return']*100:+.1f}% | > {v['hurdle_rate']*100:.2f}% (CAPM) | {'✅' if v['clears_hurdle'] else '❌'} |",
        "",
        v["rationale"],
        "",
        "---",
        f"*Investment thesis generated by Institutional Valuation System — {date_str}*  ",
        "*Mathematical framework: Risk-Return Analysis © Schoenmaker & Schramade (2023) | "
        "Technical framework: El Arte de Especular © Cava (2006)*",
    ]

    out_path = reports_dir / f"Investment_Thesis_{ticker}.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def generate_both(
    snapshot: dict[str, Any],
    allocated_weight_pct: Optional[float] = None,
    is_manual_override: bool = False,
) -> dict[str, str]:
    """Generate both reports and return their absolute paths."""
    factsheet_path = generate_factsheet(snapshot, allocated_weight_pct=allocated_weight_pct, is_manual_override=is_manual_override)
    thesis_path = generate_thesis(snapshot, allocated_weight_pct=allocated_weight_pct, is_manual_override=is_manual_override)
    return {
        "factsheet": str(factsheet_path.resolve()),
        "thesis": str(thesis_path.resolve()),
        "reports_dir": str(REPORTS_DIR.resolve()),
    }


# =============================================================================
# PDF Trade Memorandum — professional one-pager generated automatically
# on every BUY / SELL decision.
# =============================================================================

# Palette — institutional look (dark accent, monochrome body)
_COLOR_ACCENT   = colors.HexColor("#0c4a6e")  # deep navy
_COLOR_BUY      = colors.HexColor("#15803d")  # green
_COLOR_SELL     = colors.HexColor("#b91c1c")  # red
_COLOR_TEXT     = colors.HexColor("#111827")
_COLOR_MUTED    = colors.HexColor("#6b7280")
_COLOR_BORDER   = colors.HexColor("#d1d5db")
_COLOR_BG_ALT   = colors.HexColor("#f3f4f6")


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=16, textColor=_COLOR_ACCENT, spaceAfter=2, alignment=0,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", parent=base["Normal"], fontName="Helvetica",
            fontSize=9, textColor=_COLOR_MUTED, spaceAfter=12,
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=10, textColor=_COLOR_ACCENT, spaceBefore=10, spaceAfter=4,
            letterSpacing=1,
        ),
        "body": ParagraphStyle(
            "body", parent=base["Normal"], fontName="Helvetica",
            fontSize=9.5, textColor=_COLOR_TEXT, leading=13,
        ),
        "body_small": ParagraphStyle(
            "body_small", parent=base["Normal"], fontName="Helvetica",
            fontSize=8.5, textColor=_COLOR_MUTED, leading=11,
        ),
        "italic": ParagraphStyle(
            "italic", parent=base["Normal"], fontName="Helvetica-Oblique",
            fontSize=9, textColor=_COLOR_TEXT, leading=12,
        ),
    }


def _kv_table(rows: list[tuple[str, str]], col_widths=(5.5 * cm, 10.5 * cm)) -> Table:
    """Render a 2-column key/value table with subtle alt-row shading."""
    data = [[k, v] for k, v in rows]
    tbl = Table(data, colWidths=col_widths, hAlign="LEFT")
    style = [
        ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 9),
        ("FONT", (1, 0), (1, -1), "Helvetica", 9),
        ("TEXTCOLOR", (0, 0), (0, -1), _COLOR_MUTED),
        ("TEXTCOLOR", (1, 0), (1, -1), _COLOR_TEXT),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, _COLOR_BORDER),
    ]
    for i in range(len(data)):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), _COLOR_BG_ALT))
    tbl.setStyle(TableStyle(style))
    return tbl


def _banner(action: str, ticker: str, date_str: str) -> Table:
    color = _COLOR_BUY if action == "BUY" else _COLOR_SELL
    label = "BUY DECISION" if action == "BUY" else "SELL DECISION"
    data = [[
        f"{label}",
        f"{ticker}",
        f"{date_str}",
    ]]
    tbl = Table(data, colWidths=(6 * cm, 6 * cm, 4 * cm), hAlign="LEFT")
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), color),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONT", (0, 0), (0, 0), "Helvetica-Bold", 12),
        ("FONT", (1, 0), (1, 0), "Helvetica-Bold", 14),
        ("FONT", (2, 0), (2, 0), "Helvetica", 10),
        ("ALIGN", (0, 0), (0, 0), "LEFT"),
        ("ALIGN", (1, 0), (1, 0), "CENTER"),
        ("ALIGN", (2, 0), (2, 0), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return tbl


def generate_trade_memo_pdf(
    snapshot: dict[str, Any],
    action: str,                               # "BUY" or "SELL"
    trade: dict[str, Any],                     # shares, price, notional, weight_pct, etc.
    allocated_weight_pct: Optional[float] = None,
    is_manual_override: bool = False,
) -> Path:
    """
    Generate a professional one-page Trade Memorandum PDF documenting the
    rationale for a BUY or SELL decision.

    trade dict expected keys (all optional except shares/price):
        shares, price, notional, proceeds, realised_pnl, realised_pnl_pct,
        origin (e.g. 'System recommendation' / 'Manual override')
    """
    reports_dir = _ensure_reports_dir()
    f = snapshot["fundamental"]
    v = f["verdict"]
    ticker = f["ticker"]
    company = f.get("company_name", ticker)
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M UTC")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    action = action.upper()
    assert action in ("BUY", "SELL"), "action must be BUY or SELL"

    out_path = reports_dir / f"Trade_Memo_{action}_{ticker}_{stamp}.pdf"
    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title=f"Trade Memo — {action} {ticker}",
        author="Institutional Valuation System",
    )
    S = _styles()
    story: list = []

    # Header
    story.append(Paragraph("INVESTMENT COMMITTEE — TRADE MEMORANDUM", S["title"]))
    story.append(Paragraph(
        f"{company} &nbsp;•&nbsp; Sector: {f.get('sector', 'N/A')} &nbsp;•&nbsp; "
        f"Generated {date_str} &nbsp;•&nbsp; IVS v1.0",
        S["subtitle"],
    ))
    story.append(_banner(action, ticker, datetime.now().strftime("%Y-%m-%d")))
    story.append(Spacer(1, 10))

    # Trade details
    story.append(Paragraph("TRADE DETAILS", S["h2"]))
    trade_rows: list[tuple[str, str]] = []
    if "shares" in trade and "price" in trade:
        trade_rows.append(("Shares executed", f"{trade['shares']:,.4f}"))
        trade_rows.append(("Execution price", f"${trade['price']:,.2f}"))
    if trade.get("notional") is not None:
        trade_rows.append(("Notional", f"${trade['notional']:,.2f}"))
    if trade.get("proceeds") is not None:
        trade_rows.append(("Proceeds", f"${trade['proceeds']:,.2f}"))
    if trade.get("realised_pnl") is not None:
        pnl = trade["realised_pnl"]
        pnl_pct = trade.get("realised_pnl_pct")
        pnl_str = f"${pnl:+,.2f}" + (f"  ({pnl_pct:+.2f}%)" if pnl_pct is not None else "")
        trade_rows.append(("Realised P&L", pnl_str))
    if allocated_weight_pct is not None:
        trade_rows.append(("Portfolio weight", f"{allocated_weight_pct:.2f}%"))
    trade_rows.append((
        "Origin",
        trade.get("origin") or ("Manual override" if is_manual_override else "System recommendation"),
    ))
    story.append(_kv_table(trade_rows))

    # Valuation summary
    story.append(Paragraph("VALUATION SUMMARY", S["h2"]))
    mos = v.get("margin_of_safety", 0.0)
    verdict_txt = v.get("verdict", "N/A")
    story.append(_kv_table([
        ("Current market price", f"${f['current_price']:,.2f}"),
        ("Intrinsic value (DCF)", f"${f['intrinsic_price_per_share']:,.2f}"),
        ("Margin of safety", f"{mos:+.1f}%"),
        ("Verdict", verdict_txt),
        ("Expected return",
            f"{v.get('expected_return', 0) * 100:+.1f}%"),
        ("CAPM hurdle rate",
            f"{v.get('hurdle_rate', 0) * 100:.2f}%  "
            f"({'clears' if v.get('clears_hurdle') else 'does NOT clear'})"),
    ]))

    # Rationale
    story.append(Paragraph("RATIONALE", S["h2"]))
    story.append(Paragraph(v.get("rationale", "—"), S["body"]))

    # CAPM/WACC decomposition
    story.append(Paragraph("CAPM / WACC DECOMPOSITION", S["h2"]))
    story.append(_kv_table([
        ("Risk-free rate (10Y UST)", _pct(f.get("risk_free_rate", 0))),
        ("Beta (β)", f"{f.get('beta', 0):.4f}"),
        ("Equity risk premium", _pct(f.get("market_risk_premium", 0))),
        ("Cost of equity (CAPM)", _pct(f.get("cost_of_equity", 0))),
        ("After-tax cost of debt", _pct(f.get("cost_of_debt_aftertax", 0))),
        ("Capital structure (E/D)",
            f"{f.get('equity_weight', 0) * 100:.0f}% / {f.get('debt_weight', 0) * 100:.0f}%"),
        ("WACC (discount rate)", _pct(f.get("wacc", 0))),
    ]))

    # Key risk
    story.append(Paragraph("KEY RISK", S["h2"]))
    story.append(Paragraph(v.get("key_risk", "—"), S["body"]))

    # Footer
    story.append(Spacer(1, 14))
    story.append(Paragraph(
        "<i>Institutional Valuation System — paper trading portfolio. "
        "DCF &amp; CAPM framework: Risk-Return Analysis (Schoenmaker &amp; Schramade, 2023). "
        "This memorandum is a decision record, not investment advice.</i>",
        S["body_small"],
    ))

    doc.build(story)
    return out_path
