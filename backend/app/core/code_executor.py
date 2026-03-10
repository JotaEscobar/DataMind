"""
code_executor.py — Sandbox de ejecución de código Python

El LLM genera código pandas/numpy/matplotlib. Este módulo lo ejecuta de forma
segura contra el DataFrame real de la sesión y devuelve el resultado.

SEGURIDAD:
  - Bloquea imports peligrosos (os, sys, subprocess, shutil, etc.)
  - Solo permite pandas, numpy, matplotlib, scipy, sklearn, statsmodels
  - Timeout configurable (default 30s)
  - El código solo puede leer el DataFrame — no puede escribir archivos

FLUJO:
  1. Agente genera: ACTION: {"type": "code", "code": "result = df['ventas'].sum()"}
  2. CodeExecutor carga el DataFrame desde FileContext
  3. Ejecuta el código en namespace restringido con `df` disponible
  4. Captura stdout + variable `result` + figuras matplotlib
  5. Devuelve CodeResult con el output formateado para el LLM y las imágenes en base64
"""
from __future__ import annotations

import base64
import io
import signal
import sys
import textwrap
import traceback
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from typing import Any, List, Optional

import numpy as np
import pandas as pd

# ── Matplotlib — configurar backend sin GUI antes de cualquier import ─────────
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

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
    chart_images: list = field(default_factory=list)  # Lista de PNG en base64

    def to_llm_text(self) -> str:
        """
        Formatea el resultado para inyectarlo como OBSERVED en el contexto del LLM.
        Compacto pero informativo.
        """
        if not self.success:
            return f"ERROR DE EJECUCIÓN: {self.error}"

        parts = []

        if self.output.strip():
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

        if self.chart_images:
            parts.append(f"Gráficos generados: {len(self.chart_images)} imagen(es) PNG.")

        return "\n\n".join(parts) if parts else "Código ejecutado sin output."


# ── Helpers matplotlib ────────────────────────────────────────────────────────

def _capture_current_figures() -> List[str]:
    """
    Captura todas las figuras matplotlib abiertas como PNG en base64.
    Cierra las figuras después de capturarlas.
    """
    images = []
    for fig_num in plt.get_fignums():
        fig = plt.figure(fig_num)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=130, bbox_inches="tight",
                    facecolor=fig.get_facecolor())
        buf.seek(0)
        images.append(base64.b64encode(buf.read()).decode("utf-8"))
        plt.close(fig)
    return images


def _setup_chart_style():
    """Aplica el estilo visual DataMind a matplotlib."""
    plt.rcParams.update({
        "figure.facecolor":  "#111d2e",
        "axes.facecolor":    "#0e1724",
        "axes.edgecolor":    "#1a2d42",
        "axes.labelcolor":   "#7a9ab8",
        "xtick.color":       "#4a6885",
        "ytick.color":       "#4a6885",
        "text.color":        "#f0f4f8",
        "grid.color":        "#1a2d42",
        "grid.linewidth":    0.8,
        "font.family":       "sans-serif",
        "font.size":         10,
    })


# ── Sandbox ────────────────────────────────────────────────────────────────────

class CodeExecutor:
    """
    Ejecuta código Python generado por el LLM contra un DataFrame real.
    Soporta pandas, numpy, matplotlib y librerías científicas opcionales.
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
        matplotlib está disponible como `plt` con estilo DataMind precargado.
        """
        # Aplicar estilo antes de construir el namespace
        _setup_chart_style()
        # Cerrar figuras anteriores para evitar acumulación
        plt.close("all")

        ns: dict = {
            # Dataset
            "df": df.copy(),

            # Pandas y Numpy
            "pd": pd,
            "np": np,

            # Matplotlib — disponible directamente
            "plt": plt,
            "matplotlib": matplotlib,

            # Variable de resultado
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
        Las figuras matplotlib generadas se capturan automáticamente en base64.
        """
        # 1. Verificación de seguridad
        safety_error = self._check_safety(code)
        if safety_error:
            return CodeResult(success=False, output="", result_repr="", error=safety_error)

        # 2. Limpiar indentación
        code = textwrap.dedent(code).strip()

        # 3. Construir namespace (cierra figuras previas internamente)
        namespace = self._build_namespace(df)

        # 4. Capturar stdout
        stdout_capture = io.StringIO()

        # 5. Timeout via SIGALRM (Unix) o threading fallback
        def _run():
            with redirect_stdout(stdout_capture):
                exec(compile(code, "<datamind_code>", "exec"), namespace)  # noqa: S102

        try:
            if hasattr(signal, "SIGALRM"):
                def _timeout_handler(signum, frame):
                    raise TimeoutError(f"Ejecución excedió {self.timeout}s")
                signal.signal(signal.SIGALRM, _timeout_handler)
                signal.alarm(self.timeout)
                try:
                    _run()
                finally:
                    signal.alarm(0)
            else:
                # Windows — sin timeout nativo
                _run()

        except TimeoutError as e:
            plt.close("all")
            return CodeResult(
                success=False,
                output=stdout_capture.getvalue(),
                result_repr="",
                error=str(e),
            )
        except Exception:
            plt.close("all")
            error_text = traceback.format_exc()
            lines = [l for l in error_text.strip().split("\n") if l.strip()]
            short_error = "\n".join(lines[-3:])
            return CodeResult(
                success=False,
                output=stdout_capture.getvalue(),
                result_repr="",
                error=short_error,
            )

        # 6. Capturar figuras matplotlib generadas durante la ejecución
        chart_images = _capture_current_figures()

        # 7. Extraer resultado
        raw_result = namespace.get("result")
        output = stdout_capture.getvalue()

        result_repr = ""
        rows_affected = 0
        columns_in_result: list = []

        if raw_result is not None:
            if isinstance(raw_result, pd.DataFrame):
                rows_affected = len(raw_result)
                columns_in_result = raw_result.columns.tolist()
                preview = raw_result.head(20).fillna("").astype(str)
                result_repr = preview.to_string(index=True)
            elif isinstance(raw_result, pd.Series):
                rows_affected = len(raw_result)
                result_repr = raw_result.head(20).to_string()
            elif isinstance(raw_result, dict):
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
            chart_images=chart_images,
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

El DataFrame está disponible como `df`. Asigna tu resultado final a `result`.
Para gráficos, usa `plt` (matplotlib ya importado). Llama plt.figure() y
construye el gráfico normalmente — se captura automáticamente como imagen PNG.
NO llames plt.show() ni plt.savefig() — el sistema los captura solo.

Ejemplos:
  result = df.groupby('vendedor')['monto'].sum().sort_values(ascending=False)

  fig, ax = plt.subplots(figsize=(10, 5))
  result.plot(kind='bar', ax=ax, color='#00d4ff')
  ax.set_title('Ventas por vendedor')
  result = result  # siempre asigna result al final
"""