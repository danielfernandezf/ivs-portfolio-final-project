# Institutional Valuation System (IVS)

**¿Puede un modelo de valoración fundamental automatizado identificar acciones que baten al mercado?**

Proyecto final del bootcamp de Data Science & Machine Learning. Combina un sistema
de valoración de renta variable en producción (FastAPI + React) con un estudio
empírico que contrasta si su señal predice rentabilidad futura.

---

## El problema de negocio

El sector financiero dedica enormes recursos al análisis fundamental. Si un modelo
de descuento de flujos ejecutado sistemáticamente sobre miles de empresas tuviera
capacidad predictiva, sería explotable. Y si **no** la tiene, eso también es un
resultado: evidencia a favor de la hipótesis de mercados eficientes.

Este proyecto construye ese modelo, lo aplica a **2 305 empresas** y contrasta
empíricamente su capacidad predictiva.

## Los datos

| Fuente | Contenido | Volumen |
|---|---|---|
| Yahoo Finance (endpoint de screener) | Universo small/mid cap USA, 300 M$–10 B$ | 2 305 tickers |
| Yahoo Finance (`yfinance`) | Estados financieros y precios | 1 437 valoradas |
| Motor propio de valoración | DCF · Exceso de Retorno · AFFO | 1 437 filas × 32 features |
| Precios posteriores al escaneo | Variable objetivo | 1 421 etiquetadas |

**Variable objetivo:** `beats_market` — ¿superó la acción al S&P 500 entre la fecha
del escaneo (2026-08-04) y el cierre siguiente (2026-08-26, 18 sesiones)?
Tasa base: **45,1 %**.

---

## Resultados principales

### 1 · El margen de seguridad no predice linealmente

Correlación de Pearson entre margen de seguridad y exceso de rentabilidad:
**−0,009**. Los deciles no muestran progresión monótona.

### 2 · Pero los veredictos sí separan rentabilidades

| Veredicto | n | Exceso mediano |
|---|---|---|
| STRONG BUY | 298 | **+0,55 %** |
| SELL/AVOID | 986 | **−1,06 %** |

Mann-Whitney U: **p = 0,003**, diferencia significativa. Se usa una prueba no
paramétrica porque la distribución de rentabilidades tiene colas gordas.

Los resultados 1 y 2 no se contradicen: si hay señal, **no es lineal ni monótona**,
vive en los extremos de la distribución.

### 3 · El modelo alcanza AUC 0,71 — y ahí está la trampa

| Modelo | ROC-AUC (test) |
|---|---|
| Base (clase mayoritaria) | 0,500 |
| Regresión Logística | **0,722** |
| Random Forest | 0,698 |
| Gradient Boosting (ajustado) | 0,707 |

Quintiles de probabilidad ordenados de forma monótona, con un diferencial de
**+5,6 puntos porcentuales** entre el superior y el inferior.

### 4 · La ablación desmonta el resultado anterior

| Bloque de variables | AUC |
|---|---|
| Todas | 0,688 |
| **Solo sector y modelo** | **0,620** |
| Solo precio y tamaño | 0,598 |
| **Solo valoración (la tesis)** | **0,578** |

**El sector, por sí solo, predice mejor que toda la tesis de valoración junta.**

Con una **única ventana temporal**, la variable «sector» no mide una propiedad
estable del negocio: memoriza *qué sectores subieron en esas tres semanas*. La
validación cruzada no puede detectarlo porque todas las particiones comparten el
mismo régimen de mercado.

> ### Conclusión
>
> El margen de seguridad por DCF tiene capacidad predictiva **débil pero no nula**
> a 18 sesiones (AUC 0,578 aislado). Lo que **no** puede afirmarse es que el modelo
> completo prediga: la mayor parte de su AUC 0,71 procede de un artefacto de corte
> transversal.
>
> Detectar ese artefacto es el resultado del proyecto. Presentar el 0,71 sin la
> ablación habría sido un error grave.

---

## Estructura del repositorio

```
├── README.md                    ← este archivo
├── GUIA_DEL_PROYECTO.md         ← qué es cada archivo y estado de cada requisito
├── requirements.txt
│
├── notebooks/
│   ├── 01_Recoleccion_de_Datos.ipynb        Problema, universo, etiqueta
│   ├── 02_Preparacion_y_Limpieza.ipynb      Nulos, outliers, encoding, features
│   ├── 03_Analisis_Exploratorio_EDA.ipynb   Distribuciones, correlaciones, tests
│   ├── 04_Machine_Learning.ipynb            Modelos, ajuste, ablación
│   ├── 05_Gen_AI_Asistente.ipynb            RAG sobre tesis de inversión
│   └── 99_Documentacion_del_Sistema.ipynb   Cómo funciona la aplicación
│
├── data/
│   ├── screener_dataset.csv     Dataset crudo con etiqueta
│   ├── dataset_limpio.csv       Listo para modelar
│   └── tableau_export.csv       Para el dashboard
│
├── backend/     API FastAPI — 19 módulos, 8 487 líneas, 28 endpoints
├── frontend/    React + TypeScript + Vite — 23 componentes
├── reports/     70 tesis de inversión generadas (corpus del RAG)
│
├── IVS_Presentacion_TFM.pptx    Presentación de defensa (16 diapositivas, ~11 min)
└── presentacion/                Código que genera esa presentación
    ├── build_deck.py                Monta el .pptx
    ├── snippets.py                  Fragmentos de código de las capturas
    └── make_charts.py               Redibuja los gráficos en tema oscuro
```

### Qué se versiona y qué no

| Se versiona | Por qué |
|---|---|
| `backend/screener_cache.json` (2,5 MB) | Es el escaneo del 04-08-2026 del que salen los notebooks 01–04. **Sin él el proyecto no es reproducible**: Yahoo ya no devuelve aquellos precios. |
| `reports/*.md` (70 informes) | Corpus del RAG del notebook 05. |
| `data/*.csv` | Los tres datasets del pipeline. |

| Se ignora | Por qué |
|---|---|
| `portfolio.db` | Contiene posiciones y precios de compra **reales**. El componente SQL queda demostrado por el esquema y las consultas de `backend/portfolio_db.py`, que sí se versiona. |
| `reports/Trade_Memo_*.pdf` | Registran operaciones reales de la cartera. |
| `node_modules/`, cachés regenerables | Se reconstruyen con `npm install` / un reescaneo. |

---

## Metodología

### Recolección
El endpoint de screener de Yahoo devuelve ~250 filas por consulta y limita la
paginación. `backend/universe_fetcher.py` **parte el rango de capitalización en
sub-bandas** y divide recursivamente las que siguen llenas. La unión de las bandas
hoja es el universo completo.

### Limpieza
| Paso | Decisión |
|---|---|
| Exclusión de dominio | Fuera preferentes, warrants, units y fondos: no son capital ordinario |
| Sin etiqueta | Eliminadas — la variable objetivo no se puede imputar |
| Beta / WACC nulos | Mediana **sectorial**, no global |
| Outliers de mercado | **Conservados** — son el fenómeno que se estudia |
| Outliers imposibles | MoS recortado a [−200, 100] |
| Fugas de información | Eliminadas antes de modelar |

### Modelado
Tres familias de modelos, validación cruzada estratificada de 5 particiones,
`GridSearchCV` sobre el mejor candidato y **ablación por bloques de variables**
para identificar el origen real de la señal. Escalado dentro de `Pipeline` para
evitar fuga entre particiones.

**Métrica principal:** ROC-AUC, por ser insensible al umbral y responder
directamente a la pregunta de si el modelo ordena mejor que el azar.

---

## Retos encontrados

| Reto | Solución |
|---|---|
| Yahoo limita a 250 filas por consulta | Partición recursiva del rango de capitalización |
| Rate-limiting agresivo (HTTP 429) | Descarga en lote + tandas de 150 + backoff exponencial |
| ADR con cuentas en otra divisa | `fx_engine`: se detectó un error de valoración de ~87 000× |
| Betas irreales de yfinance (0,03) | Guardarraíles: β ∈ [0,35 · 2,50] |
| Valor terminal explosivo | Diferencial mínimo WACC − g del 2 % |
| **Un solo corte temporal** | Declarado como limitación; motiva la ablación |
| **yfinance < 1.0 falla en silencio** | Fijado `yfinance>=1.2` en `requirements.txt` |

---

## Instalación y ejecución

```bash
pip install -r requirements.txt
```

> ⚠ **`yfinance` debe ser >= 1.0.** Las versiones 0.2.x rompen todas las descargas
> **en silencio**: los precios se congelan y la cartera aparenta un +6 % falso.
> Comprobación: `GET /api/health` devuelve el intérprete y la versión en uso.

**Notebooks** (en orden 01 → 05):
```bash
jupyter notebook notebooks/
```

**Aplicación web:**
```bash
./START_WINDOWS.bat          # backend :8011 + frontend :3016
```

**Regenerar la presentación** (sólo si hay que cambiarla):
```bash
cd presentacion && python make_charts.py && python build_deck.py
```
Las capturas de código no son pantallazos: se generan con Pygments a partir de
`presentacion/snippets.py`. Para cambiar un fragmento, edítalo ahí y reejecuta —
no edites el `.pptx` a mano si luego vas a volver a generarlo.

---

## Componente de IA generativa

Sistema **RAG** sobre las 70 tesis de inversión que genera la propia aplicación.
Troceado por secciones de Markdown, índice TF-IDF y recuperación con filtro por
ticker. El prompt obliga al modelo a responder **sólo** con el contexto
recuperado, para evitar que invente cifras.

Estado: recuperación y construcción del prompt implementadas y ejecutables sin
clave de API; la llamada al LLM está preparada y requiere `ANTHROPIC_API_KEY`.
Detalle en `notebooks/05`.

---

## Limitaciones

1. **Una sola fecha de escaneo** → corte transversal, no panel. Imposibilita la
   validación temporal, que es la correcta en finanzas. **Es la limitación
   principal del estudio.**
2. **Ventana de 18 sesiones** → el value investing opera en años; tres semanas son
   fundamentalmente ruido.
3. **Sin coste de transacción** → un diferencial de quintiles pequeño desaparece
   con comisiones.
4. **Sin libro de operaciones** en la cartera → la reconstrucción histórica sólo
   ve las posiciones actuales.

## Trabajo futuro

1. **Escaneo mensual durante 12+ meses** — convierte el corte en panel y permite
   validación temporal real. Es la mejora número uno.
2. **Neutralizar por sector** — aísla la señal de valoración de la rotación
   sectorial que contamina el resultado actual.
3. **Añadir Altman Z y Piotroski F como features** — ya los calcula la aplicación.
4. **Migrar el RAG a embeddings semánticos** y exponerlo como pestaña de chat.

---

## Stack

**Backend:** FastAPI · Pydantic · SQLite · yfinance · pandas · NumPy · SciPy
**ML:** scikit-learn · matplotlib · seaborn
**Frontend:** React · TypeScript · Vite · Tailwind · Recharts

## Referencias

- Schoenmaker & Schramade (2023), *Risk-Return Analysis* — CAPM y WACC
- Damodaran — modelos de Exceso de Retorno y AFFO
- Altman (1968) — Z-Score · Piotroski (2000) — F-Score
- Cava (2006), *El Arte de Especular* — análisis técnico
