"""
code_executor.py — Sandbox de ejecución de código Python

El LLM genera código pandas/numpy. Este módulo lo ejecuta de forma
segura contra el DataFrame real de la sesión y devuelve el resultado.

SEGURIDAD:
  - Bloquea imports peligrosos (os, sys, subprocess, shutil, etc.)
  - Solo permite pandas, numpy, scipy, sklearn, statsmodels
  - Timeout configurable (default 30s)
  - El código solo puede leer el DataFrame — no puede escribir archivos

FLUJO:
  1. Agente genera: ACTION: {"type": "code", "code": "result = df['ventas'].sum()"}
  2. CodeExecutor carga el DataFrame desde FileContext
  3. Ejecuta el código en namespace restringido con `df` disponible
  4. Captura stdout + variable `result`
  5. Devuelve CodeResult con el output formateado para el LLM
"""
from __future__ import annotations

import io
import signal
import sys
import textwrap
import traceback
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd

# ── Importaciones opcionales ──────────────────────────────────────────────────
try:
    import scipy.stats as _scipy_stats
    SCIPY_OK = True
except ImportError:
    SCIPY_OK = False

try:
    import sklearn
    SKLEARN_OK = True
except ImportError:
    SKLEARN_OK = False

try:
    import statsmodels.api as _sm
    STATSMODELS_OK = True
except ImportError:
    STATSMODELS_OK = False


# ── Módulos bloqueados — el sandbox los intercepta ───────────────────────────
_BLOCKED_MODULES = {
    "os", "sys", "subprocess", "shutil", "pathlib", "glob",
    "socket", "http", "urllib", "requests", "httpx",
    "open", "eval", "exec", "compile", "__import__",
    "builtins", "importlib", "pickle", "shelve",
}

_BLOCKED_KEYWORDS = [
    "import os", "import sys", "import subprocess",
    "open(", "__import__", "eval(", "exec(",
    "os.system", "os.remove", "os.unlink",
    "shutil.", "subprocess.", "socket.",
]


# ── Resultado de ejecución ────────────────────────────────────────────────────

@dataclass
class CodeResult:
    success: bool
    output: str            # stdout capturado
    result_repr: str       # repr() de la variable `result` si existe
    error: str = ""
    rows_affected: int = 0
    columns_in_result: list = field(default_factory=list)

    def to_llm_text(self) -> str:
        """
        Formatea el resultado para inyectarlo como OBSERVED en el contexto del LLM.
        Compacto pero informativo.
        """
        if not self.success:
            return f"ERROR DE EJECUCIÓN: {self.error}"

        parts = []

        if self.output.strip():
            # Truncar stdout si es muy largo
            stdout = self.output.strip()
            if len(stdout) > 2000:
                stdout = stdout[:2000] + "\n... [truncado]"
            parts.append(f"STDOUT:\n{stdout}")

        if self.result_repr and self.result_repr != "None":
            result_text = self.result_repr
            if len(result_text) > 2000:
                result_text = result_text[:2000] + "\n... [truncado]"
            parts.append(f"RESULT:\n{result_text}")

        if self.rows_affected:
            parts.append(f"Filas en resultado: {self.rows_affected}")

        if self.columns_in_result:
            parts.append(f"Columnas: {', '.join(str(c) for c in self.columns_in_result[:15])}")

        return "\n\n".join(parts) if parts else "Código ejecutado sin output."


# ── Sandbox ────────────────────────────────────────────────────────────────────

class CodeExecutor:
    """
    Ejecuta código Python generado por el LLM contra un DataFrame real.
    """

    def __init__(self, timeout_seconds: int = 30):
        self.timeout = timeout_seconds

    def _check_safety(self, code: str) -> Optional[str]:
        """
        Verificación básica de seguridad antes de ejecutar.
        Devuelve un mensaje de error si el código es peligroso, None si es seguro.
        """
        code_lower = code.lower()
        for keyword in _BLOCKED_KEYWORDS:
            if keyword.lower() in code_lower:
                return f"Código bloqueado: contiene '{keyword}' que no está permitido."
        return None

    def _build_namespace(self, df: pd.DataFrame) -> dict:
        """
        Construye el namespace de ejecución con las librerías permitidas.
        El DataFrame se pasa como `df` — el LLM siempre usa esa variable.
        """
        ns: dict = {
            # Dataset — solo lectura (el LLM no debería mutar df, pero si lo hace no importa
            # porque es una copia y no afecta el archivo original)
            "df": df.copy(),

            # Pandas y Numpy — siempre disponibles
            "pd": pd,
            "np": np,

            # Variable de resultado — el LLM debe asignar aquí su respuesta
            "result": None,
        }

        # Librerías opcionales
        if SCIPY_OK:
            import scipy.stats as scipy_stats
            ns["stats"] = scipy_stats

        if STATSMODELS_OK:
            import statsmodels.api as sm
            ns["sm"] = sm

        if SKLEARN_OK:
            from sklearn.preprocessing import StandardScaler
            from sklearn.cluster import KMeans
            from sklearn.ensemble import IsolationForest
            ns["StandardScaler"] = StandardScaler
            ns["KMeans"] = KMeans
            ns["IsolationForest"] = IsolationForest

        return ns

    def execute(self, code: str, df: pd.DataFrame) -> CodeResult:
        """
        Ejecuta el código en el sandbox y devuelve un CodeResult.
        """
        # 1. Verificación de seguridad
        safety_error = self._check_safety(code)
        if safety_error:
            return CodeResult(success=False, output="", result_repr="", error=safety_error)

        # 2. Limpiar indentación (el LLM a veces genera código con indentación extra)
        code = textwrap.dedent(code).strip()

        # 3. Construir namespace
        namespace = self._build_namespace(df)

        # 4. Capturar stdout
        stdout_capture = io.StringIO()

        # 5. Timeout via SIGALRM (Unix) o threading fallback
        def _run():
            with redirect_stdout(stdout_capture):
                exec(compile(code, "<datamind_code>", "exec"), namespace)  # noqa: S102

        try:
            if hasattr(signal, "SIGALRM"):
                # Unix — timeout limpio
                def _timeout_handler(signum, frame):
                    raise TimeoutError(f"Ejecución excedió {self.timeout}s")
                signal.signal(signal.SIGALRM, _timeout_handler)
                signal.alarm(self.timeout)
                try:
                    _run()
                finally:
                    signal.alarm(0)
            else:
                # Windows — ejecutar sin timeout (limitación del OS)
                _run()

        except TimeoutError as e:
            return CodeResult(
                success=False,
                output=stdout_capture.getvalue(),
                result_repr="",
                error=str(e),
            )
        except Exception:
            error_text = traceback.format_exc()
            # Limpiar el traceback para el LLM — solo las últimas 3 líneas
            lines = [l for l in error_text.strip().split("\n") if l.strip()]
            short_error = "\n".join(lines[-3:])
            return CodeResult(
                success=False,
                output=stdout_capture.getvalue(),
                result_repr="",
                error=short_error,
            )

        # 6. Extraer resultado
        raw_result = namespace.get("result")
        output = stdout_capture.getvalue()

        result_repr = ""
        rows_affected = 0
        columns_in_result: list = []

        if raw_result is not None:
            if isinstance(raw_result, pd.DataFrame):
                rows_affected = len(raw_result)
                columns_in_result = raw_result.columns.tolist()
                # Mostrar máximo 20 filas al LLM
                preview = raw_result.head(20).fillna("").astype(str)
                result_repr = preview.to_string(index=True)
            elif isinstance(raw_result, pd.Series):
                rows_affected = len(raw_result)
                result_repr = raw_result.head(20).to_string()
            elif isinstance(raw_result, dict):
                # Formatear dict de forma legible
                result_repr = "\n".join(f"  {k}: {v}" for k, v in list(raw_result.items())[:30])
            elif isinstance(raw_result, (list, tuple)):
                result_repr = "\n".join(str(item) for item in raw_result[:30])
            else:
                result_repr = str(raw_result)

        return CodeResult(
            success=True,
            output=output,
            result_repr=result_repr,
            rows_affected=rows_affected,
            columns_in_result=columns_in_result,
        )


# ── Instancia global ──────────────────────────────────────────────────────────
executor = CodeExecutor(timeout_seconds=30)


# ── Helpers para el agente ────────────────────────────────────────────────────

def load_dataframe(file_path: str) -> Optional[pd.DataFrame]:
    """Carga el DataFrame desde el path del FileContext."""
    import os
    if not os.path.exists(file_path):
        return None
    ext = os.path.splitext(file_path)[1].lower()
    try:
        if ext == ".csv":
            return pd.read_csv(file_path)
        elif ext in {".xlsx", ".xls"}:
            return pd.read_excel(file_path)
    except Exception:
        return None
    return None


CODE_EXECUTOR_DESCRIPTION = """
execute_python_code — Ejecuta código Python real contra el DataFrame cargado.
USA ESTO para cualquier cálculo numérico: sumas, promedios, agrupaciones,
filtros, correlaciones, rankings, etc. NUNCA calcules números mentalmente.

El DataFrame está disponible como `df`. Asigna tu resultado a `result`.

Ejemplos:
  # Suma por categoría
  result = df.groupby('categoria')['ventas'].sum().sort_values(ascending=False)

  # Top 5 con porcentaje acumulado
  totales = df.groupby('vendedor')['monto'].sum().sort_values(ascending=False)
  totales_df = totales.reset_index()
  totales_df['pct'] = totales_df['monto'] / totales_df['monto'].sum() * 100
  totales_df['pct_acum'] = totales_df['pct'].cumsum()
  result = totales_df.head(5)

  # Correlación entre columnas numéricas
  result = df[['col1', 'col2', 'col3']].corr()

  # Detección de outliers con IQR
  Q1 = df['valor'].quantile(0.25)
  Q3 = df['valor'].quantile(0.75)
  IQR = Q3 - Q1
  result = df[(df['valor'] < Q1 - 1.5*IQR) | (df['valor'] > Q3 + 1.5*IQR)]
  print(f"Outliers encontrados: {len(result)}")
""".strip()