"""
dashboard.py — Dashboard interactivo compartible por link

Genera un HTML standalone con gráficos Plotly que se puede servir por URL
y compartir con cualquier persona sin login.

Flujo:
  1. DashboardBuilder.build(ctx, insights) → HTML string
  2. save_dashboard(session_id, title, html) → uuid
  3. GET /dashboard/{uuid} → sirve el HTML directamente
"""
from __future__ import annotations

import json
import sqlite3
import textwrap
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

# ── DB path (reutiliza la misma DB de la app) ─────────────────────────────────
BASE_DIR = Path(__file__).resolve().parents[3]
DB_PATH  = BASE_DIR / "data_storage" / "datamind.db"


@contextmanager
def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_dashboard_table():
    with _conn() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS dashboards (
                uuid        TEXT PRIMARY KEY,
                session_id  TEXT NOT NULL,
                title       TEXT NOT NULL,
                html_content TEXT NOT NULL,
                created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_dash_session ON dashboards(session_id)"
        )


def save_dashboard(session_id: str, title: str, html_content: str) -> str:
    """Persiste el dashboard y devuelve su UUID."""
    dash_uuid = str(uuid.uuid4())
    with _conn() as con:
        con.execute(
            "INSERT INTO dashboards (uuid, session_id, title, html_content) VALUES (?,?,?,?)",
            (dash_uuid, session_id, title, html_content),
        )
    return dash_uuid


def get_dashboard(dash_uuid: str) -> Optional[Dict[str, str]]:
    with _conn() as con:
        row = con.execute(
            "SELECT uuid, session_id, title, html_content, created_at FROM dashboards WHERE uuid=?",
            (dash_uuid,),
        ).fetchone()
    if not row:
        return None
    return {"uuid": row[0], "session_id": row[1], "title": row[2],
            "html_content": row[3], "created_at": row[4]}


def list_dashboards(session_id: str) -> List[Dict[str, str]]:
    with _conn() as con:
        rows = con.execute(
            "SELECT uuid, title, created_at FROM dashboards WHERE session_id=? ORDER BY created_at DESC",
            (session_id,),
        ).fetchall()
    return [{"uuid": r[0], "title": r[1], "created_at": r[2]} for r in rows]


def delete_dashboard(dash_uuid: str) -> bool:
    with _conn() as con:
        cur = con.execute("DELETE FROM dashboards WHERE uuid=?", (dash_uuid,))
    return cur.rowcount > 0


# ── Chart data builders ───────────────────────────────────────────────────────

def _detect_date_col(df: pd.DataFrame) -> Optional[str]:
    for col in df.select_dtypes(include=["datetime", "datetimetz"]).columns:
        return col
    for col in df.select_dtypes(include="object").columns:
        try:
            parsed = pd.to_datetime(df[col], errors="coerce")
            if parsed.notnull().mean() > 0.7:
                df[col] = parsed
                return col
        except Exception:
            pass
    return None


def _build_chart_specs(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    Genera hasta 4 especificaciones de gráficos Plotly basadas en el dataset.
    Cada spec es un dict con {type, data, layout} listo para JSON.
    """
    specs = []
    num_cols = df.select_dtypes(include="number").columns.tolist()
    cat_cols = df.select_dtypes(include="object").columns.tolist()

    # ── Chart 1: Top categorías (bar) ─────────────────────────────────────────
    if cat_cols and num_cols:
        cat_col, num_col = cat_cols[0], num_cols[0]
        grouped = (df.groupby(cat_col)[num_col].sum()
                   .sort_values(ascending=False).head(12))
        if len(grouped) > 1:
            specs.append({
                "title": f"Top {cat_col} por {num_col}",
                "type": "bar",
                "data": [{
                    "x": grouped.index.tolist(),
                    "y": [round(float(v), 2) for v in grouped.values],
                    "type": "bar",
                    "marker": {
                        "color": [f"rgba(0,212,255,{0.6 + 0.4 * (1 - i/len(grouped))})"
                                  for i in range(len(grouped))],
                        "line": {"color": "#00d4ff", "width": 1},
                    },
                    "hovertemplate": "<b>%{x}</b><br>" + num_col + ": %{y:,.2f}<extra></extra>",
                }],
            })

    # ── Chart 2: Serie temporal (line) ────────────────────────────────────────
    date_col = _detect_date_col(df)
    if date_col and num_cols:
        try:
            ts_df = df.copy()
            ts_df[date_col] = pd.to_datetime(ts_df[date_col], errors="coerce")
            ts_df = ts_df.dropna(subset=[date_col]).set_index(date_col).sort_index()
            num_col = num_cols[0]
            monthly = ts_df[num_col].resample("ME").sum()
            if len(monthly) >= 3:
                specs.append({
                    "title": f"Tendencia mensual — {num_col}",
                    "type": "line",
                    "data": [{
                        "x": [str(d.date()) for d in monthly.index],
                        "y": [round(float(v), 2) for v in monthly.values],
                        "type": "scatter",
                        "mode": "lines+markers",
                        "line": {"color": "#00e5a0", "width": 2.5},
                        "marker": {"size": 5, "color": "#00e5a0"},
                        "fill": "tozeroy",
                        "fillcolor": "rgba(0,229,160,0.1)",
                        "hovertemplate": "%{x}<br>" + num_col + ": %{y:,.2f}<extra></extra>",
                    }],
                })
        except Exception:
            pass

    # ── Chart 3: Pie / donut ──────────────────────────────────────────────────
    if cat_cols and num_cols:
        cat_col, num_col = cat_cols[0], num_cols[0]
        grouped = (df.groupby(cat_col)[num_col].sum()
                   .sort_values(ascending=False).head(8))
        if 2 <= len(grouped) <= 10:
            labels = grouped.index.tolist()
            values = [round(float(v), 2) for v in grouped.values]
            if len(labels) > 7:
                labels, values = labels[:6] + ["Otros"], values[:6] + [round(sum(values[6:]), 2)]
            specs.append({
                "title": f"Composición — {num_col} por {cat_col}",
                "type": "pie",
                "data": [{
                    "labels": labels,
                    "values": values,
                    "type": "pie",
                    "hole": 0.4,
                    "marker": {
                        "colors": ["#00d4ff","#00e5a0","#ffb300","#a855f7",
                                   "#ff4560","#0066ff","#ff6b6b"],
                        "line": {"color": "#0e1724", "width": 2},
                    },
                    "textinfo": "percent",
                    "hovertemplate": "<b>%{label}</b><br>%{value:,.2f} (%{percent})<extra></extra>",
                }],
            })

    # ── Chart 4: Correlación heatmap ──────────────────────────────────────────
    if len(num_cols) >= 3:
        try:
            corr_df = df[num_cols[:8]].corr().round(2)
            z = corr_df.values.tolist()
            cols_list = corr_df.columns.tolist()
            specs.append({
                "title": "Mapa de correlaciones",
                "type": "heatmap",
                "data": [{
                    "z": z,
                    "x": cols_list,
                    "y": cols_list,
                    "type": "heatmap",
                    "colorscale": [
                        [0.0, "#ff4560"], [0.5, "#0e1724"], [1.0, "#00d4ff"]
                    ],
                    "zmid": 0,
                    "text": [[f"{v:.2f}" for v in row] for row in z],
                    "texttemplate": "%{text}",
                    "hovertemplate": "%{x} × %{y}: %{z:.2f}<extra></extra>",
                }],
            })
        except Exception:
            pass

    return specs


# ── HTML template ─────────────────────────────────────────────────────────────

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — DataMind</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
  :root {{
    --bg: #080d14; --surface: #0e1724; --surface2: #111d2e;
    --border: #1a2d42; --accent: #00d4ff; --green: #00e5a0;
    --amber: #ffb300; --text: #f0f4f8; --mid: #7a9ab8; --dim: #4a6885;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: "Inter", "Segoe UI", sans-serif; min-height: 100vh; }}

  .topbar {{
    background: var(--surface); border-bottom: 1px solid var(--border);
    padding: 14px 32px; display: flex; align-items: center; justify-content: space-between;
    position: sticky; top: 0; z-index: 100;
  }}
  .brand {{ display: flex; align-items: center; gap: 10px; }}
  .brand-dot {{ width: 8px; height: 8px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 8px var(--accent); }}
  .brand-name {{ font-size: 14px; font-weight: 700; letter-spacing: 2px; color: var(--accent); }}
  .report-title {{ font-size: 13px; color: var(--mid); }}
  .meta {{ font-size: 11px; color: var(--dim); }}

  .hero {{
    background: linear-gradient(135deg, var(--surface) 0%, var(--bg) 100%);
    border-bottom: 1px solid var(--border);
    padding: 40px 32px 32px;
  }}
  .hero h1 {{ font-size: 28px; font-weight: 700; color: var(--text); margin-bottom: 8px; }}
  .hero-meta {{ font-size: 12px; color: var(--dim); }}

  .kpi-row {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 12px; padding: 24px 32px;
  }}
  .kpi-card {{
    background: var(--surface2); border: 1px solid var(--border);
    border-radius: 8px; padding: 16px; text-align: center;
  }}
  .kpi-value {{ font-size: 26px; font-weight: 700; color: var(--accent); }}
  .kpi-label {{ font-size: 10px; color: var(--mid); letter-spacing: 1px; text-transform: uppercase; margin-top: 4px; }}

  .charts-grid {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(520px, 1fr));
    gap: 20px; padding: 0 32px 32px;
  }}
  .chart-card {{
    background: var(--surface2); border: 1px solid var(--border);
    border-radius: 10px; overflow: hidden;
  }}
  .chart-title {{
    padding: 14px 18px 10px;
    font-size: 13px; font-weight: 600; color: var(--mid);
    border-bottom: 1px solid var(--border);
  }}
  .chart-container {{ padding: 8px; }}

  .insights-section {{ padding: 0 32px 32px; }}
  .section-label {{
    font-size: 11px; letter-spacing: 2px; text-transform: uppercase;
    color: var(--accent); margin-bottom: 14px; display: flex; align-items: center; gap: 8px;
  }}
  .section-label::after {{ content: ""; flex: 1; height: 1px; background: var(--border); }}
  .insight-block {{
    background: var(--surface2); border: 1px solid var(--border);
    border-left: 3px solid var(--accent);
    border-radius: 8px; padding: 16px 18px; margin-bottom: 12px;
    font-size: 13px; line-height: 1.7; color: #cbd5e1;
  }}

  .warnings {{ padding: 0 32px; margin-bottom: 20px; }}
  .warning-item {{
    background: rgba(255,179,0,0.08); border: 1px solid rgba(255,179,0,0.25);
    border-radius: 6px; padding: 8px 14px; margin-bottom: 8px;
    font-size: 12px; color: var(--amber);
  }}

  .suggestions {{ padding: 0 32px 40px; }}
  .suggestion-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 10px; }}
  .suggestion-chip {{
    background: var(--surface2); border: 1px solid var(--border);
    border-radius: 8px; padding: 12px 16px;
    font-size: 12px; color: var(--mid); cursor: pointer;
    transition: all 0.2s; display: flex; align-items: flex-start; gap: 8px;
  }}
  .suggestion-chip:hover {{ border-color: var(--accent); color: var(--text); background: var(--surface); }}
  .suggestion-chip .num {{ color: var(--accent); font-weight: 700; min-width: 18px; }}

  .footer {{ text-align: center; padding: 24px; font-size: 11px; color: var(--dim); border-top: 1px solid var(--border); }}
</style>
</head>
<body>

<div class="topbar">
  <div class="brand">
    <div class="brand-dot"></div>
    <span class="brand-name">DATAMIND</span>
  </div>
  <span class="report-title">{title}</span>
  <span class="meta">{date_str}</span>
</div>

<div class="hero">
  <h1>{title}</h1>
  <div class="hero-meta">{file_name}  ·  Generado el {date_str}</div>
</div>

<div class="kpi-row">
{kpi_cards}
</div>

{warnings_html}

<div class="insights-section">
  <div class="section-label">Hallazgos Principales</div>
{insights_html}
</div>

<div class="charts-grid" id="charts">
{chart_placeholders}
</div>

{suggestions_html}

<div class="footer">DATAMIND 2.0 &nbsp;·&nbsp; Reporte generado automáticamente &nbsp;·&nbsp; {date_str}</div>

<script>
const chartSpecs = {chart_specs_json};
const plotlyLayout = {{
  paper_bgcolor: "#111d2e",
  plot_bgcolor:  "#0e1724",
  font:          {{ color: "#7a9ab8", family: "Inter, sans-serif", size: 11 }},
  xaxis:         {{ gridcolor: "#1a2d42", linecolor: "#1a2d42" }},
  yaxis:         {{ gridcolor: "#1a2d42", linecolor: "#1a2d42" }},
  margin:        {{ t: 20, b: 50, l: 50, r: 20 }},
  showlegend:    true,
  legend:        {{ bgcolor: "transparent", font: {{ color: "#7a9ab8", size: 10 }} }},
}};

chartSpecs.forEach((spec, i) => {{
  const el = document.getElementById("chart-" + i);
  if (!el) return;
  const layout = Object.assign({{}}, plotlyLayout, {{ title: "" }});
  if (spec.type === "pie") {{
    layout.paper_bgcolor = "#111d2e";
    delete layout.xaxis;
    delete layout.yaxis;
  }}
  if (spec.type === "heatmap") {{
    layout.margin = {{ t: 20, b: 80, l: 80, r: 20 }};
  }}
  Plotly.newPlot(el, spec.data, layout, {{
    responsive: true, displayModeBar: false
  }});
}});
</script>
</body>
</html>"""


# ── HTML component builders ───────────────────────────────────────────────────

def _kpi_cards_html(df: pd.DataFrame) -> str:
    num_df = df.select_dtypes(include="number")
    total_missing = int(df.isnull().sum().sum())
    quality = round(100 - total_missing / max(len(df) * len(df.columns), 1) * 100, 1)
    kpis = [
        (f"{len(df):,}", "Registros"),
        (f"{len(df.columns)}", "Variables"),
        (f"{quality}%", "Calidad"),
        (f"{len(num_df.columns)}", "Col. Numéricas"),
    ]
    return "\n".join(
        f'<div class="kpi-card"><div class="kpi-value">{val}</div>'
        f'<div class="kpi-label">{label}</div></div>'
        for val, label in kpis
    )


def _insights_html(insights: str) -> str:
    clean = (insights or "").replace("**", "").strip()
    parts = [p.strip() for p in clean.split("\n\n") if p.strip()]
    return "\n".join(
        f'<div class="insight-block">{p}</div>' for p in parts[:5]
    )


def _warnings_html(warnings: Optional[List[str]]) -> str:
    if not warnings:
        return ""
    items = "\n".join(f'<div class="warning-item">⚠  {w}</div>' for w in warnings[:4])
    return f'<div class="warnings">{items}</div>'


def _suggestions_html(questions: Optional[List[str]]) -> str:
    if not questions:
        return ""
    chips = "\n".join(
        f'<div class="suggestion-chip"><span class="num">{i+1}</span>{q}</div>'
        for i, q in enumerate(questions[:6])
    )
    return (
        f'<div class="suggestions">'
        f'<div class="section-label">Análisis Recomendados</div>'
        f'<div class="suggestion-grid">{chips}</div>'
        f'</div>'
    )


def _chart_placeholders_html(n_charts: int) -> str:
    return "\n".join(
        f'<div class="chart-card" id="card-{i}">'
        f'<div class="chart-title" id="title-{i}"></div>'
        f'<div class="chart-container"><div id="chart-{i}" style="height:340px;"></div></div>'
        f'</div>'
        for i in range(n_charts)
    )


# ── Main builder ───────────────────────────────────────────────────────────────

class DashboardBuilder:

    def build(
        self,
        file_path: str,
        title: str,
        insights: str,
        warnings: Optional[List[str]] = None,
        suggested_questions: Optional[List[str]] = None,
    ) -> str:
        """
        Genera el HTML standalone del dashboard.
        Devuelve el string HTML completo.
        """
        df = self._load_df(file_path)
        date_str = datetime.now().strftime("%d/%m/%Y %H:%M")

        if df is None:
            # Dashboard vacío con solo insights
            kpi_html = ""
            chart_placeholders = ""
            chart_specs_json = "[]"
        else:
            kpi_html = _kpi_cards_html(df)
            specs = _build_chart_specs(df)
            chart_placeholders = _chart_placeholders_html(len(specs))
            # Inyectar títulos en el JS specs para que el HTML los ponga
            chart_specs_json = json.dumps(specs, ensure_ascii=False)

            # Inyectar títulos en los placeholders via JS inline
            title_js_calls = "\n".join(
                f'document.getElementById("title-{i}").textContent = {json.dumps(s["title"])};'
                for i, s in enumerate(specs)
            )
            chart_specs_json_with_titles = chart_specs_json
            # Append title injection after plots
            extra_js = f"<script>{title_js_calls}</script>"
            chart_placeholders = chart_placeholders + extra_js

        html = _HTML_TEMPLATE.format(
            title=title or "Análisis de Datos",
            date_str=date_str,
            file_name=Path(file_path).name if file_path else "",
            kpi_cards=kpi_html,
            warnings_html=_warnings_html(warnings),
            insights_html=_insights_html(insights),
            chart_placeholders=chart_placeholders,
            chart_specs_json=chart_specs_json,
            suggestions_html=_suggestions_html(suggested_questions),
        )
        return html

    def _load_df(self, file_path: str) -> Optional[pd.DataFrame]:
        if not file_path:
            return None
        try:
            ext = Path(file_path).suffix.lower()
            if ext == ".csv":
                return pd.read_csv(file_path)
            elif ext in {".xlsx", ".xls"}:
                return pd.read_excel(file_path)
        except Exception:
            pass
        return None


# ── Instancia global + init ────────────────────────────────────────────────────
dashboard_builder = DashboardBuilder()
init_dashboard_table()