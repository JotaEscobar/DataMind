"""
auto_analyst.py — Análisis automático profundo al subir un archivo

Qué hace:
  1. Ejecuta ~6 bloques de código pandas contra el DataFrame real (sin LLM)
  2. Recopila todos los resultados en un contexto estructurado
  3. Llama al LLM UNA sola vez para generar narrativa + preguntas sugeridas
  4. Devuelve AutoAnalysisResult con todo listo para streamear al frontend

Por qué este diseño:
  - Los números los calcula pandas (exactos, nunca inventados)
  - El LLM solo narra — no calcula
  - Una sola llamada LLM = rápido y barato
  - El resultado se usa como "primer mensaje" del asistente en la sesión
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

from app.core.code_executor import CodeExecutor, load_dataframe
from app.core.intent import FileContext

logger = logging.getLogger(__name__)


# ── Resultado del análisis automático ─────────────────────────────────────────

@dataclass
class AutoAnalysisResult:
    narrative: str                          # Texto principal para el usuario
    suggested_questions: List[str]          # 4 preguntas concretas basadas en los datos
    stats: Dict[str, Any] = field(default_factory=dict)  # Métricas clave calculadas
    warnings: List[str] = field(default_factory=list)    # Alertas de calidad de datos
    error: str = ""

    @property
    def success(self) -> bool:
        return not self.error


# ── Bloques de código para análisis inicial ───────────────────────────────────
# Cada bloque es independiente y falla silenciosamente si no aplica al dataset

_ANALYSIS_BLOCKS: List[Tuple[str, str]] = [

    ("overview", """
import pandas as pd
total = len(df)
numeric_cols = df.select_dtypes(include='number').columns.tolist()
text_cols = df.select_dtypes(include='object').columns.tolist()
missing_total = int(df.isnull().sum().sum())
dup_rows = int(df.duplicated().sum())
result = {
    "total_rows": total,
    "total_cols": len(df.columns),
    "numeric_cols": numeric_cols,
    "text_cols": text_cols,
    "missing_total": missing_total,
    "missing_pct": round(missing_total / max(total * len(df.columns), 1) * 100, 1),
    "duplicate_rows": dup_rows,
}
"""),

    ("numeric_summary", """
import pandas as pd
import numpy as np
num_df = df.select_dtypes(include='number')
if num_df.empty:
    result = {}
else:
    desc = num_df.describe().round(2)
    # Detectar columnas con alta variabilidad (CV > 1)
    means = desc.loc['mean']
    stds = desc.loc['std']
    high_variance = [col for col in means.index if means[col] != 0 and stds[col]/abs(means[col]) > 1]
    result = {
        "stats": desc.to_dict(),
        "high_variance_cols": high_variance,
        "most_complete_numeric": num_df.isnull().mean().sort_values().index[0] if len(num_df.columns) > 0 else None,
    }
"""),

    ("top_categories", """
import pandas as pd
text_cols = df.select_dtypes(include='object').columns.tolist()
result = {}
for col in text_cols[:4]:  # máximo 4 columnas texto
    vc = df[col].value_counts().head(5)
    result[col] = {
        "top_values": vc.index.tolist(),
        "top_counts": vc.values.tolist(),
        "unique_count": int(df[col].nunique()),
        "dominance_pct": round(vc.iloc[0] / len(df) * 100, 1) if len(vc) > 0 else 0,
    }
"""),

    ("numeric_top_values", """
import pandas as pd
num_cols = df.select_dtypes(include='number').columns.tolist()
result = {}
for col in num_cols[:5]:  # máximo 5 columnas numéricas
    series = df[col].dropna()
    if len(series) == 0:
        continue
    result[col] = {
        "sum": round(float(series.sum()), 2),
        "mean": round(float(series.mean()), 2),
        "median": round(float(series.median()), 2),
        "min": round(float(series.min()), 2),
        "max": round(float(series.max()), 2),
        "std": round(float(series.std()), 2),
        "zeros_pct": round((series == 0).mean() * 100, 1),
        "negative_pct": round((series < 0).mean() * 100, 1),
    }
"""),

    ("outlier_quick_scan", """
import pandas as pd
import numpy as np
num_cols = df.select_dtypes(include='number').columns.tolist()
result = {}
for col in num_cols[:5]:
    series = df[col].dropna()
    if len(series) < 10:
        continue
    Q1, Q3 = series.quantile(0.25), series.quantile(0.75)
    IQR = Q3 - Q1
    if IQR == 0:
        continue
    outliers = ((series < Q1 - 1.5*IQR) | (series > Q3 + 1.5*IQR)).sum()
    result[col] = {
        "outlier_count": int(outliers),
        "outlier_pct": round(outliers / len(series) * 100, 1),
        "Q1": round(float(Q1), 2),
        "Q3": round(float(Q3), 2),
    }
"""),

    ("time_series_detect", """
import pandas as pd
# Detectar columna temporal
date_col = None
for col in df.columns:
    try:
        parsed = pd.to_datetime(df[col], errors='coerce')
        if parsed.notnull().mean() > 0.7:
            date_col = col
            df[col] = parsed
            break
    except:
        pass

if date_col is None:
    result = {"has_dates": False}
else:
    ts = df.set_index(date_col).sort_index()
    num_cols = ts.select_dtypes(include='number').columns.tolist()
    result = {
        "has_dates": True,
        "date_col": date_col,
        "date_range": {
            "min": str(ts.index.min().date()),
            "max": str(ts.index.max().date()),
        },
        "numeric_cols_for_ts": num_cols[:3],
        "monthly_available": len(ts) >= 12,
    }
    if num_cols:
        # Tendencia rápida: ¿creció o cayó el primer vs último período?
        mid = len(ts) // 2
        first_half_mean = float(ts[num_cols[0]].iloc[:mid].mean())
        second_half_mean = float(ts[num_cols[0]].iloc[mid:].mean())
        pct_change = ((second_half_mean - first_half_mean) / abs(first_half_mean) * 100) if first_half_mean != 0 else 0
        result["trend"] = {
            "col": num_cols[0],
            "direction": "creciente" if pct_change > 2 else ("decreciente" if pct_change < -2 else "estable"),
            "pct_change": round(pct_change, 1),
        }
"""),

    ("correlation_quick", """
import pandas as pd
import numpy as np
num_df = df.select_dtypes(include='number').dropna()
if len(num_df.columns) < 2 or len(num_df) < 10:
    result = {"available": False}
else:
    corr = num_df.corr()
    # Extraer pares de alta correlación (> 0.7 o < -0.7), excluyendo diagonal
    pairs = []
    cols = corr.columns.tolist()
    for i in range(len(cols)):
        for j in range(i+1, len(cols)):
            val = corr.iloc[i, j]
            if abs(val) >= 0.65:
                pairs.append({
                    "col_a": cols[i],
                    "col_b": cols[j],
                    "correlation": round(float(val), 3),
                    "type": "positiva" if val > 0 else "negativa",
                })
    result = {
        "available": True,
        "high_correlation_pairs": sorted(pairs, key=lambda x: abs(x["correlation"]), reverse=True)[:5],
        "total_numeric_cols": len(cols),
    }
"""),

]


# ── Prompt para el LLM — narra los resultados, no los calcula ─────────────────

def _build_narrative_prompt(ctx: FileContext, analysis_data: Dict[str, Any]) -> str:
    domain_labels = {
        "financial": "financiero/comercial",
        "hr": "recursos humanos",
        "marketing": "marketing/producto",
        "ops": "operaciones/logística",
        "scientific": "científico/experimental",
        "general": "general",
    }
    domain = domain_labels.get(ctx.domain_hint, "general")

    return f"""Eres DATAMIND 2.0. Acabas de analizar automáticamente un archivo de datos.
Tu trabajo es generar un diagnóstico inicial claro, útil y directo.

ARCHIVO: {ctx.file_name}
DOMINIO DETECTADO: {domain}
RESULTADOS DEL ANÁLISIS (datos REALES calculados por pandas):
{json.dumps(analysis_data, ensure_ascii=False, indent=2, default=str)}

INSTRUCCIONES:
1. Escribe un DIAGNÓSTICO en máximo 4 párrafos cortos (máx 4 líneas cada uno).
2. Empieza con el hallazgo más interesante o relevante del dataset — no con "El archivo contiene...".
3. Menciona cifras reales de los resultados. NUNCA inventes números.
4. Si hay anomalías, nulos importantes o tendencias, menciónalos.
5. Usa **negritas** para cifras clave (máx 2 por párrafo).
6. Escribe en español, tono profesional pero accesible.

Luego, en una línea separada, escribe exactamente:
SUGERENCIAS: [pregunta1] | [pregunta2] | [pregunta3] | [pregunta4]

Las 4 preguntas deben ser CONCRETAS y basadas en los datos reales del análisis.
Ejemplo correcto: "¿Cuál es la tendencia mensual de ventas?" (si hay columna de fechas y ventas)
Ejemplo incorrecto: "¿Qué análisis quieres?" (demasiado vago)

DIAGNÓSTICO:"""


# ── Motor principal ────────────────────────────────────────────────────────────

class AutoAnalyst:
    """
    Ejecuta el análisis automático completo al subir un archivo.
    Separa cálculos (pandas exacto) de narrativa (LLM).
    """

    def __init__(self, chat_fn: Callable, fast_model: str):
        """
        chat_fn: función (model, messages) -> str
        fast_model: modelo liviano para la narrativa (no necesita el potente)
        """
        self._chat = chat_fn
        self._fast_model = fast_model
        self._executor = CodeExecutor(timeout_seconds=20)

    def run(self, ctx: FileContext) -> AutoAnalysisResult:
        """
        Ejecuta análisis completo. Bloqueante.
        Usa este método cuando no necesitas streaming.
        """
        if not ctx.is_loaded:
            return AutoAnalysisResult(
                narrative="No hay archivo cargado.",
                suggested_questions=[],
                error="FileContext vacío.",
            )

        df = load_dataframe(ctx.file_path)
        if df is None:
            return AutoAnalysisResult(
                narrative="No se pudo cargar el archivo.",
                suggested_questions=[],
                error=f"No se pudo leer: {ctx.file_path}",
            )

        # 1. Ejecutar todos los bloques de análisis
        analysis_data, warnings = self._run_analysis_blocks(df)

        # 2. LLM genera narrativa sobre los resultados
        narrative, suggestions = self._generate_narrative(ctx, analysis_data)

        return AutoAnalysisResult(
            narrative=narrative,
            suggested_questions=suggestions,
            stats=analysis_data,
            warnings=warnings,
        )

    def _run_analysis_blocks(
        self, df: pd.DataFrame
    ) -> Tuple[Dict[str, Any], List[str]]:
        """
        Ejecuta cada bloque de código y recopila resultados.
        Los bloques que fallan se omiten silenciosamente.
        """
        results: Dict[str, Any] = {}
        warnings: List[str] = []

        for block_name, code in _ANALYSIS_BLOCKS:
            try:
                code_result = self._executor.execute(code, df)
                if code_result.success and code_result.result_repr:
                    # Parsear el result_repr como dict/valor Python
                    import ast
                    try:
                        parsed = ast.literal_eval(code_result.result_repr)
                        results[block_name] = parsed
                    except Exception:
                        # Si no es parseable, guardar como string
                        results[block_name] = code_result.result_repr[:500]
                elif not code_result.success:
                    logger.debug("Block '%s' falló: %s", block_name, code_result.error)
            except Exception as e:
                logger.debug("Block '%s' excepción: %s", block_name, e)

        # Detectar advertencias de calidad
        overview = results.get("overview", {})
        if isinstance(overview, dict):
            if overview.get("missing_pct", 0) > 15:
                warnings.append(f"Alta proporción de nulos: {overview['missing_pct']}% del total")
            if overview.get("duplicate_rows", 0) > 0:
                dup = overview["duplicate_rows"]
                total = overview.get("total_rows", 1)
                warnings.append(f"{dup} filas duplicadas ({round(dup/total*100, 1)}% del total)")

        outliers = results.get("outlier_quick_scan", {})
        if isinstance(outliers, dict):
            heavy = [(col, data) for col, data in outliers.items()
                     if isinstance(data, dict) and data.get("outlier_pct", 0) > 5]
            for col, data in heavy[:2]:
                warnings.append(
                    f"Columna '{col}': {data['outlier_count']} outliers ({data['outlier_pct']}%)"
                )

        return results, warnings

    def _generate_narrative(
        self,
        ctx: FileContext,
        analysis_data: Dict[str, Any],
    ) -> Tuple[str, List[str]]:
        """
        Llama al LLM UNA vez para generar narrativa + sugerencias.
        """
        prompt = _build_narrative_prompt(ctx, analysis_data)
        try:
            raw = self._chat(
                model=self._fast_model,
                messages=[{"role": "user", "content": prompt}],
            ).strip()
        except Exception as e:
            logger.error("AutoAnalyst LLM falló: %s", e)
            # Fallback: narrativa sin LLM
            return self._fallback_narrative(ctx, analysis_data), self._fallback_suggestions(ctx)

        # Separar narrativa de sugerencias
        narrative = raw
        suggestions: List[str] = []

        if "SUGERENCIAS:" in raw:
            parts = raw.split("SUGERENCIAS:", 1)
            narrative = parts[0].strip()
            raw_suggestions = parts[1].strip()
            # Parsear "pregunta1 | pregunta2 | ..."
            suggestions = [s.strip().strip("[]") for s in raw_suggestions.split("|") if s.strip()]
            suggestions = [s for s in suggestions if len(s) > 5][:4]

        if not suggestions:
            suggestions = self._fallback_suggestions(ctx)

        return narrative, suggestions

    def _fallback_narrative(self, ctx: FileContext, data: Dict[str, Any]) -> str:
        """Narrativa sin LLM cuando el modelo falla."""
        overview = data.get("overview", {})
        if not isinstance(overview, dict):
            return f"📂 **{ctx.file_name}** cargado. ¿Qué quieres analizar?"

        rows = overview.get("total_rows", ctx.rows)
        cols = overview.get("total_cols", len(ctx.columns))
        missing_pct = overview.get("missing_pct", 0)
        quality = "excelente" if missing_pct < 2 else "buena" if missing_pct < 10 else "regular"

        lines = [
            f"📂 **{ctx.file_name}** cargado — **{rows:,} filas · {cols} columnas**.",
            f"Calidad de datos: **{quality}** ({missing_pct}% nulos).",
        ]
        if ctx.numeric_cols:
            lines.append(f"Columnas numéricas disponibles: {', '.join(ctx.numeric_cols[:5])}.")
        if ctx.date_cols:
            lines.append("Detecté columnas temporales — puedo analizar tendencias por período.")

        lines.append("\n¿Qué quieres explorar primero?")
        return "\n".join(lines)

    def _fallback_suggestions(self, ctx: FileContext) -> List[str]:
        """Sugerencias genéricas basadas en el dominio del archivo."""
        base = {
            "financial": [
                "¿Cuáles son los 5 productos/categorías con más ventas?",
                "¿Cuál es la tendencia de ingresos por mes?",
                "¿Dónde están los outliers en los montos?",
                "Aplica análisis Pareto a las ventas",
            ],
            "hr": [
                "¿Cuál es la distribución por departamento?",
                "¿Cómo se distribuyen los salarios?",
                "¿Qué departamento tiene mayor rotación?",
                "Muestra la antigüedad promedio por área",
            ],
            "marketing": [
                "¿Cuál es la tasa de conversión por canal?",
                "¿Qué segmento de clientes genera más valor?",
                "Análisis de cohortes por mes de adquisición",
                "¿Cuál es el LTV promedio por segmento?",
            ],
            "ops": [
                "¿Cuál es el tiempo promedio de ciclo por etapa?",
                "¿Dónde están los cuellos de botella del proceso?",
                "¿Qué porcentaje cumple el SLA?",
                "Detecta anomalías en los tiempos de entrega",
            ],
            "scientific": [
                "¿Hay diferencias significativas entre los grupos?",
                "¿Qué variables están más correlacionadas?",
                "Muestra la distribución de la variable principal",
                "¿Hay outliers que puedan distorsionar los resultados?",
            ],
        }
        return base.get(ctx.domain_hint, [
            "¿Cuáles son las estadísticas descriptivas principales?",
            "¿Hay valores atípicos o anomalías en los datos?",
            "¿Qué columnas están más correlacionadas entre sí?",
            "Muéstrame la distribución de los valores principales",
        ])


# ── Instancia global ──────────────────────────────────────────────────────────
# Se inicializa en main.py con la función _chat_text del agente

_auto_analyst_instance: Optional[AutoAnalyst] = None


def get_auto_analyst(chat_fn: Callable, fast_model: str) -> AutoAnalyst:
    """Factory con lazy init."""
    global _auto_analyst_instance
    if _auto_analyst_instance is None:
        _auto_analyst_instance = AutoAnalyst(chat_fn=chat_fn, fast_model=fast_model)
    return _auto_analyst_instance
