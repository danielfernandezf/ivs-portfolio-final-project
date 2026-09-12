"""
Generates a professional PDF documenting the full valuation methodology used
by the Institutional Valuation System.

Output: reports/Metodologia_Valoracion.pdf
Run:    python backend/methodology_pdf.py
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    KeepTogether,
)


REPORTS_DIR = Path(__file__).parent.parent / "reports"
OUTPUT_PATH = REPORTS_DIR / "Metodologia_Valoracion.pdf"


NAVY = colors.HexColor("#0B2545")
ACCENT = colors.HexColor("#C9A961")
SLATE = colors.HexColor("#3E5C76")
LIGHT = colors.HexColor("#F4F1EA")
RULE = colors.HexColor("#1B3A57")


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "Title", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=24, leading=28, textColor=NAVY, alignment=TA_CENTER,
            spaceAfter=6,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle", parent=base["Normal"], fontName="Helvetica-Oblique",
            fontSize=12, leading=16, textColor=SLATE, alignment=TA_CENTER,
            spaceAfter=24,
        ),
        "h1": ParagraphStyle(
            "H1", parent=base["Heading1"], fontName="Helvetica-Bold",
            fontSize=16, leading=20, textColor=NAVY,
            spaceBefore=18, spaceAfter=8, borderPadding=4,
        ),
        "h2": ParagraphStyle(
            "H2", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=12.5, leading=16, textColor=RULE,
            spaceBefore=12, spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "Body", parent=base["BodyText"], fontName="Helvetica",
            fontSize=10.5, leading=15, textColor=colors.black,
            alignment=TA_JUSTIFY, spaceAfter=6,
        ),
        "formula": ParagraphStyle(
            "Formula", parent=base["Normal"], fontName="Helvetica-Oblique",
            fontSize=11, leading=15, textColor=NAVY,
            backColor=LIGHT, borderPadding=8, leftIndent=12, rightIndent=12,
            spaceBefore=4, spaceAfter=8, alignment=TA_LEFT,
        ),
        "callout": ParagraphStyle(
            "Callout", parent=base["Normal"], fontName="Helvetica",
            fontSize=10, leading=14, textColor=colors.black,
            backColor=colors.HexColor("#FAF6E9"), borderPadding=8,
            leftIndent=6, rightIndent=6, spaceBefore=4, spaceAfter=8,
            alignment=TA_JUSTIFY,
        ),
        "footer": ParagraphStyle(
            "Footer", parent=base["Normal"], fontName="Helvetica-Oblique",
            fontSize=8.5, leading=11, textColor=SLATE, alignment=TA_CENTER,
        ),
        "toc_entry": ParagraphStyle(
            "TOC", parent=base["Normal"], fontName="Helvetica",
            fontSize=11, leading=18, textColor=colors.black,
        ),
    }


def _header_footer(canvas, doc):
    canvas.saveState()
    page_num = canvas.getPageNumber()

    # Footer band
    canvas.setFillColor(NAVY)
    canvas.rect(0, 0, A4[0], 1.4 * cm, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica", 8.5)
    canvas.drawString(2 * cm, 0.5 * cm,
                      "Institutional Valuation System  ·  Metodología de Valoración")
    canvas.drawRightString(A4[0] - 2 * cm, 0.5 * cm, f"Página {page_num}")

    # Top accent rule (skip on cover)
    if page_num > 1:
        canvas.setStrokeColor(ACCENT)
        canvas.setLineWidth(1.2)
        canvas.line(2 * cm, A4[1] - 1.4 * cm, A4[0] - 2 * cm, A4[1] - 1.4 * cm)
        canvas.setFillColor(SLATE)
        canvas.setFont("Helvetica-Oblique", 8.5)
        canvas.drawString(2 * cm, A4[1] - 1.05 * cm,
                          "Metodología de Valoración de Empresas")
        canvas.drawRightString(A4[0] - 2 * cm, A4[1] - 1.05 * cm,
                               "DCF · CAPM · WACC · Quality · Risk")

    canvas.restoreState()


def _hr(width_cm: float = 17, color=ACCENT, thickness: float = 1.0) -> Table:
    t = Table([[""]], colWidths=[width_cm * cm], rowHeights=[1])
    t.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), thickness, color),
    ]))
    return t


def _kv_table(rows: list[tuple[str, str]]) -> Table:
    t = Table(rows, colWidths=[6.5 * cm, 10.5 * cm])
    t.setStyle(TableStyle([
        ("FONT",       (0, 0), (0, -1), "Helvetica-Bold", 10),
        ("FONT",       (1, 0), (1, -1), "Helvetica", 10),
        ("TEXTCOLOR",  (0, 0), (0, -1), NAVY),
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, LIGHT]),
        ("VALIGN",     (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING",   (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
        ("LINEBELOW",  (0, 0), (-1, -1), 0.25, colors.HexColor("#D8D2C2")),
    ]))
    return t


def build() -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    S = _styles()

    doc = SimpleDocTemplate(
        str(OUTPUT_PATH),
        pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
        title="Metodología de Valoración — Institutional Valuation System",
        author="Institutional Valuation System",
    )

    story: list = []

    # =================== COVER ===================
    story.append(Spacer(1, 4 * cm))
    story.append(Paragraph("Metodología de Valoración de Empresas", S["title"]))
    story.append(Paragraph(
        "Marco analítico institucional · DCF · CAPM · WACC · Calidad · Riesgo",
        S["subtitle"]))
    story.append(Spacer(1, 0.5 * cm))
    story.append(_hr(width_cm=10, color=ACCENT, thickness=1.4))
    story.append(Spacer(1, 0.4 * cm))

    cover_meta = _kv_table([
        ("Sistema",          "Institutional Valuation System"),
        ("Versión",          "1.0"),
        ("Marco teórico",    "Risk-Return Analysis (Schoenmaker & Schramade, 2023)"),
        ("Complemento",      "El Arte de Especular (J. L. Cava, 2006) — módulo de riesgo"),
        ("Filtros calidad",  "Altman Z-Score (1968) · Piotroski F-Score (2000)"),
        ("Fecha emisión",    datetime.now().strftime("%d de %B de %Y")),
    ])
    story.append(cover_meta)
    story.append(Spacer(1, 2 * cm))
    story.append(Paragraph(
        "Este documento describe de forma exhaustiva la totalidad de los inputs, "
        "fórmulas, supuestos y reglas de decisión empleados por el sistema para "
        "determinar el valor intrínseco de una compañía cotizada y emitir un "
        "veredicto de inversión.",
        S["body"]))

    story.append(PageBreak())

    # =================== TOC ===================
    story.append(Paragraph("Índice", S["h1"]))
    story.append(_hr())
    toc_items = [
        "1.  Filosofía y arquitectura analítica",
        "2.  Coste del Equity — Modelo CAPM",
        "3.  Coste medio ponderado de capital — WACC",
        "4.  Cash flow libre y calibración de crecimiento",
        "5.  Proyección DCF y valor terminal (Gordon)",
        "6.  Valor de la empresa y precio intrínseco",
        "7.  Margen de Seguridad y Veredicto del Comité",
        "8.  Filtros de calidad — Altman Z-Score",
        "9.  Filtros de calidad — Piotroski F-Score",
        "10. Múltiplos sectoriales (P/E y EV/EBITDA)",
        "11. Análisis de riesgo técnico y volatilidad",
        "12. Simulación Monte Carlo del DCF",
        "13. Dimensionamiento de la posición",
        "14. Screener de universo completo — construcción y ranking",
        "15. Medición de rendimiento — TWR, benchmark S&amp;P 500 y alpha",
        "16. Reglas de override y garantías de aislamiento",
        "17. Limitaciones y advertencias",
    ]
    for item in toc_items:
        story.append(Paragraph(item, S["toc_entry"]))
    story.append(PageBreak())

    # =================== 1. PHILOSOPHY ===================
    story.append(Paragraph("1. Filosofía y arquitectura analítica", S["h1"]))
    story.append(_hr())
    story.append(Paragraph(
        "El sistema separa de forma estricta tres dominios analíticos que jamás "
        "se contaminan entre sí: el <b>análisis fundamental</b> (DCF puro), los "
        "<b>filtros de calidad y supervivencia</b> (Altman, Piotroski, múltiplos "
        "sectoriales) y el <b>análisis de riesgo técnico y probabilístico</b> "
        "(tendencia, momentum, volatilidad, Monte Carlo). Esta segregación "
        "garantiza que el precio justo derivado del flujo de caja descontado no "
        "queda jamás distorsionado por sentimiento de mercado ni indicadores "
        "técnicos.",
        S["body"]))
    story.append(Paragraph(
        "El flujo de decisión es secuencial: primero se calcula el valor "
        "intrínseco, después se aplican filtros de calidad que pueden vetar la "
        "posición, y por último se sobreponen capas de riesgo y dimensionamiento.",
        S["body"]))

    arch = Table([
        ["Capa", "Módulo", "Output"],
        ["1. Valoración fundamental",  "valuation_engine.py",  "Precio intrínseco, MoS, veredicto"],
        ["2. Calidad y supervivencia", "quality_engine.py",    "Z-Score, F-Score, múltiplos sectoriales"],
        ["3. Riesgo técnico",          "risk_analysis.py",     "Tendencia, MACD, Fibonacci, σ"],
        ["4. Probabilístico",          "montecarlo_engine.py", "Percentiles P10/P50/P90, P(infravalorada)"],
        ["5. Dimensionamiento",        "position_sizing.py",   "% del capital recomendado"],
    ], colWidths=[4.2 * cm, 4.8 * cm, 8 * cm])
    arch.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONT",       (0, 0), (-1, 0), "Helvetica-Bold", 10),
        ("FONT",       (0, 1), (-1, -1), "Helvetica", 9.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING",   (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CCCCCC")),
    ]))
    story.append(arch)

    # =================== 2. CAPM ===================
    story.append(Paragraph("2. Coste del Equity — Modelo CAPM", S["h1"]))
    story.append(_hr())
    story.append(Paragraph(
        "El coste de los recursos propios representa la rentabilidad mínima "
        "exigida por el accionista para compensar el riesgo sistemático de la "
        "compañía. Se calcula con el <b>Capital Asset Pricing Model</b> "
        "(Sharpe, 1964; Eq. 12.15 de Schoenmaker & Schramade, 2023):",
        S["body"]))
    story.append(Paragraph(
        "r<sub>e</sub>  =  r<sub>f</sub>  +  β<sub>i</sub> × (E[r<sub>MKT</sub>] − r<sub>f</sub>)",
        S["formula"]))

    story.append(Paragraph("Componentes del modelo", S["h2"]))
    story.append(_kv_table([
        ("r_f — Tipo libre de riesgo",
         "Rentabilidad del bono soberano a 10 años (referencia macro)."),
        ("β — Beta del valor",
         "Sensibilidad histórica frente al índice de referencia. β > 1 amplifica el mercado, β < 1 lo suaviza."),
        ("ERP — Prima de riesgo de mercado",
         "Diferencia E[r_MKT] − r_f. Default 5,5 % (media histórica, Tabla 12.1)."),
        ("r_e — Coste del equity",
         "Output del modelo. Sirve como tasa-objetivo (hurdle rate) en el veredicto."),
    ]))

    story.append(Paragraph("Interpretación práctica", S["h2"]))
    story.append(Paragraph(
        "Si una acción tiene β = 1,3, r<sub>f</sub> = 4,2 % y ERP = 5,5 %, el "
        "coste del equity será 4,2 % + 1,3 × 5,5 % = <b>11,35 %</b>. La acción "
        "debe ofrecer al menos esa rentabilidad esperada para que la inversión "
        "sea económicamente racional.",
        S["callout"]))

    # =================== 3. WACC ===================
    story.append(Paragraph("3. Coste medio ponderado de capital — WACC", S["h1"]))
    story.append(_hr())
    story.append(Paragraph(
        "La empresa no se financia exclusivamente con equity: la deuda fiscalmente "
        "deducible abarata el coste de capital. El WACC pondera ambas fuentes:",
        S["body"]))
    story.append(Paragraph(
        "WACC  =  (E/V) × r<sub>e</sub>  +  (D/V) × r<sub>d</sub> × (1 − T)",
        S["formula"]))

    story.append(_kv_table([
        ("E — Valor de mercado del equity",     "Market cap (precio × acciones)."),
        ("D — Deuda total a valor contable",    "Total Debt del balance."),
        ("V — Capital total",                   "V = E + D."),
        ("r_d — Coste de la deuda (pre-tax)",   "Tipo medio de la deuda viva."),
        ("T — Tipo impositivo efectivo",        "Effective tax rate del último ejercicio."),
        ("r_d × (1 − T) — Coste fiscal",        "Refleja el escudo fiscal de los intereses."),
    ]))

    story.append(Paragraph("Normalización del WACC (guardrails)", S["h2"]))
    story.append(Paragraph(
        "El CAPM tiende a sobreestimar el retorno exigido en negocios con foso "
        "monopolístico (Big Tech) y a infravalorarlo en negocios estables de "
        "baja beta. El sistema aplica dos correcciones:",
        S["body"]))
    story.append(_kv_table([
        ("Big Tech (AAPL, MSFT, GOOGL, META, AMZN, NVDA, TSLA)",
         "WACC tope ≤ 8,5 %. El CAPM crudo se conserva para diagnóstico, pero la tasa de descuento efectiva se limita."),
        ("Compañías estables (β < 1,2)",
         "WACC acotado al rango [7 %, 12 %] para evitar resultados degenerados con betas bajas o erróneas."),
        ("WACC manual (override)",
         "El usuario puede forzar un WACC personalizado desde el panel; el motor lo respeta sin guardrails."),
    ]))

    # =================== 4. FCF ===================
    story.append(Paragraph("4. Cash flow libre y calibración de crecimiento", S["h1"]))
    story.append(_hr())
    story.append(Paragraph(
        "El motor proyecta <b>Free Cash Flow</b> (FCF) histórico tomado de los "
        "tres a cinco últimos ejercicios disponibles en yfinance.",
        S["body"]))

    story.append(Paragraph("Selección del FCF base (año 0)", S["h2"]))
    story.append(Paragraph(
        "• Si todos los años son positivos → se usa el último FCF reportado.<br/>"
        "• Si existe al menos un año negativo → se aplica <b>mean-reversion</b>: "
        "la media de los tres últimos años para amortiguar valores atípicos y "
        "no contaminar la proyección con un T-0 distorsionado.",
        S["body"]))

    story.append(Paragraph("Calibración del crecimiento (CAGR histórico)", S["h2"]))
    story.append(Paragraph(
        "CAGR  =  (FCF<sub>n</sub> / FCF<sub>0</sub>)<sup>1/(n−1)</sup>  −  1",
        S["formula"]))
    story.append(Paragraph(
        "El crecimiento queda acotado al intervalo <b>[−30 %, +50 %]</b> para "
        "evitar que rachas excepcionales (post-COVID, ciclos energéticos) "
        "extrapolen a perpetuidad. Si el FCF inicial es negativo, se utiliza "
        "la media aritmética de las tasas anuales en lugar del CAGR.",
        S["body"]))
    story.append(Paragraph(
        "El usuario puede sobreescribir la tasa de crecimiento desde los sliders "
        "del frontend para construir escenarios alternativos (bull / base / bear).",
        S["callout"]))

    # =================== 5. DCF & TV ===================
    story.append(Paragraph("5. Proyección DCF y valor terminal (Gordon)", S["h1"]))
    story.append(_hr())
    story.append(Paragraph(
        "El valor de la empresa se obtiene descontando todos los flujos futuros "
        "al WACC. La fórmula completa es:",
        S["body"]))
    story.append(Paragraph(
        "EV  =  Σ<sub>t=1..n</sub>  FCF<sub>t</sub> / (1+WACC)<sup>t</sup>  "
        "+  TV / (1+WACC)<sup>n</sup>",
        S["formula"]))

    story.append(Paragraph("Horizonte explícito (años 1 – 5)", S["h2"]))
    story.append(Paragraph(
        "El motor proyecta cinco años de FCF a la tasa de crecimiento calibrada "
        "y descuenta cada uno individualmente al WACC.",
        S["body"]))

    story.append(Paragraph("Valor terminal — modelo de Gordon", S["h2"]))
    story.append(Paragraph(
        "TV  =  FCF<sub>n</sub> × (1 + g)  /  (WACC − g)",
        S["formula"]))
    story.append(Paragraph(
        "donde <b>g</b> es la tasa de crecimiento a perpetuidad (terminal "
        "growth), por defecto cercana al crecimiento del PIB nominal (2 – 3 %). "
        "El motor exige <b>WACC > g</b>; si la diferencia es inferior a 0,1 % "
        "se aplica un suelo de seguridad para evitar divisiones casi por cero.",
        S["body"]))
    story.append(Paragraph(
        "En negocios tecnológicos el valor terminal suele representar más del "
        "70 % del EV total — el sistema señala esta dependencia como riesgo "
        "principal en su narrativa de veredicto.",
        S["callout"]))

    # =================== 6. EV → Price ===================
    story.append(Paragraph("6. Valor de la empresa y precio intrínseco", S["h1"]))
    story.append(_hr())
    story.append(Paragraph(
        "Una vez obtenido el Enterprise Value, se traduce a valor para el "
        "accionista restando la deuda neta y dividiendo por las acciones en "
        "circulación:",
        S["body"]))
    story.append(Paragraph(
        "Deuda Neta  =  Total Debt − Cash &amp; Equivalentes<br/>"
        "Equity Value  =  EV − Deuda Neta<br/>"
        "Precio Intrínseco  =  Equity Value / Acciones en circulación",
        S["formula"]))
    story.append(Paragraph(
        "Las compañías con caja neta positiva (Apple, Microsoft) ven aumentado "
        "su equity value por encima del EV; las muy apalancadas (utilities, "
        "telcos) sufren la dilución contraria.",
        S["body"]))

    # =================== 7. MoS & Verdict ===================
    story.append(Paragraph("7. Margen de Seguridad y Veredicto del Comité", S["h1"]))
    story.append(_hr())
    story.append(Paragraph(
        "Inspirado en Benjamin Graham (<i>The Intelligent Investor</i>), el "
        "<b>Margen de Seguridad</b> (Margin of Safety, MoS) protege frente al "
        "error de estimación inherente a cualquier modelo:",
        S["body"]))
    story.append(Paragraph(
        "MoS (%)  =  (Precio Intrínseco − Precio Mercado) / Precio Intrínseco × 100",
        S["formula"]))
    story.append(Paragraph(
        "Rentabilidad esperada  =  (Precio Intrínseco − Precio Mercado) / Precio Mercado",
        S["formula"]))

    story.append(Paragraph("Regla de decisión", S["h2"]))
    rule_tbl = Table([
        ["Veredicto", "Condición", "Lectura"],
        ["STRONG BUY",   "MoS > 20 % y r_esperada > r_e (CAPM)",
         "Asimetría positiva: descuento amplio y retorno > hurdle rate."],
        ["HOLD / MONITOR", "0 % ≤ MoS ≤ 20 %",
         "Precio justo; iniciar sólo en debilidad o si supera el hurdle."],
        ["SELL / AVOID", "MoS < 0 %",
         "El mercado descuenta hipótesis no presentes en el histórico de FCF."],
    ], colWidths=[3.2 * cm, 6 * cm, 7.8 * cm])
    rule_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONT",       (0, 0), (-1, 0), "Helvetica-Bold", 10),
        ("FONT",       (0, 1), (-1, -1), "Helvetica", 9.5),
        ("FONT",       (0, 1), (0, -1), "Helvetica-Bold", 9.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",(0, 0), (-1, -1), 6),
        ("RIGHTPADDING",(0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CCCCCC")),
    ]))
    story.append(rule_tbl)

    story.append(Paragraph("Riesgo clave (narrativa sectorial)", S["h2"]))
    story.append(Paragraph(
        "El motor identifica automáticamente el riesgo dominante en función del "
        "perfil de la empresa:",
        S["body"]))
    story.append(_kv_table([
        ("MoS negativo",
         "Sobrevaloración significativa — no hay margen de error."),
        ("β > 1,5",
         "Riesgo sistemático elevado; el precio cae más que el mercado en drawdowns."),
        ("Deuda neta / MCap > 0,5x",
         "Apalancamiento elevado; sensible a subidas de tipos y compresión de beneficios."),
        ("Tech / Software",
         "El valor terminal domina; la disrupción competitiva es la amenaza principal."),
        ("Energía / Materiales",
         "FCF cíclico; el terminal growth puede sobrestimar el potencial a largo plazo."),
        ("Resto",
         "Sensibilidad al WACC: +100 pb reduce el valor intrínseco ~10–15 %."),
    ]))

    # =================== 8. Altman ===================
    story.append(Paragraph("8. Filtros de calidad — Altman Z-Score", S["h1"]))
    story.append(_hr())
    story.append(Paragraph(
        "Modelo Altman (1968) para compañías cotizadas. Identifica probabilidad "
        "de quiebra a dos años mediante un score lineal de cinco ratios:",
        S["body"]))
    story.append(Paragraph(
        "Z  =  1,2·X<sub>1</sub>  +  1,4·X<sub>2</sub>  +  3,3·X<sub>3</sub>  "
        "+  0,6·X<sub>4</sub>  +  1,0·X<sub>5</sub>",
        S["formula"]))
    story.append(_kv_table([
        ("X₁",  "Working Capital / Total Assets — liquidez."),
        ("X₂",  "Retained Earnings / Total Assets — historial de generación de beneficios."),
        ("X₃",  "EBIT / Total Assets — rentabilidad operativa."),
        ("X₄",  "Market Cap / Total Liabilities — solvencia bursátil."),
        ("X₅",  "Revenue / Total Assets — eficiencia del activo."),
    ]))

    story.append(Paragraph("Zonas de clasificación", S["h2"]))
    story.append(_kv_table([
        ("Z > 2,99",        "SAFE — alejado del riesgo de quiebra."),
        ("1,81 ≤ Z ≤ 2,99", "GREY — zona de incertidumbre; vigilar."),
        ("Z < 1,81",        "DISTRESS — alta probabilidad de quiebra. Override → SELL/AVOID."),
    ]))

    # =================== 9. Piotroski ===================
    story.append(Paragraph("9. Filtros de calidad — Piotroski F-Score", S["h1"]))
    story.append(_hr())
    story.append(Paragraph(
        "Piotroski (2000) — score binario (0/1) sobre nueve señales fundamentales "
        "agrupadas en rentabilidad, apalancamiento y eficiencia operativa:",
        S["body"]))
    pio_tbl = Table([
        ["Bloque", "Señal", "Punto si…"],
        ["Rentabilidad", "ROA positivo",                  "Net Income > 0"],
        ["",             "CFO positivo",                  "Operating Cash Flow > 0"],
        ["",             "ROA al alza",                   "ROA actual > ROA año anterior"],
        ["",             "Calidad de beneficios",         "CFO > Net Income"],
        ["Apalancamiento","Deuda LP al alza? — penaliza", "Long-term Debt actual < anterior"],
        ["",             "Liquidez al alza",              "Current Ratio actual > anterior"],
        ["",             "Sin nuevas emisiones",          "Shares Outstanding no aumentan"],
        ["Eficiencia",   "Margen bruto al alza",          "Gross Margin actual > anterior"],
        ["",             "Rotación del activo al alza",   "Asset Turnover actual > anterior"],
    ], colWidths=[3.4 * cm, 5.4 * cm, 8.2 * cm])
    pio_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONT",       (0, 0), (-1, 0), "Helvetica-Bold", 9.5),
        ("FONT",       (0, 1), (-1, -1), "Helvetica", 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",(0, 0), (-1, -1), 5),
        ("RIGHTPADDING",(0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CCCCCC")),
    ]))
    story.append(pio_tbl)
    story.append(Spacer(1, 6))
    story.append(_kv_table([
        ("F-Score 7 – 9", "STRONG — calidad fundamental sólida."),
        ("F-Score 4 – 6", "AVERAGE — calidad aceptable."),
        ("F-Score 0 – 3", "WEAK — override automático → SELL/AVOID (< 5 puntos)."),
    ]))

    # =================== 10. Multiples ===================
    story.append(Paragraph("10. Múltiplos sectoriales (P/E y EV/EBITDA)", S["h1"]))
    story.append(_hr())
    story.append(Paragraph(
        "Como contraste relativo al DCF, el motor compara los múltiplos de la "
        "empresa con la mediana sectorial S&P 500 (aproximación 2024). Si la "
        "compañía cotiza con prima superior al 30 % respecto a su sector, se "
        "marca como sobrevalorada por múltiplos.",
        S["body"]))
    mtbl = Table([
        ["Sector", "P/E mediano", "EV/EBITDA mediano"],
        ["Technology",             "28,5", "22,1"],
        ["Healthcare",             "22,3", "17,8"],
        ["Financial Services",     "13,2", "10,5"],
        ["Consumer Cyclical",      "19,4", "12,8"],
        ["Consumer Defensive",     "21,8", "14,6"],
        ["Energy",                 "11,8",  "6,9"],
        ["Industrials",            "22,1", "14,3"],
        ["Basic Materials",        "15,2",  "9,1"],
        ["Real Estate",            "35,8", "19,2"],
        ["Utilities",              "18,6", "11,4"],
        ["Communication Services", "16,8", "10,9"],
    ], colWidths=[7 * cm, 5 * cm, 5 * cm])
    mtbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONT",       (0, 0), (-1, 0), "Helvetica-Bold", 10),
        ("FONT",       (0, 1), (-1, -1), "Helvetica", 9.5),
        ("ALIGN",      (1, 0), (-1, -1), "CENTER"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CCCCCC")),
    ]))
    story.append(mtbl)

    # =================== 11. Risk ===================
    story.append(Paragraph("11. Análisis de riesgo técnico y volatilidad", S["h1"]))
    story.append(_hr())
    story.append(Paragraph(
        "Módulo inspirado en <i>El Arte de Especular</i> (J. L. Cava). No "
        "modifica nunca el valor intrínseco; aporta un panel paralelo que ayuda "
        "a temporizar la entrada.",
        S["body"]))
    story.append(_kv_table([
        ("Tendencia",
         "Precio vs. MA50 y MA200. BULLISH si precio > ambas medias; BEARISH si por debajo de ambas; NEUTRAL en transición."),
        ("Fuerza",
         "STRONG / MODERATE / WEAK según separación porcentual respecto a las medias."),
        ("MACD",
         "Cruce de la línea MACD (EMA12 − EMA26) sobre su signal line (EMA9). BUY / SELL / NEUTRAL."),
        ("Volatilidad anualizada",
         "σ histórica = stdev(retornos diarios) × √252. Régimen: LOW < 20 %, NORMAL 20–35 %, HIGH 35–55 %, EXTREME > 55 %."),
        ("Niveles de Fibonacci",
         "Retracements 23,6 % / 38,2 % / 50 % / 61,8 % / 78,6 % sobre el rango 52 semanas. Soportes y resistencias dinámicos."),
    ]))

    # =================== 12. Monte Carlo ===================
    story.append(Paragraph("12. Simulación Monte Carlo del DCF", S["h1"]))
    story.append(_hr())
    story.append(Paragraph(
        "El DCF determinista entrega un único valor justo. El motor Monte Carlo "
        "ejecuta <b>10 000 iteraciones</b> vectorizadas en NumPy variando los "
        "dos inputs más sensibles:",
        S["body"]))
    story.append(Paragraph(
        "g<sub>i</sub>  ~  N(μ<sub>g</sub>, σ<sub>g</sub>)<br/>"
        "WACC<sub>i</sub>  ~  N(μ<sub>WACC</sub>, σ<sub>WACC</sub>)<br/>"
        "σ<sub>WACC</sub>  =  β × σ<sub>mkt</sub> × ERP",
        S["formula"]))
    story.append(Paragraph(
        "donde σ<sub>g</sub> es la desviación típica de las tasas anuales "
        "históricas de FCF y σ<sub>WACC</sub> propaga la incertidumbre de la "
        "beta. Los muestreos se acotan a g ∈ [−30 %, +60 %] y "
        "WACC ∈ [max(g+0,5 %, 3 %), 25 %].",
        S["body"]))
    story.append(Paragraph("Outputs probabilísticos", S["h2"]))
    story.append(_kv_table([
        ("Percentiles",                "P10, P25, P50 (mediana), P75, P90 del valor intrínseco."),
        ("Bandas de escenario",        "P10 = bear, P50 = base, P90 = bull."),
        ("P(infravalorada)",           "Probabilidad de que el valor intrínseco supere el precio actual."),
        ("Histograma (60 bins)",       "Distribución completa para la gráfica de campana."),
    ]))

    # =================== 13. Sizing ===================
    story.append(Paragraph("13. Dimensionamiento de la posición", S["h1"]))
    story.append(_hr())
    story.append(Paragraph(
        "El veredicto BUY no implica peso uniforme: el sistema calcula el peso "
        "óptimo en cartera combinando convicción (MoS) y riesgo sistemático (β):",
        S["body"]))
    story.append(Paragraph(
        "raw  =  min(MoS / 100, 1) × (1 / max(β, 0,3)) × 0,15<br/>"
        "peso  =  min(raw, 10 %)",
        S["formula"]))
    sz = Table([
        ["MoS", "β", "Raw weight", "Recomendado"],
        ["100 %", "0,5", "30,0 %", "10,0 % (capped)"],
        [" 75 %", "0,8", "14,1 %", "10,0 % (capped)"],
        [" 50 %", "1,0", " 7,5 %", " 7,5 %"],
        [" 30 %", "1,5", " 3,0 %", " 3,0 %"],
        [" 20 %", "2,0", " 1,5 %", " 1,5 %"],
    ], colWidths=[3 * cm, 2.5 * cm, 4 * cm, 4 * cm])
    sz.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONT",       (0, 0), (-1, 0), "Helvetica-Bold", 10),
        ("FONT",       (0, 1), (-1, -1), "Helvetica", 9.5),
        ("ALIGN",      (0, 0), (-1, -1), "CENTER"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CCCCCC")),
    ]))
    story.append(sz)
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "<b>Cap institucional</b>: ningún valor podrá superar el 10 % del "
        "patrimonio total (regla clásica de diversificación). Adicionalmente, "
        "se verifica que una orden equivalente al 10 % del capital no exceda "
        "el 5 % del volumen medio de 10 días — si lo hace, se emite alerta de "
        "iliquidez (riesgo de impacto en precio).",
        S["callout"]))

    # =================== 14. Screener ===================
    story.append(Paragraph("14. Screener de universo completo — construcción y ranking", S["h1"]))
    story.append(_hr())
    story.append(Paragraph(
        "El módulo Screener extiende la valoración individual a un universo "
        "completo de compañías, aplicando el mismo motor DCF a cada nombre y "
        "ordenando por Margen de Seguridad. El universo no es una lista "
        "estática: se construye dinámicamente desde el screener de Yahoo "
        "Finance con los siguientes filtros institucionales:",
        S["body"]))
    story.append(_kv_table([
        ("Capitalización", "Small y Mid Cap: 300 M$ – 10.000 M$ (banda donde la "
         "ineficiencia de precio y la cobertura reducida de analistas generan "
         "más oportunidades de descuento sobre valor intrínseco)."),
        ("Mercados", "NASDAQ (NMS), NYSE (NYQ) y NYSE American (ASE) — se "
         "excluyen OTC y pink sheets por calidad de datos y liquidez."),
        ("Tamaño del universo", "≈ 2.300 compañías, refrescadas bajo demanda "
         "mediante particionado por bandas de market cap (la API limita cada "
         "consulta, por lo que el rango se subdivide hasta cubrir el total)."),
        ("Ranking", "Orden descendente por MoS calculado con el DCF completo "
         "(secciones 2–6), tras aplicar los filtros de calidad (Altman Z, "
         "Piotroski F) de las secciones 8–9."),
    ]))
    story.append(Paragraph(
        "<b>Robustez operativa</b>: el escaneo completo es reanudable (guarda "
        "progreso incremental) y aplica <i>exponential backoff</i> ante "
        "límites de peticiones del proveedor de datos, de modo que un barrido "
        "del universo puede completarse en varias sesiones sin perder trabajo.",
        S["callout"]))

    # =================== 15. Performance / TWR / Benchmark ===================
    story.append(Paragraph("15. Medición de rendimiento — TWR, benchmark S&amp;P 500 y alpha", S["h1"]))
    story.append(_hr())
    story.append(Paragraph(
        "Medir la rentabilidad de una cartera con aportaciones periódicas de "
        "capital exige eliminar el efecto de esos flujos: de lo contrario, "
        "cada ingreso de efectivo se contabilizaría erróneamente como "
        "“ganancia”. El estándar institucional (GIPS) es el "
        "<b>Time-Weighted Return (TWR)</b>, que encadena las rentabilidades "
        "de cada sub-período neteando las aportaciones:",
        S["body"]))
    story.append(Paragraph(
        "r<sub>t</sub>  =  (V<sub>t</sub> − C<sub>t</sub>) / V<sub>t−1</sub><br/>"
        "TWR  =  [ ∏<sub>t</sub> r<sub>t</sub> ] − 1",
        S["formula"]))
    story.append(Paragraph(
        "donde V<sub>t</sub> es el valor total de la cartera al cierre del día "
        "t (efectivo + posiciones a precio de mercado), C<sub>t</sub> la "
        "aportación de capital recibida ese día y V<sub>t−1</sub> el valor al "
        "cierre anterior. El primer sub-período parte del capital inicial.",
        S["body"]))
    story.append(Paragraph(
        "<b>Reconstrucción del historial</b>: el valor diario no se apoya en "
        "capturas manuales, sino que se reconstruye desde la primera compra "
        "con precios de cierre históricos reales: para cada día de mercado, "
        "efectivo(t) = capital acumulado − coste de las posiciones activas, y "
        "valor(t) = efectivo(t) + Σ acciones<sub>i</sub> × cierre<sub>i</sub>(t). "
        "Los días sin cotización de un valor se cubren con forward-fill del "
        "último cierre disponible.",
        S["body"]))
    story.append(Paragraph(
        "<b>Benchmark y alpha</b>: la cartera se compara contra el S&amp;P 500 "
        "(ETF SPY) desde la fecha de la primera compra. Ambas series se "
        "indexan a la misma base (el capital inicial) para hacerlas "
        "directamente comparables:",
        S["body"]))
    story.append(Paragraph(
        "SPY<sub>idx</sub>(t)  =  base × precio_SPY(t) / precio_SPY(t<sub>0</sub>)<br/>"
        "alpha  =  retorno_cartera  −  retorno_SPY",
        S["formula"]))
    story.append(Paragraph(
        "Un alpha positivo sostenido indica que la selección por Margen de "
        "Seguridad genera valor sobre la gestión pasiva; un alpha negativo "
        "señalaría que el inversor habría obtenido más comprando el índice. "
        "Esta comparación honesta contra el coste de oportunidad es parte "
        "integral de la disciplina del sistema.",
        S["callout"]))

    # =================== 16. Overrides ===================
    story.append(Paragraph("16. Reglas de override y garantías de aislamiento", S["h1"]))
    story.append(_hr())
    story.append(_kv_table([
        ("Z-Score en DISTRESS",
         "El veredicto se fuerza a SELL/AVOID incluso si el DCF muestra MoS alto."),
        ("F-Score < 5",
         "El veredicto se fuerza a SELL/AVOID. La calidad fundamental pesa más que el descuento."),
        ("Aislamiento DCF ↔ Técnico",
         "valuation_engine.py no importa nada de risk_analysis.py. El precio justo nunca queda contaminado por momentum o sentiment."),
        ("Aislamiento DCF ↔ Monte Carlo",
         "El Monte Carlo consume el motor determinista pero no modifica su salida; se exhibe en paralelo."),
        ("Trazabilidad",
         "Cada fórmula referencia su origen en Schoenmaker & Schramade (2023) o en Graham / Altman / Piotroski."),
    ]))

    # =================== 17. Limitations ===================
    story.append(Paragraph("17. Limitaciones y advertencias", S["h1"]))
    story.append(_hr())
    story.append(Paragraph(
        "1. <b>El DCF es altamente sensible al WACC y al terminal growth</b>. "
        "Variaciones de ±100 pb en WACC pueden mover el valor intrínseco un "
        "10 – 20 %.<br/><br/>"
        "2. <b>Datos de yfinance</b>: pueden contener reclasificaciones o "
        "huecos. El motor aplica mean-reversion para mitigar, pero no sustituye "
        "una verificación cruzada con 10-K / 20-F.<br/><br/>"
        "3. <b>Beta histórica</b>: refleja sensibilidad pasada, no futura. En "
        "transiciones de modelo de negocio el CAPM puede desviarse "
        "significativamente.<br/><br/>"
        "4. <b>Múltiplos sectoriales</b>: las medianas son una aproximación "
        "2024; en regímenes de tipos cambiantes deberían recalibrarse "
        "anualmente.<br/><br/>"
        "5. <b>Monte Carlo</b>: asume normalidad de g y WACC. Eventos de cola "
        "(crisis, intervención regulatoria) quedan fuera del modelo.<br/><br/>"
        "6. <b>Este documento y la aplicación tienen finalidad analítica</b>. "
        "No constituyen asesoramiento financiero personalizado.",
        S["body"]))

    story.append(Spacer(1, 1 * cm))
    story.append(_hr(width_cm=10, color=ACCENT, thickness=1.2))
    story.append(Spacer(1, 0.4 * cm))
    story.append(Paragraph(
        "Institutional Valuation System · Metodología v2.0 · "
        f"Generado {datetime.now().strftime('%Y-%m-%d')}",
        S["footer"]))

    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    return OUTPUT_PATH


if __name__ == "__main__":
    path = build()
    print(f"PDF generado: {path}")
