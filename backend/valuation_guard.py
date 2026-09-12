"""
Valuation Guard — Control de plausibilidad y grado de confianza
================================================================
Última línea de defensa antes de que un número llegue al ranking.

Los modelos ya están corregidos, pero ningún modelo es más fiable que los datos
que recibe: un ejercicio mal imputado en Yahoo, unas cuentas en una divisa
exótica sin tipo de cambio o un histórico de un solo año pueden seguir
produciendo un resultado absurdo. La regla rectora es:

    Un valor intrínseco 50 veces superior al precio NO es una oportunidad de
    inversión: es un error de datos. El mercado no deja un billete de 100 € en
    el suelo durante años.

Por eso el sistema deja de tratar "MoS altísimo" como sinónimo de "gran
oportunidad" y lo trata como lo que estadísticamente es: una señal de alarma.
El resultado se descarta o se degrada, y además se acompaña de una puntuación
de confianza que permite ordenar el ranking por convicción y no sólo por
descuento aparente.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# Por encima de este múltiplo el resultado se descarta: no es creíble bajo
# ninguna hipótesis razonable y casi siempre delata datos corruptos.
REJECT_RATIO = 8.0
# A partir de aquí el resultado se conserva pero se marca como sospechoso y
# nunca puede emitir una recomendación de compra.
SUSPECT_RATIO = 4.0
# Suelo simétrico: un valor intrínseco por debajo del 2 % del precio también
# apunta a datos rotos, no a una sobrevaloración de 50 veces.
REJECT_RATIO_LOW = 0.02


@dataclass
class GuardResult:
    accepted: bool
    confidence: float                 # 0-100
    confidence_label: str             # ALTA | MEDIA | BAJA
    rejection_reason: str | None = None
    flags: list[str] = field(default_factory=list)
    capped_mos_pct: float | None = None


def _label(score: float) -> str:
    if score >= 70:
        return "ALTA"
    if score >= 45:
        return "MEDIA"
    return "BAJA"


def evaluate(
    *,
    intrinsic_price: float,
    current_price: float,
    model: str,
    fcf_years: int = 0,
    terminal_value_share: float | None = None,
    fx_converted: bool = False,
    fx_supported: bool = True,
    warnings: list[str] | None = None,
    beta_defaulted: bool = False,
) -> GuardResult:
    """
    Valida el resultado y calcula su grado de confianza.

    `fcf_years` es el número de ejercicios de flujo disponibles (o de ROE, según
    el modelo). `terminal_value_share` es la fracción del valor que aporta la
    perpetuidad.
    """
    warnings = list(warnings or [])
    flags: list[str] = []

    # --- Validez aritmética ---
    if not math.isfinite(intrinsic_price) or intrinsic_price <= 0:
        return GuardResult(False, 0.0, "BAJA",
                           rejection_reason="El modelo no produce un valor intrínseco positivo")
    if not math.isfinite(current_price) or current_price <= 0:
        return GuardResult(False, 0.0, "BAJA",
                           rejection_reason="Precio de mercado no disponible")

    ratio = intrinsic_price / current_price

    if ratio > REJECT_RATIO:
        return GuardResult(
            False, 0.0, "BAJA",
            rejection_reason=(
                f"Valor intrínseco {ratio:.0f} veces el precio de mercado: "
                "incompatible con un mercado líquido, se descarta por datos no fiables"
            ),
        )
    if ratio < REJECT_RATIO_LOW:
        return GuardResult(
            False, 0.0, "BAJA",
            rejection_reason=(
                f"Valor intrínseco equivalente al {ratio:.1%} del precio: "
                "magnitud implausible, se descarta por datos no fiables"
            ),
        )

    # --- Puntuación de confianza ---
    score = 100.0

    if ratio > SUSPECT_RATIO:
        score -= 35
        flags.append(
            f"Descuento extraordinario ({ratio:.1f}x el precio): verificar las cuentas "
            "antes de actuar — a menudo indica un dato erróneo, no una oportunidad"
        )

    if fcf_years <= 1:
        score -= 25
        flags.append("Un único ejercicio de histórico: el crecimiento no es calibrable")
    elif fcf_years == 2:
        score -= 12
        flags.append("Sólo dos ejercicios de histórico: calibración frágil")

    if terminal_value_share is not None:
        if terminal_value_share > 0.90:
            score -= 20
            flags.append(
                f"El {terminal_value_share:.0%} del valor procede de la perpetuidad: "
                "la valoración es casi enteramente una hipótesis terminal"
            )
        elif terminal_value_share > 0.80:
            score -= 8

    if fx_converted:
        if not fx_supported:
            score -= 30
            flags.append("Conversión de divisa sin tipo fiable: magnitud no garantizada")
        else:
            score -= 5
            flags.append("Cuentas convertidas desde otra divisa: sujeto a riesgo de tipo de cambio")

    if beta_defaulted:
        score -= 8
        flags.append("Beta no disponible: se asume 1,00 para el coste del capital")

    # Cada aviso del modelo resta, con tope para no anular la puntuación
    score -= min(len(warnings) * 4, 16)

    score = max(0.0, min(100.0, score))

    return GuardResult(
        accepted=True,
        confidence=round(score, 1),
        confidence_label=_label(score),
        flags=flags,
    )
