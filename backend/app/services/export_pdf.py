"""
export_pdf.py — Exportación PDF con gráficos reales y branding DataMind

Genera un reporte ejecutivo con:
  - Cover page con branding DataMind
  - Métricas clave del análisis
  - Gráficos reales (matplotlib → BytesIO → ReportLab)
  - Tabla de datos top
  - Sección de hallazgos e insights

Uso:
    from app.tools.export_pdf import build_pdf_report
    path = build_pdf_report(file_path, session_id, title, insights)
"""
from __future__ import annotations

import io
import os
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")  # sin GUI
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.flowables import HRFlowable

# ── DataMind color palette ─────────────────────────────────────────────────────
DM_DARK      = "#080d14"
DM_SURFACE   = "#0e1724"
DM_ACCENT    = "#00d4ff"
DM_ACCENT2   = "#4de4ff"
DM_GREEN     = "#00e5a0"
DM_AMBER     = "#ffb300"
DM_RED       = "#ff4560"
DM_PURPLE    = "#a855f7"
DM_TEXT      = "#f0f4f8"
DM_MID       = "#7a9ab8"
DM_WHITE     = "#ffffff"

# Paleta para gráficos
CHART_COLORS = [DM_ACCENT, DM_GREEN, DM_AMBER, DM_PURPLE, DM_RED,
                "#0066ff", "#ff6b6b", "#ffd93d", "#6bcb77", "#4d96ff"]

STORAGE_DIR = Path(__file__).resolve().parents[3] / "data_storage" / "exports"


# ── Matplotlib helper ──────────────────────────────────────────────────────────

def _setup_chart_style():
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
        "font.size":         9,
    })


def _fig_to_image(fig, width_cm: float = 16, height_cm: float = 8) -> Image:
    """Convierte figura matplotlib a Image de ReportLab."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    buf.seek(0)
    plt.close(fig)
    return Image(buf, width=width_cm * cm, height=height_cm * cm)


def _bar_chart(
    labels: List[str],
    values: List[float],
    title: str,
    xlabel: str = "",
    ylabel: str = "",
    horizontal: bool = False,
    color: str = DM_ACCENT,
) -> Image:
    _setup_chart_style()
    fig, ax = plt.subplots(figsize=(10, 5))
    fig.patch.set_facecolor("#111d2e")

    # Truncar labels largos
    labels = [str(l)[:20] for l in labels]
    x = range(len(labels))

    if horizontal:
        bars = ax.barh(labels, values, color=color, alpha=0.85, height=0.6)
        ax.set_xlabel(ylabel or "Valor", color="#7a9ab8")
        # Anotaciones
        for bar, val in zip(bars, values):
            ax.text(bar.get_width() * 1.01, bar.get_y() + bar.get_height() / 2,
                    f"{val:,.0f}", va="center", fontsize=8, color="#f0f4f8")
    else:
        bars = ax.bar(x, values, color=color, alpha=0.85, width=0.6)
        ax.set_xticks(list(x))
        ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
        ax.set_ylabel(ylabel or "Valor", color="#7a9ab8")
        for bar, val in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() * 1.01,
                    f"{val:,.0f}", ha="center", fontsize=7, color="#f0f4f8")

    ax.set_title(title, color="#f0f4f8", fontsize=11, pad=10)
    if xlabel:
        ax.set_xlabel(xlabel, color="#7a9ab8")
    ax.grid(axis="x" if horizontal else "y", alpha=0.3)
    ax.spines[:].set_visible(False)
    fig.tight_layout()
    return _fig_to_image(fig, 16, 7)


def _line_chart(
    x_values: List,
    y_values: List[float],
    title: str,
    x_label: str = "",
    y_label: str = "",
    color: str = DM_ACCENT,
) -> Image:
    _setup_chart_style()
    fig, ax = plt.subplots(figsize=(10, 5))
    fig.patch.set_facecolor("#111d2e")

    ax.plot(range(len(x_values)), y_values, color=color, linewidth=2.5,
            marker="o", markersize=4, markerfacecolor=color)
    ax.fill_between(range(len(x_values)), y_values, alpha=0.15, color=color)

    step = max(1, len(x_values) // 10)
    ax.set_xticks(range(0, len(x_values), step))
    ax.set_xticklabels([str(x_values[i])[:12] for i in range(0, len(x_values), step)],
                       rotation=30, ha="right", fontsize=8)
    ax.set_title(title, color="#f0f4f8", fontsize=11, pad=10)
    if x_label: ax.set_xlabel(x_label, color="#7a9ab8")
    if y_label: ax.set_ylabel(y_label, color="#7a9ab8")
    ax.grid(axis="y", alpha=0.3)
    ax.spines[:].set_visible(False)
    fig.tight_layout()
    return _fig_to_image(fig, 16, 7)


def _pie_chart(labels: List[str], values: List[float], title: str) -> Image:
    _setup_chart_style()
    fig, ax = plt.subplots(figsize=(7, 5))
    fig.patch.set_facecolor("#111d2e")

    # Máximo 7 categorías, resto agrupado
    if len(labels) > 7:
        top_labels, top_values = labels[:6], values[:6]
        others = sum(values[6:])
        top_labels.append("Otros")
        top_values.append(others)
        labels, values = top_labels, top_values

    wedges, texts, autotexts = ax.pie(
        values,
        labels=None,
        autopct="%1.1f%%",
        colors=CHART_COLORS[:len(values)],
        startangle=90,
        wedgeprops={"edgecolor": "#0e1724", "linewidth": 1.5},
        pctdistance=0.8,
    )
    for at in autotexts:
        at.set_color("#f0f4f8")
        at.set_fontsize(8)

    ax.legend(wedges, [str(l)[:18] for l in labels],
              loc="lower center", bbox_to_anchor=(0.5, -0.15),
              ncol=3, fontsize=7, frameon=False,
              labelcolor="#7a9ab8")
    ax.set_title(title, color="#f0f4f8", fontsize=11, pad=10)
    fig.tight_layout()
    return _fig_to_image(fig, 12, 7)


# ── ReportLab styles ───────────────────────────────────────────────────────────

def _build_styles() -> dict:
    base = getSampleStyleSheet()
    c = colors.HexColor

    return {
        "cover_title": ParagraphStyle("cover_title",
            fontSize=28, fontName="Helvetica-Bold",
            textColor=c(DM_ACCENT), spaceAfter=8, alignment=TA_LEFT),
        "cover_sub": ParagraphStyle("cover_sub",
            fontSize=13, fontName="Helvetica",
            textColor=c(DM_MID), spaceAfter=6, alignment=TA_LEFT),
        "cover_meta": ParagraphStyle("cover_meta",
            fontSize=9, fontName="Helvetica",
            textColor=c(DM_MID), alignment=TA_LEFT),
        "section_title": ParagraphStyle("section_title",
            fontSize=14, fontName="Helvetica-Bold",
            textColor=c(DM_ACCENT), spaceBefore=16, spaceAfter=8),
        "body": ParagraphStyle("body",
            fontSize=9, fontName="Helvetica",
            textColor=c("#cbd5e1"), leading=14, spaceAfter=6),
        "insight": ParagraphStyle("insight",
            fontSize=9.5, fontName="Helvetica",
            textColor=c("#e2e8f0"), leading=15, spaceAfter=8,
            leftIndent=12, borderPad=8,
            borderColor=c(DM_ACCENT), borderWidth=2,
            borderRadius=4, backColor=c("#0e1724")),
        "kpi_label": ParagraphStyle("kpi_label",
            fontSize=8, fontName="Helvetica",
            textColor=c(DM_MID), alignment=TA_CENTER),
        "kpi_value": ParagraphStyle("kpi_value",
            fontSize=18, fontName="Helvetica-Bold",
            textColor=c(DM_ACCENT), alignment=TA_CENTER),
        "footer": ParagraphStyle("footer",
            fontSize=7, fontName="Helvetica",
            textColor=c("#2d4a6a"), alignment=TA_CENTER),
        "warning": ParagraphStyle("warning",
            fontSize=8.5, fontName="Helvetica",
            textColor=c(DM_AMBER), leftIndent=10, spaceAfter=4),
    }


# ── Page templates ─────────────────────────────────────────────────────────────

def _make_cover_bg(canvas, doc):
    """Fondo oscuro DataMind para la portada."""
    w, h = A4
    canvas.saveState()
    canvas.setFillColor(colors.HexColor(DM_DARK))
    canvas.rect(0, 0, w, h, fill=1, stroke=0)
    # Franja de acento vertical izquierda
    canvas.setFillColor(colors.HexColor(DM_ACCENT))
    canvas.rect(0, 0, 4 * mm, h, fill=1, stroke=0)
    # Bloque de color superior
    canvas.setFillColor(colors.HexColor(DM_SURFACE))
    canvas.rect(0, h * 0.55, w, h * 0.45, fill=1, stroke=0)
    # Grid decorativo (dots)
    canvas.setFillColor(colors.HexColor("#1a2d42"))
    for col in range(6, int(w), 20):
        for row in range(6, int(h * 0.55), 20):
            canvas.circle(col, row, 1, fill=1, stroke=0)
    canvas.restoreState()


def _make_inner_bg(canvas, doc):
    """Fondo para páginas interiores."""
    w, h = A4
    canvas.saveState()
    canvas.setFillColor(colors.HexColor("#0a0f1a"))
    canvas.rect(0, 0, w, h, fill=1, stroke=0)
    # Franja izquierda
    canvas.setFillColor(colors.HexColor(DM_ACCENT))
    canvas.rect(0, 0, 2 * mm, h, fill=1, stroke=0)
    # Footer line
    canvas.setStrokeColor(colors.HexColor("#1a2d42"))
    canvas.setLineWidth(0.5)
    canvas.line(1.5 * cm, 1.5 * cm, w - 1.5 * cm, 1.5 * cm)
    # Footer text
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#2d4a6a"))
    canvas.drawString(1.5 * cm, 1.1 * cm, "DATAMIND 2.0  ·  Reporte Confidencial")
    canvas.drawRightString(w - 1.5 * cm, 1.1 * cm, f"Pág. {doc.page}")
    canvas.restoreState()


# ── KPI card row ───────────────────────────────────────────────────────────────

def _kpi_table(kpis: List[Tuple[str, str]], styles: dict) -> Table:
    """Fila de tarjetas KPI: [(label, valor), ...]"""
    headers = [Paragraph(k[0], styles["kpi_label"]) for k in kpis]
    values  = [Paragraph(k[1], styles["kpi_value"])  for k in kpis]
    t = Table([headers, values], colWidths=[A4[0] / len(kpis) - 1.2 * cm] * len(kpis))
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor("#0e1724")),
        ("ROWBACKGROUNDS",(0, 0), (-1, -1), [colors.HexColor("#111d2e")]),
        ("BOX",           (0, 0), (-1, -1), 1, colors.HexColor("#1a2d42")),
        ("INNERGRID",     (0, 0), (-1, -1), 0.5, colors.HexColor("#1a2d42")),
        ("TOPPADDING",    (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
    ]))
    return t


# ── Data table ─────────────────────────────────────────────────────────────────

def _data_table(df_preview: pd.DataFrame) -> Table:
    cols = df_preview.columns.tolist()
    rows = df_preview.head(15).fillna("").astype(str).values.tolist()
    data = [cols] + rows

    col_w = max(2.5 * cm, (A4[0] - 3 * cm) / max(len(cols), 1))
    col_widths = [min(col_w, 4 * cm)] * len(cols)

    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), colors.HexColor("#0e1724")),
        ("TEXTCOLOR",     (0, 0), (-1, 0), colors.HexColor(DM_ACCENT)),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, 0), 8),
        ("FONTSIZE",      (0, 1), (-1, -1), 7.5),
        ("TEXTCOLOR",     (0, 1), (-1, -1), colors.HexColor("#cbd5e1")),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1),
         [colors.HexColor("#0e1724"), colors.HexColor("#111d2e")]),
        ("GRID",          (0, 0), (-1, -1), 0.4, colors.HexColor("#1a2d42")),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("ALIGN",         (0, 0), (-1, -1), "LEFT"),
        ("ROWBACKGROUNDS",(0, 0), (0, -1),  [colors.HexColor("#0e1724")]),
    ]))
    return t


# ── Main builder ───────────────────────────────────────────────────────────────

def build_pdf_report(
    file_path: str,
    session_id: str,
    title: str,
    insights: str,
    warnings: Optional[List[str]] = None,
    suggested_questions: Optional[List[str]] = None,
) -> str:
    """
    Construye el PDF completo y devuelve la ruta del archivo generado.

    Parámetros:
        file_path   : ruta del CSV/XLSX de datos
        session_id  : ID de la sesión (para nombre de archivo)
        title       : título del reporte
        insights    : narrativa principal generada por el LLM
        warnings    : alertas de calidad del dataset
        suggested_questions: preguntas sugeridas para continuar el análisis
    """
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = str(STORAGE_DIR / f"datamind_{session_id[:8]}_{timestamp}.pdf")

    # Cargar datos
    df = _load_df(file_path)

    # ── Documento ────────────────────────────────────────────────────────────
    doc = BaseDocTemplate(
        out_path,
        pagesize=A4,
        leftMargin=1.8 * cm,
        rightMargin=1.8 * cm,
        topMargin=2 * cm,
        bottomMargin=2.5 * cm,
    )

    cover_frame = Frame(
        doc.leftMargin, doc.bottomMargin,
        doc.width, doc.height,
        id="cover",
    )
    inner_frame = Frame(
        doc.leftMargin, doc.bottomMargin,
        doc.width, doc.height,
        id="inner",
    )
    doc.addPageTemplates([
        PageTemplate(id="Cover", frames=[cover_frame], onPage=_make_cover_bg),
        PageTemplate(id="Inner", frames=[inner_frame], onPage=_make_inner_bg),
    ])

    styles = _build_styles()
    story = []

    # ── COVER ─────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 4 * cm))
    story.append(Paragraph("DATAMIND 2.0", styles["cover_meta"]))
    story.append(Spacer(1, 0.4 * cm))
    # Título envuelto
    for line in textwrap.wrap(title or "Reporte de Análisis", 40):
        story.append(Paragraph(line, styles["cover_title"]))
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph(
        f"Análisis ejecutivo generado el {datetime.now().strftime('%d de %B de %Y')}",
        styles["cover_sub"],
    ))
    if df is not None:
        story.append(Paragraph(
            f"{len(df):,} registros  ·  {len(df.columns)} variables  ·  {Path(file_path).name}",
            styles["cover_meta"],
        ))
    story.append(Spacer(1, 1 * cm))
    story.append(HRFlowable(
        width="100%", thickness=1,
        color=colors.HexColor(DM_ACCENT), spaceAfter=8,
    ))

    # ── KPIs del dataset ─────────────────────────────────────────────────────
    if df is not None:
        num_df = df.select_dtypes(include="number")
        total_missing = int(df.isnull().sum().sum())
        quality = round(100 - total_missing / max(len(df) * len(df.columns), 1) * 100, 1)
        kpis = [
            ("REGISTROS", f"{len(df):,}"),
            ("VARIABLES", f"{len(df.columns)}"),
            ("CALIDAD DATO", f"{quality}%"),
            ("COLUMNAS NUM.", f"{len(num_df.columns)}"),
        ]
        story.append(Spacer(1, 0.8 * cm))
        story.append(_kpi_table(kpis, styles))

    story.append(PageBreak())
    story.append(NextPageTemplate("Inner"))

    # ── INSIGHTS ──────────────────────────────────────────────────────────────
    story.append(Paragraph("Hallazgos Principales", styles["section_title"]))
    story.append(HRFlowable(width="100%", thickness=0.5,
                            color=colors.HexColor("#1a2d42"), spaceAfter=8))

    # Limpiar markdown y dividir en párrafos
    clean_insights = (insights or "Sin análisis disponible.").replace("**", "")
    for para in clean_insights.split("\n\n"):
        para = para.strip()
        if para:
            story.append(Paragraph(para, styles["insight"]))
            story.append(Spacer(1, 0.2 * cm))

    # Alertas de calidad
    if warnings:
        story.append(Spacer(1, 0.3 * cm))
        story.append(Paragraph("⚠ Alertas de Calidad", styles["section_title"]))
        for w in warnings:
            story.append(Paragraph(f"• {w}", styles["warning"]))

    # ── GRÁFICOS ──────────────────────────────────────────────────────────────
    if df is not None:
        num_cols = df.select_dtypes(include="number").columns.tolist()
        cat_cols = df.select_dtypes(include="object").columns.tolist()

        story.append(PageBreak())
        story.append(Paragraph("Análisis Visual", styles["section_title"]))
        story.append(HRFlowable(width="100%", thickness=0.5,
                                color=colors.HexColor("#1a2d42"), spaceAfter=12))

        charts_added = 0

        # Gráfico 1: top categoría por valor numérico
        if cat_cols and num_cols:
            cat_col = cat_cols[0]
            num_col = num_cols[0]
            grouped = (
                df.groupby(cat_col)[num_col]
                .sum()
                .sort_values(ascending=False)
                .head(10)
            )
            if len(grouped) > 1:
                img = _bar_chart(
                    grouped.index.tolist(), grouped.values.tolist(),
                    f"Top 10 — {num_col} por {cat_col}",
                    ylabel=num_col, horizontal=len(grouped) > 5,
                    color=DM_ACCENT,
                )
                story.append(img)
                story.append(Spacer(1, 0.5 * cm))
                charts_added += 1

        # Gráfico 2: serie temporal si hay fechas
        date_col = _detect_date_col(df)
        if date_col and num_cols:
            try:
                ts_df = df.copy()
                ts_df[date_col] = pd.to_datetime(ts_df[date_col], errors="coerce")
                ts_df = ts_df.dropna(subset=[date_col])
                ts_df = ts_df.set_index(date_col).sort_index()
                num_col = num_cols[0]
                monthly = ts_df[num_col].resample("ME").sum()
                if len(monthly) >= 3:
                    img = _line_chart(
                        [str(d.strftime("%b %Y")) for d in monthly.index],
                        monthly.values.tolist(),
                        f"Tendencia mensual — {num_col}",
                        y_label=num_col,
                        color=DM_GREEN,
                    )
                    story.append(img)
                    story.append(Spacer(1, 0.5 * cm))
                    charts_added += 1
            except Exception:
                pass

        # Gráfico 3: distribución de la variable numérica principal
        if num_cols and charts_added < 3:
            col = num_cols[0]
            series = df[col].dropna()
            if len(series) > 10:
                _setup_chart_style()
                fig, ax = plt.subplots(figsize=(10, 4))
                fig.patch.set_facecolor("#111d2e")
                ax.hist(series, bins=30, color=DM_ACCENT, alpha=0.75, edgecolor="#0e1724")
                ax.set_title(f"Distribución — {col}", color="#f0f4f8", fontsize=11, pad=10)
                ax.set_xlabel(col, color="#7a9ab8")
                ax.set_ylabel("Frecuencia", color="#7a9ab8")
                ax.grid(axis="y", alpha=0.3)
                ax.spines[:].set_visible(False)
                fig.tight_layout()
                story.append(_fig_to_image(fig, 16, 6))
                story.append(Spacer(1, 0.5 * cm))

        # Gráfico 4: donut de categorías si aplica
        if cat_cols and num_cols:
            try:
                cat_col = cat_cols[0]
                num_col = num_cols[0]
                grouped = (
                    df.groupby(cat_col)[num_col]
                    .sum()
                    .sort_values(ascending=False)
                    .head(7)
                )
                if 2 <= len(grouped) <= 10:
                    img = _pie_chart(
                        grouped.index.tolist(),
                        grouped.values.tolist(),
                        f"Composición — {num_col} por {cat_col}",
                    )
                    story.append(img)
                    story.append(Spacer(1, 0.5 * cm))
            except Exception:
                pass

    # ── MUESTRA DE DATOS ──────────────────────────────────────────────────────
    if df is not None and len(df) > 0:
        story.append(PageBreak())
        story.append(Paragraph("Muestra de Datos", styles["section_title"]))
        story.append(HRFlowable(width="100%", thickness=0.5,
                                color=colors.HexColor("#1a2d42"), spaceAfter=12))
        story.append(Paragraph(
            f"Primeros 15 registros de {len(df):,} totales.",
            styles["body"],
        ))
        story.append(Spacer(1, 0.3 * cm))
        story.append(_data_table(df))

    # ── PRÓXIMOS PASOS ────────────────────────────────────────────────────────
    if suggested_questions:
        story.append(PageBreak())
        story.append(Paragraph("Análisis Recomendados", styles["section_title"]))
        story.append(HRFlowable(width="100%", thickness=0.5,
                                color=colors.HexColor("#1a2d42"), spaceAfter=12))
        for i, q in enumerate(suggested_questions, 1):
            story.append(Paragraph(f"{i}. {q}", styles["body"]))
            story.append(Spacer(1, 0.15 * cm))

    doc.build(story)
    return out_path


def _load_df(file_path: str) -> Optional[pd.DataFrame]:
    try:
        ext = Path(file_path).suffix.lower()
        if ext == ".csv":
            return pd.read_csv(file_path)
        elif ext in {".xlsx", ".xls"}:
            return pd.read_excel(file_path)
    except Exception:
        pass
    return None


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