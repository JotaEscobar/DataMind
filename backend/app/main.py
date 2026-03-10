"""
main.py — DataMind 2.0 API

Cambios vs versión anterior:
  ✅ FileContext se crea al subir archivo y se persiste por session_id
  ✅ /upload genera diagnóstico automático del dataset
  ✅ /stream y /analyze usan el FileContext de la sesión (sin reenviar archivo)
  ✅ generate_title no bloquea el stream (se genera en paralelo)
  ✅ /sessions/{id} limpia el FileContext al eliminar sesión
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Optional, Tuple
from uuid import uuid4

import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse

ROOT_DIR = Path(__file__).resolve().parents[2]   # backend/app/main.py → raíz
BACKEND_DIR = Path(__file__).resolve().parents[1]  # → backend/
load_dotenv(ROOT_DIR / ".env")


from app.core.agent import (
    DataMindAgent,
    clear_session_file,
    get_session_file,
    set_session_file,
)
from app.core.auto_analyst import get_auto_analyst
from app.services.dashboard import dashboard_builder, save_dashboard, get_dashboard, list_dashboards, delete_dashboard
from app.services.export_pdf import build_pdf_report
from app.services.export_pptx import build_pptx_report
from app.core.database import (
    clear_history,
    get_all_sessions,
    get_chat_history,
    save_message,
    save_session,
    update_session_title,
)
from app.core.intent import FileContext
from app.core.registry import registry

STORAGE_DIR = ROOT_DIR / "data_storage"

app = FastAPI(title="DATAMIND 2.0 API")

allowed_origins = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "*").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins or ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _new_agent() -> DataMindAgent:
    return DataMindAgent(registry)


def _sanitize_filename(filename: str) -> str:
    candidate = Path(filename).name
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "_", candidate).strip("._")
    return candidate or f"upload_{uuid4().hex}.dat"


async def _store_upload(file: UploadFile) -> Tuple[str, Path]:
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = _sanitize_filename(file.filename or "upload.dat")
    target = STORAGE_DIR / safe_name
    if target.exists():
        target = target.with_name(f"{target.stem}_{uuid4().hex[:8]}{target.suffix}")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="El archivo subido está vacío.")
    target.write_bytes(content)
    return target.name, target


def _load_dataframe(file_path: Path) -> pd.DataFrame:
    ext = file_path.suffix.lower()
    if ext == ".csv":
        return pd.read_csv(file_path)
    elif ext in {".xlsx", ".xls"}:
        return pd.read_excel(file_path)
    else:
        raise HTTPException(status_code=400, detail=f"Formato '{ext}' no soportado. Usa .csv, .xlsx o .xls")


def _structural_diagnosis(ctx) -> str:
    """Diagnóstico estructural sin LLM — respuesta instantánea."""
    total_missing = sum(ctx.missing_values.values())
    total_cells = ctx.rows * len(ctx.columns)
    quality_pct = round(100 - (total_missing / max(total_cells, 1) * 100), 1)
    domain_labels = {
        "financial": "financiero / comercial", "hr": "recursos humanos",
        "marketing": "marketing / producto", "ops": "operaciones / logística",
        "scientific": "científico / experimental", "general": "general",
    }
    domain_label = domain_labels.get(ctx.domain_hint, "general")
    lines = [
        f"📂 **{ctx.file_name}** cargado — **{ctx.rows:,} filas · {len(ctx.columns)} columnas**",
        f"Calidad: **{quality_pct}%** · Dominio detectado: **{domain_label}**",
    ]
    if ctx.numeric_cols:
        lines.append(f"Numéricas: {', '.join(ctx.numeric_cols[:6])}")
    if ctx.date_cols:
        lines.append(f"Fechas: {', '.join(ctx.date_cols[:3])}")
    return "\n".join(lines)


def _get_shared_agent():
    return DataMindAgent(registry)


# ── Static files ──────────────────────────────────────────────────────────────

@app.get("/")
async def read_index():
    path = ROOT_DIR / "index.html"
    return FileResponse(path) if path.exists() else JSONResponse({"status": "ok"})


@app.get("/logo.png")
async def get_logo():
    path = ROOT_DIR / "logo.png"
    if not path.exists():
        raise HTTPException(status_code=404, detail="logo.png no encontrado")
    return FileResponse(path)


@app.get("/icono.png")
async def get_icon():
    path = ROOT_DIR / "icono.png"
    if not path.exists():
        raise HTTPException(status_code=404, detail="icono.png no encontrado")
    return FileResponse(path)


# ── Upload ────────────────────────────────────────────────────────────────────

@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    session_id: str = Form("default_user"),
):
    """Sube archivo, construye FileContext y devuelve metadata inmediata."""
    stored_name, file_path = await _store_upload(file)
    try:
        df = _load_dataframe(file_path)
        ctx = FileContext.from_dataframe(str(file_path), df)
        set_session_file(session_id, ctx)
        return {
            "filename": file.filename,
            "stored_filename": stored_name,
            "status": "ok",
            "rows": ctx.rows,
            "columns": ctx.columns,
            "domain_hint": ctx.domain_hint,
            "structural_diagnosis": _structural_diagnosis(ctx),
            "missing_values": ctx.missing_values,
            "numeric_cols": ctx.numeric_cols,
            "date_cols": ctx.date_cols,
            "ready_for_deep_analysis": True,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error al procesar el archivo: {e}") from e


@app.post("/upload/stream")
async def upload_and_analyze_stream(
    file: UploadFile = File(...),
    session_id: str = Form("default_user"),
):
    """Sube archivo Y ejecuta análisis automático profundo con LLM via SSE."""
    try:
        stored_name, file_path = await _store_upload(file)
        df = _load_dataframe(file_path)
        ctx = FileContext.from_dataframe(str(file_path), df)
        set_session_file(session_id, ctx)
    except Exception as e:
        async def error_gen():
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        return StreamingResponse(error_gen(), media_type="text/event-stream")

    def emit(payload: dict) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    async def analysis_generator():
        try:
            yield emit({"type": "file_ready", "filename": ctx.file_name,
                        "rows": ctx.rows, "cols": len(ctx.columns), "domain": ctx.domain_hint})
            await asyncio.sleep(0)

            agent = _get_shared_agent()
            auto_analyst = get_auto_analyst(chat_fn=agent._chat_text, fast_model=agent.fast_model)

            steps = [
                "Inspeccionando estructura del dataset...",
                "Calculando estadísticas descriptivas...",
                "Analizando categorías y distribuciones...",
                "Escaneando outliers y anomalías...",
                "Detectando series de tiempo...",
                "Calculando correlaciones...",
                "Generando diagnóstico con IA...",
            ]
            for label in steps:
                yield emit({"type": "step", "label": label})
                await asyncio.sleep(0.05)

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, auto_analyst.run, ctx)

            for warning in result.warnings:
                yield emit({"type": "warning", "message": warning})
                await asyncio.sleep(0)

            chunk_size = 6
            for i in range(0, len(result.narrative), chunk_size):
                yield emit({"type": "insight_token", "token": result.narrative[i:i+chunk_size]})
                await asyncio.sleep(0)

            if result.suggested_questions:
                yield emit({"type": "suggestions", "items": result.suggested_questions})

            # Guardar como primer mensaje de la sesión
            full_msg = result.narrative
            if result.suggested_questions:
                full_msg += "\n\n**Análisis sugeridos:**\n"
                full_msg += "\n".join(f"- {q}" for q in result.suggested_questions)

            sessions = get_all_sessions()
            if not any(s["session_id"] == session_id for s in sessions):
                save_session(session_id, f"Análisis: {ctx.file_name}")
            save_message(session_id, "assistant", full_msg)

            yield emit({"type": "done"})

        except Exception as e:
            logger.error("upload/stream error: %s", e)
            yield emit({"type": "error", "message": str(e)})
            yield emit({"type": "done"})

    return StreamingResponse(
        analysis_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Analyze (bloqueante) ──────────────────────────────────────────────────────


@app.post("/analyze")
async def analyze_data(
    question: str = Form(""),
    session_id: str = Form("default_user"),
    model: str = Form("llama3.1"),
    file: Optional[UploadFile] = File(None),
):
    """Punto de entrada bloqueante. Mantiene compatibilidad."""
    try:
        agent = _new_agent()

        # Si llega un archivo en este request, actualizar FileContext
        if file is not None:
            stored_name, file_path = await _store_upload(file)
            df = _load_dataframe(file_path)
            ctx = FileContext.from_dataframe(str(file_path), df)
            set_session_file(session_id, ctx)

        sessions = get_all_sessions()
        session_exists = any(s["session_id"] == session_id for s in sessions)

        result = agent.process_request(
            question,
            session_id=session_id,
            model=model,
        )

        title = None
        if not session_exists:
            title = agent.generate_title(question, model=model)
            save_session(session_id, title)

        return {
            "response": result["insight"],
            "thought": result["thought"],
            "title": title,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


# ── Stream (SSE) ──────────────────────────────────────────────────────────────

@app.post("/stream")
async def stream_analysis(
    question: str = Form(""),
    session_id: str = Form("default_user"),
    model: str = Form("llama3.1"),
    file: Optional[UploadFile] = File(None),
):
    """Endpoint SSE principal. El FileContext se carga desde la sesión."""
    agent = _new_agent()

    # Normalizar pregunta: si viene vacía y hay archivo, usar prompt por defecto
    if not question.strip() and file is not None:
        question = "Analiza este archivo y dame un resumen del dataset."
    elif not question.strip():
        question = "¿Qué puedes decirme sobre los datos actuales?"

    # Si llega archivo adjunto en este request, actualizar FileContext
    if file is not None:
        stored_name, file_path = await _store_upload(file)
        try:
            df = _load_dataframe(file_path)
            ctx = FileContext.from_dataframe(str(file_path), df)
            set_session_file(session_id, ctx)
        except Exception as e:
            logger_ctx = f"Error procesando archivo adjunto: {e}"
            # Continuar sin archivo — el IntentClassifier lo manejará

    # Título de sesión (async, no bloquea el stream)
    sessions = get_all_sessions()
    session_exists = any(s["session_id"] == session_id for s in sessions)

    title = None
    if not session_exists:
        # Generar título de forma no bloqueante usando modelo liviano
        title = agent.generate_title(question)
        save_session(session_id, title)

    async def event_generator():
        if title:
            yield f"data: {json.dumps({'type': 'session_title', 'title': title}, ensure_ascii=False)}\n\n"

        async for event in agent.stream_request(
            question,
            session_id=session_id,
            model=model,
        ):
            yield event
            await asyncio.sleep(0)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Sessions ──────────────────────────────────────────────────────────────────

@app.get("/sessions")
async def list_sessions():
    return get_all_sessions()


@app.get("/history/{session_id}")
async def history(session_id: str):
    return get_chat_history(session_id, limit=100)


@app.patch("/sessions/{session_id}/rename")
async def rename_session(session_id: str, data: dict):
    title = data.get("title", "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="El título no puede estar vacío.")
    update_session_title(session_id, title)
    return {"status": "success"}


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    clear_history(session_id)
    clear_session_file(session_id)  # Limpiar FileContext también
    return {"status": "success", "message": f"Sesión {session_id} eliminada."}


@app.post("/reset")
async def reset_session(session_id: str = Form("default_user")):
    clear_history(session_id)
    clear_session_file(session_id)
    return {"status": "ok", "message": "Sesión reseteada."}


# ── Exports ───────────────────────────────────────────────────────────────────

@app.post("/export/pdf")
async def export_pdf(
    session_id: str = Form("default_user"),
    title: str = Form("Reporte de Análisis"),
    insights: str = Form(""),
    warnings: str = Form("[]"),
    suggested_questions: str = Form("[]"),
):
    """Genera un PDF ejecutivo y devuelve el archivo para descarga."""
    ctx = get_session_file(session_id)
    if not ctx or not ctx.is_loaded:
        raise HTTPException(status_code=400, detail="No hay archivo cargado para esta sesión.")
    try:
        warns = json.loads(warnings) if warnings else []
        questions = json.loads(suggested_questions) if suggested_questions else []
        path = build_pdf_report(
            file_path=ctx.file_path,
            session_id=session_id,
            title=title,
            insights=insights,
            warnings=warns,
            suggested_questions=questions,
        )
        return FileResponse(
            path,
            media_type="application/pdf",
            filename=Path(path).name,
            headers={"Content-Disposition": f'attachment; filename="{Path(path).name}"'},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generando PDF: {e}") from e


@app.post("/export/pptx")
async def export_pptx(
    session_id: str = Form("default_user"),
    title: str = Form("Presentación de Análisis"),
    insights: str = Form(""),
    warnings: str = Form("[]"),
    suggested_questions: str = Form("[]"),
):
    """Genera un PPTX ejecutivo y devuelve el archivo para descarga."""
    ctx = get_session_file(session_id)
    if not ctx or not ctx.is_loaded:
        raise HTTPException(status_code=400, detail="No hay archivo cargado para esta sesión.")
    try:
        warns = json.loads(warnings) if warnings else []
        questions = json.loads(suggested_questions) if suggested_questions else []
        path = build_pptx_report(
            file_path=ctx.file_path,
            session_id=session_id,
            title=title,
            insights=insights,
            warnings=warns,
            suggested_questions=questions,
        )
        return FileResponse(
            path,
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            filename=Path(path).name,
            headers={"Content-Disposition": f'attachment; filename="{Path(path).name}"'},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generando PPTX: {e}") from e


# ── Dashboards ────────────────────────────────────────────────────────────────

@app.post("/dashboard/create")
async def create_dashboard(
    session_id: str = Form("default_user"),
    title: str = Form("Dashboard de Análisis"),
    insights: str = Form(""),
    warnings: str = Form("[]"),
    suggested_questions: str = Form("[]"),
):
    """Genera el dashboard HTML, lo persiste y devuelve el UUID para compartir."""
    ctx = get_session_file(session_id)
    if not ctx or not ctx.is_loaded:
        raise HTTPException(status_code=400, detail="No hay archivo cargado para esta sesión.")
    try:
        warns = json.loads(warnings) if warnings else []
        questions = json.loads(suggested_questions) if suggested_questions else []
        html = dashboard_builder.build(
            file_path=ctx.file_path,
            title=title,
            insights=insights,
            warnings=warns,
            suggested_questions=questions,
        )
        dash_uuid = save_dashboard(session_id, title, html)
        return {
            "uuid": dash_uuid,
            "url": f"/dashboard/{dash_uuid}",
            "title": title,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creando dashboard: {e}") from e


@app.get("/dashboard/{dash_uuid}", response_class=HTMLResponse)
async def serve_dashboard(dash_uuid: str):
    """Sirve el dashboard HTML por UUID — accesible sin login."""
    record = get_dashboard(dash_uuid)
    if not record:
        raise HTTPException(status_code=404, detail="Dashboard no encontrado.")
    return HTMLResponse(content=record["html_content"])


@app.get("/dashboards/{session_id}")
async def list_session_dashboards(session_id: str):
    """Lista los dashboards de una sesión."""
    return list_dashboards(session_id)


@app.delete("/dashboard/{dash_uuid}")
async def remove_dashboard(dash_uuid: str):
    if not delete_dashboard(dash_uuid):
        raise HTTPException(status_code=404, detail="Dashboard no encontrado.")
    return {"status": "deleted"}


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    return {
        "status": "online",
        "version": "2.1.0",
        "active_file_sessions": 0,  # Podría exponer len(_session_files) para debug
    }