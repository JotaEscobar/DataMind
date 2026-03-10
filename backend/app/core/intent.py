"""
intent.py — Clasificador de intención + FileContext + Personas

Responsabilidades:
  1. IntentType: qué tipo de request es (CHAT, NEEDS_FILE, ANALYSIS, EXPORT)
  2. FileContext: estado persistente del archivo cargado por sesión
  3. AgentPersona: personas diferenciadas con prompts y tools propios
  4. IntentClassifier: llama al LLM ligero para clasificar intención
                       y seleccionar persona según archivo + pregunta
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# INTENT TYPES
# ──────────────────────────────────────────────────────────────────────────────

class IntentType(str, Enum):
    CHAT       = "CHAT"        # Saludo, agradecimiento, pregunta general — NO activa ReAct
    NEEDS_FILE = "NEEDS_FILE"  # Pide análisis pero no hay archivo cargado
    ANALYSIS   = "ANALYSIS"    # Análisis real sobre datos — activa ReAct completo
    EXPORT     = "EXPORT"      # Solicita PDF, PPTX, dashboard — activa agente narrador


# ──────────────────────────────────────────────────────────────────────────────
# FILE CONTEXT — Estado persistente del archivo por sesión
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class FileContext:
    """
    Guarda el estado completo del archivo cargado en una sesión.
    Se crea una vez al subir el archivo y se reutiliza en todos los turnos.
    """
    file_path: str = ""
    file_name: str = ""
    rows: int = 0
    columns: List[str] = field(default_factory=list)
    dtypes: Dict[str, str] = field(default_factory=dict)
    numeric_cols: List[str] = field(default_factory=list)
    date_cols: List[str] = field(default_factory=list)
    text_cols: List[str] = field(default_factory=list)
    missing_values: Dict[str, int] = field(default_factory=dict)
    sample_rows: List[dict] = field(default_factory=list)
    domain_hint: str = ""        # Perfil detectado: financial, hr, scientific, marketing, ops
    auto_diagnosis: str = ""     # Diagnóstico inicial generado al subir el archivo

    @property
    def is_loaded(self) -> bool:
        return bool(self.file_path and os.path.exists(self.file_path))

    @classmethod
    def from_dataframe(cls, file_path: str, df: pd.DataFrame) -> "FileContext":
        """Construye el contexto completo a partir de un DataFrame ya cargado."""
        dtypes = df.dtypes.astype(str).to_dict()
        numeric_cols = df.select_dtypes(include="number").columns.tolist()
        date_cols = df.select_dtypes(include=["datetime", "datetimetz"]).columns.tolist()
        # También detectar columnas de texto que parezcan fechas
        for col in df.select_dtypes(include="object").columns:
            sample = df[col].dropna().head(5).astype(str).tolist()
            if any(
                any(c.isdigit() for c in v) and any(c in v for c in ["-", "/", " "])
                for v in sample
            ):
                date_cols.append(col)
        date_cols = list(dict.fromkeys(date_cols))  # dedup
        text_cols = [c for c in df.select_dtypes(include="object").columns if c not in date_cols]

        missing = {
            k: int(v)
            for k, v in df.isnull().sum().items()
            if v > 0
        }

        sample = df.head(5).fillna("").astype(str).to_dict(orient="records")

        domain_hint = _detect_domain(df.columns.tolist())

        return cls(
            file_path=file_path,
            file_name=os.path.basename(file_path),
            rows=len(df),
            columns=df.columns.tolist(),
            dtypes=dtypes,
            numeric_cols=numeric_cols,
            date_cols=date_cols,
            text_cols=text_cols,
            missing_values=missing,
            sample_rows=sample,
            domain_hint=domain_hint,
        )

    def to_prompt_block(self) -> str:
        """
        Devuelve un bloque de texto para inyectar al inicio de cada prompt.
        Compacto pero completo — el LLM no necesita adivinar nada sobre los datos.
        """
        if not self.is_loaded:
            return "Archivo: ninguno cargado."

        missing_summary = (
            f"{len(self.missing_values)} columnas con nulos"
            if self.missing_values
            else "sin nulos"
        )

        cols_preview = ", ".join(self.columns[:20])
        if len(self.columns) > 20:
            cols_preview += f" ... (+{len(self.columns) - 20} más)"

        lines = [
            f"═══ CONTEXTO DEL ARCHIVO ═══",
            f"Archivo : {self.file_name}",
            f"Filas   : {self.rows:,}  |  Columnas: {len(self.columns)}  |  Calidad: {missing_summary}",
            f"Columnas: {cols_preview}",
        ]
        if self.numeric_cols:
            lines.append(f"Numéricas: {', '.join(self.numeric_cols[:10])}")
        if self.date_cols:
            lines.append(f"Fechas   : {', '.join(self.date_cols[:5])}")
        if self.text_cols:
            lines.append(f"Texto    : {', '.join(self.text_cols[:8])}")
        if self.missing_values:
            top_missing = sorted(self.missing_values.items(), key=lambda x: -x[1])[:5]
            lines.append(f"Nulos top: {', '.join(f'{k}={v}' for k,v in top_missing)}")

        # Muestra compacta de 3 filas
        if self.sample_rows:
            lines.append("Muestra (3 filas):")
            for row in self.sample_rows[:3]:
                row_str = " | ".join(f"{k}: {v}" for k, v in list(row.items())[:6])
                lines.append(f"  › {row_str}")

        lines.append("═══════════════════════════")
        return "\n".join(lines)


def _detect_domain(columns: List[str]) -> str:
    """Detecta el dominio temático del dataset a partir de los nombres de columnas."""
    col_str = " ".join(columns).lower()

    financial_signals = ["monto", "precio", "costo", "ingreso", "egreso", "venta",
                         "revenue", "profit", "salary", "sueldo", "pago", "factura",
                         "importe", "deuda", "credito", "rentabilidad", "margen"]
    hr_signals = ["empleado", "cargo", "departamento", "area", "puesto", "dni",
                  "rut", "nombre", "apellido", "contrato", "antiguedad", "ausencia",
                  "employee", "department", "position", "hire_date"]
    marketing_signals = ["cliente", "usuario", "sesion", "conversion", "click",
                         "campaign", "channel", "funnel", "churn", "nps", "cac",
                         "ltv", "customer", "acquisition", "retention"]
    ops_signals = ["tiempo", "duracion", "proceso", "etapa", "estado", "orden",
                   "envio", "entrega", "inventario", "stock", "proveedor",
                   "tiempo_ciclo", "lead_time", "throughput", "sla"]
    scientific_signals = ["muestra", "medicion", "experimento", "control",
                          "tratamiento", "variable", "sensor", "temperatura",
                          "presion", "concentracion", "dosis", "resultado",
                          "paciente", "diagnostico", "grupo_a", "grupo_b"]

    scores = {
        "financial":   sum(1 for s in financial_signals  if s in col_str),
        "hr":          sum(1 for s in hr_signals          if s in col_str),
        "marketing":   sum(1 for s in marketing_signals   if s in col_str),
        "ops":         sum(1 for s in ops_signals         if s in col_str),
        "scientific":  sum(1 for s in scientific_signals  if s in col_str),
    }

    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else "general"


# ──────────────────────────────────────────────────────────────────────────────
# PERSONAS — Cada una con su sistema de razonamiento diferenciado
# ──────────────────────────────────────────────────────────────────────────────

class AgentPersona(str, Enum):
    DATA_ANALYST       = "DATA_ANALYST"
    FINANCIAL_ANALYST  = "FINANCIAL_ANALYST"
    OPERATIONS_ANALYST = "OPERATIONS_ANALYST"
    STATISTICIAN       = "STATISTICIAN"
    GROWTH_ANALYST     = "GROWTH_ANALYST"
    DATA_DETECTIVE     = "DATA_DETECTIVE"
    REPORT_NARRATOR    = "REPORT_NARRATOR"


PERSONA_PROFILES: Dict[AgentPersona, Dict] = {

    AgentPersona.DATA_ANALYST: {
        "title": "Analista de Datos Senior",
        "focus": "exploración general, calidad de datos, distribuciones, patrones",
        "style": (
            "Didáctico y preciso. Siempre explica qué significan los números antes de "
            "interpretar. Empieza con la calidad del dato antes de cualquier conclusión."
        ),
        "priority_tools": ["inspect_data_structure", "smart_cleaner", "analytics_stats"],
        "key_metrics": "completitud, distribuciones, mediana, moda, rango intercuartílico",
    },

    AgentPersona.FINANCIAL_ANALYST: {
        "title": "Analista Financiero Certificado",
        "focus": "rentabilidad, tendencias financieras, Pareto, forecasting, variaciones",
        "style": (
            "Ejecutivo y orientado a decisión. Va directo al impacto económico. "
            "Siempre contextualiza cifras con variación porcentual y benchmark."
        ),
        "priority_tools": ["trend_analyzer", "pareto_engine", "forecaster", "analytics_stats"],
        "key_metrics": "margen, variación YoY/MoM, CAGR, concentración Pareto, proyección",
    },

    AgentPersona.OPERATIONS_ANALYST: {
        "title": "Analista de Operaciones",
        "focus": "eficiencia de procesos, tiempos de ciclo, cuellos de botella, SLA",
        "style": (
            "Técnico y orientado a proceso. Busca percentiles P90/P95 más que promedios. "
            "Identifica variabilidad y qué la causa."
        ),
        "priority_tools": ["analytics_stats", "anomaly_scanner", "trend_analyzer"],
        "key_metrics": "percentiles, desviación estándar, tiempos medios, SLA compliance, throughput",
    },

    AgentPersona.STATISTICIAN: {
        "title": "Estadístico de Datos",
        "focus": "significancia estadística, distribuciones, correlaciones, tests de hipótesis",
        "style": (
            "Riguroso y cauteloso. Nunca concluye sin evidencia estadística. "
            "Siempre menciona p-value, tamaño de muestra y limitaciones del análisis."
        ),
        "priority_tools": ["stat_tester", "correlation_discovery", "analytics_stats"],
        "key_metrics": "p-value, R², correlación de Pearson/Spearman, intervalos de confianza",
    },

    AgentPersona.GROWTH_ANALYST: {
        "title": "Analista de Crecimiento y Producto",
        "focus": "cohortes, segmentación, comportamiento de usuarios, retención, conversión",
        "style": (
            "Orientado al usuario y al comportamiento. Piensa en grupos, no en promedios. "
            "Busca segmentos que se comportan diferente al resto."
        ),
        "priority_tools": ["cohort_tracker", "cluster_segmenter", "trend_analyzer"],
        "key_metrics": "retención, churn, LTV, CAC, tasa de conversión, NPS por segmento",
    },

    AgentPersona.DATA_DETECTIVE: {
        "title": "Investigador de Datos",
        "focus": "anomalías, inconsistencias, correlaciones inesperadas, valores atípicos",
        "style": (
            "Curioso e inquisitivo. Formula hipótesis antes de concluir. "
            "Busca el 'por qué' detrás de cada número extraño. No descansa hasta explicar la anomalía."
        ),
        "priority_tools": ["anomaly_scanner", "correlation_discovery", "stat_tester"],
        "key_metrics": "Z-score, IQR, Isolation Forest score, correlaciones espurias, duplicados",
    },

    AgentPersona.REPORT_NARRATOR: {
        "title": "Narrador de Insights Ejecutivos",
        "focus": "síntesis de resultados, narrativa ejecutiva, exportación de reportes",
        "style": (
            "Claro, ejecutivo, sin jerga técnica. Transforma datos en decisiones. "
            "Cada insight termina con una recomendación accionable."
        ),
        "priority_tools": [],  # No ejecuta análisis — narra resultados ya calculados
        "key_metrics": "hallazgos clave, impacto estimado, recomendación prioritaria",
    },
}


def select_persona_from_context(
    query: str,
    file_context: Optional[FileContext] = None,
) -> AgentPersona:
    """
    Selecciona la persona óptima sin llamar al LLM.
    Combina señales del archivo + palabras clave de la pregunta.
    Rápido, determinístico, sin costo de tokens.
    """
    q = query.lower()

    # Señales de exportación/reporte — siempre REPORT_NARRATOR
    if any(w in q for w in ["exporta", "reporte", "pdf", "pptx", "presenta", "resume",
                              "dashboard", "diapositiva", "informe", "comparte"]):
        return AgentPersona.REPORT_NARRATOR

    # Señales de investigación — DATA_DETECTIVE
    if any(w in q for w in ["anomal", "raro", "extraño", "inconsisten", "error",
                              "duplicad", "outlier", "sospech", "por qué", "causa"]):
        return AgentPersona.DATA_DETECTIVE

    # Señales estadísticas — STATISTICIAN
    if any(w in q for w in ["significan", "correlaci", "p-value", "hipótesis",
                              "distribuc", "normal", "t-test", "chi", "regresión"]):
        return AgentPersona.STATISTICIAN

    # Señales de crecimiento/marketing — GROWTH_ANALYST
    if any(w in q for w in ["cohorte", "retención", "churn", "conversión", "funnel",
                              "segmento", "usuario", "cliente", "ltv", "cac", "nps"]):
        return AgentPersona.GROWTH_ANALYST

    # Señales operacionales — OPERATIONS_ANALYST
    if any(w in q for w in ["tiempo", "proceso", "etapa", "demora", "sla", "ciclo",
                              "eficiencia", "inventario", "entrega", "proveedor"]):
        return AgentPersona.OPERATIONS_ANALYST

    # Señales financieras — FINANCIAL_ANALYST
    if any(w in q for w in ["monto", "precio", "costo", "ingreso", "venta", "margen",
                              "rentab", "revenue", "profit", "factura", "tendencia"]):
        return AgentPersona.FINANCIAL_ANALYST

    # Sin señales claras en la pregunta → usar el dominio detectado del archivo
    if file_context and file_context.domain_hint:
        domain_map = {
            "financial":  AgentPersona.FINANCIAL_ANALYST,
            "hr":         AgentPersona.OPERATIONS_ANALYST,
            "marketing":  AgentPersona.GROWTH_ANALYST,
            "ops":        AgentPersona.OPERATIONS_ANALYST,
            "scientific": AgentPersona.STATISTICIAN,
        }
        if file_context.domain_hint in domain_map:
            return domain_map[file_context.domain_hint]

    return AgentPersona.DATA_ANALYST


# ──────────────────────────────────────────────────────────────────────────────
# INTENT CLASSIFIER — Clasificación de intención por capas
# ──────────────────────────────────────────────────────────────────────────────

# Patrones conversacionales — capa 0, sin LLM, O(1)
_CHAT_PATTERNS = [
    "hola", "hi", "hey", "buenos", "buenas", "buen día", "saludos",
    "gracias", "thanks", "ok", "okay", "perfecto", "excelente", "genial",
    "entendido", "de acuerdo", "listo", "bien", "dale",
    "¿qué puedes", "qué puedes", "para qué sirves", "cómo funciona",
    "cuáles son tus", "ayuda", "help", "¿cómo te llamas", "quién eres",
    "¿qué eres", "qué eres", "¿qué haces", "qué haces",
]

_EXPORT_PATTERNS = [
    "exporta", "genera un pdf", "genera el pdf", "crea el pdf",
    "genera un pptx", "crea una presentación", "genera el reporte",
    "dashboard", "comparte el", "genera un reporte", "descarga",
]


class IntentClassifier:
    """
    Clasifica la intención del usuario en capas:
      Capa 0: regex/keywords — sin costo, instantáneo
      Capa 1: LLM liviano (solo si capa 0 no resuelve)
    """

    def __init__(self, chat_fn):
        """
        chat_fn: función que recibe (model, messages) y devuelve texto.
        Debe ser la versión liviana/barata del LLM.
        """
        self._chat = chat_fn
        self._fast_model = os.getenv("FAST_MODEL", "groq/llama-3.1-8b-instant")

    def classify(
        self,
        query: str,
        has_file: bool,
        history_length: int = 0,
    ) -> IntentType:
        """
        Clasifica la intención. Orden de evaluación:
          1. ¿Es claramente conversacional? → CHAT
          2. ¿Pide análisis pero no hay archivo? → NEEDS_FILE
          3. ¿Pide exportar? → EXPORT
          4. Llamar al LLM liviano para decidir CHAT vs ANALYSIS
        """
        q_lower = query.lower().strip()

        # ── Capa 0a: patrones conversacionales directos ──
        if len(q_lower.split()) <= 3:
            if any(p in q_lower for p in _CHAT_PATTERNS):
                return IntentType.CHAT

        if any(q_lower.startswith(p) or p in q_lower for p in _CHAT_PATTERNS):
            # Solo marcar como CHAT si es corta o es claramente un saludo
            word_count = len(q_lower.split())
            if word_count <= 8:
                return IntentType.CHAT

        # ── Capa 0b: exportación ──
        if any(p in q_lower for p in _EXPORT_PATTERNS):
            return IntentType.EXPORT

        # ── Capa 0c: análisis sin archivo ──
        # Si la pregunta claramente pide analizar datos y no hay archivo
        analysis_signals = [
            "analiza", "muéstrame", "muestrame", "cuál fue", "cuál es",
            "cuántos", "cuantos", "promedio", "total", "suma", "grafico",
            "gráfico", "torta", "barras", "tendencia", "distribución",
            "top", "ranking", "comparar", "correlación",
        ]
        if not has_file and any(s in q_lower for s in analysis_signals):
            return IntentType.NEEDS_FILE

        # ── Capa 1: LLM liviano para casos ambiguos ──
        # Solo si la query tiene más de 5 palabras y no fue resuelta arriba
        if len(q_lower.split()) > 5:
            return self._classify_with_llm(query, has_file)

        # Default: si hay archivo, asumir análisis; si no, chat
        return IntentType.ANALYSIS if has_file else IntentType.CHAT

    def _classify_with_llm(self, query: str, has_file: bool) -> IntentType:
        """Llamada ultraliviana al LLM — solo clasifica, no analiza."""
        try:
            file_status = "hay un archivo de datos cargado" if has_file else "NO hay archivo cargado"
            prompt = (
                f"Clasifica esta solicitud de usuario en UNA sola palabra. "
                f"Contexto: {file_status}.\n"
                f"Solicitud: \"{query}\"\n\n"
                f"Responde SOLO con una de estas palabras:\n"
                f"- CHAT (si es saludo, agradecimiento, pregunta general sin datos)\n"
                f"- ANALYSIS (si pide analizar, calcular o explorar datos)\n"
                f"- NEEDS_FILE (si pide análisis pero no hay archivo)\n"
                f"- EXPORT (si pide generar PDF, PPTX, dashboard o reporte)\n\n"
                f"Respuesta (una palabra):"
            )
            result = self._chat(
                model=self._fast_model,
                messages=[{"role": "user", "content": prompt}],
            ).strip().upper()

            # Extraer solo la palabra clave
            for intent in ["ANALYSIS", "NEEDS_FILE", "EXPORT", "CHAT"]:
                if intent in result:
                    return IntentType(intent)

        except Exception as e:
            logger.warning("IntentClassifier LLM falló, usando fallback: %s", e)

        # Fallback seguro
        return IntentType.ANALYSIS if has_file else IntentType.CHAT


# ──────────────────────────────────────────────────────────────────────────────
# RESPUESTAS DIRECTAS — Para CHAT y NEEDS_FILE sin activar ReAct
# ──────────────────────────────────────────────────────────────────────────────

_CHAT_RESPONSES = {
    "hola": (
        "¡Hola! Soy **DataMind**, tu analista de datos con IA. "
        "Puedo analizar archivos CSV o Excel, detectar anomalías, generar gráficos, "
        "calcular estadísticas, hacer forecasting y exportar reportes profesionales. "
        "¿Tienes un archivo que quieras explorar?"
    ),
    "gracias": "Con gusto. ¿Hay algo más que quieras analizar o profundizar?",
    "default": (
        "Soy **DataMind**, tu analista de datos. Adjunta un archivo CSV o Excel "
        "y dime qué quieres descubrir. Puedo hacer análisis estadístico, detectar "
        "anomalías, segmentar, proyectar tendencias y generar reportes."
    ),
}

NEEDS_FILE_RESPONSE = (
    "Para realizar ese análisis necesito que primero **cargues un archivo de datos**. "
    "Acepto formatos **CSV** y **Excel** (.xlsx, .xls). "
    "Una vez que lo tengas listo, dime qué quieres analizar y me pongo a trabajar."
)


def get_chat_response(query: str) -> str:
    """Respuesta directa para intenciones conversacionales."""
    q = query.lower()
    if any(w in q for w in ["hola", "hi", "hey", "buenos", "buenas", "buen día"]):
        return _CHAT_RESPONSES["hola"]
    if any(w in q for w in ["gracias", "thanks"]):
        return _CHAT_RESPONSES["gracias"]
    return _CHAT_RESPONSES["default"]
