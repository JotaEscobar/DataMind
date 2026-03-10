"""
agent.py — DataMind 2.0 — Motor ReAct refactorizado

FIXES aplicados vs versión anterior:
  ✅ Bug #1: _chat() para Ollama ya no se llama a sí mismo (recursión infinita)
  ✅ Bug #2: Guardia de archivo — si la tool necesita datos y no hay archivo,
             responde directamente sin inventar
  ✅ Bug #3: Streaming real con Ollama via ollama.chat(stream=True)
  ✅ Bug #4: generate_title usa modelo liviano, no bloquea el análisis principal

  ✅ Nuevo: IntentClassifier — clasifica CHAT/NEEDS_FILE/ANALYSIS/EXPORT antes de ReAct
  ✅ Nuevo: FileContext — estado persistente del archivo inyectado en cada prompt
  ✅ Nuevo: Personas diferenciadas con system prompts propios por dominio
  ✅ Nuevo: Model routing — modelo liviano para tareas baratas, potente para análisis
"""
from __future__ import annotations

import json
import logging
import os
import inspect as _inspect
from typing import AsyncGenerator, Dict, List, Optional

import ollama as _ollama

from app.core.database import get_chat_history, save_message
from app.core.code_executor import (
    CODE_EXECUTOR_DESCRIPTION,
    CodeExecutor,
    load_dataframe,
)
from app.core.intent import (
    AgentPersona,
    FileContext,
    IntentClassifier,
    IntentType,
    NEEDS_FILE_RESPONSE,
    PERSONA_PROFILES,
    get_chat_response,
    select_persona_from_context,
)

try:
    import groq as _groq_module
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False
    _groq_module = None

logger = logging.getLogger(__name__)


# ── Model routing ──────────────────────────────────────────────────────────────
# FAST_MODEL  → clasificar intención, generar título (barato, rápido)
# MAIN_MODEL  → análisis principal (más capaz)
# LOCAL_MODEL → fallback sin internet

_DEFAULT_FAST  = "groq/llama-3.1-8b-instant"
_DEFAULT_MAIN  = "groq/llama-3.3-70b-versatile"
_DEFAULT_LOCAL = "llama3.1"


# ──────────────────────────────────────────────────────────────────────────────
# SESSION FILE STORE — Memoria de archivos por sesión en proceso
# (En producción esto iría a Redis o DB; aquí es in-process y es suficiente)
# ──────────────────────────────────────────────────────────────────────────────
_session_files: Dict[str, FileContext] = {}


def set_session_file(session_id: str, ctx: FileContext) -> None:
    _session_files[session_id] = ctx


def get_session_file(session_id: str) -> Optional[FileContext]:
    return _session_files.get(session_id)


def clear_session_file(session_id: str) -> None:
    _session_files.pop(session_id, None)


# ──────────────────────────────────────────────────────────────────────────────
# DATAMIND AGENT
# ──────────────────────────────────────────────────────────────────────────────

class DataMindAgent:
    """
    Motor agéntico ReAct con clasificación de intención, contexto de archivo
    persistente y personas diferenciadas por dominio.
    """

    def __init__(self, registry):
        self.registry = registry
        self.groq_api_key = os.getenv("GROQ_API_KEY", "")
        self.fast_model   = os.getenv("FAST_MODEL",  _DEFAULT_FAST)
        self.main_model   = os.getenv("MAIN_MODEL",  _DEFAULT_MAIN)

        # Clasificador de intención
        self._classifier = IntentClassifier(chat_fn=self._chat_text)

        # Code executor — para cálculos exactos sin alucinaciones
        self._code_executor = CodeExecutor(timeout_seconds=30)

    # ── LLM Interface ──────────────────────────────────────────────────────────

    def _is_groq(self, model: str) -> bool:
        return model.startswith("groq/") and GROQ_AVAILABLE and _groq_module is not None

    def _groq_model_name(self, model: str) -> str:
        return model.replace("groq/", "")

    def _chat(self, model: str, messages: list, stream: bool = False):
        """
        Unified LLM interface — Groq o Ollama.
        Devuelve el objeto response crudo (para streaming o extracción posterior).
        """
        if self._is_groq(model):
            client = _groq_module.Groq(api_key=self.groq_api_key)
            return client.chat.completions.create(
                model=self._groq_model_name(model),
                messages=messages,
                stream=stream,
                temperature=0.3,
                max_tokens=2048,
            )
        else:
            # Ollama — llamada real, sin recursión
            local_model = model.replace("ollama/", "")
            return _ollama.chat(
                model=local_model,
                messages=messages,
                stream=stream,
                options={"temperature": 0.3},
            )

    def _chat_text(self, model: str, messages: list) -> str:
        """
        Conveniencia: llama al LLM y devuelve el texto directamente.
        Usado por IntentClassifier y generate_title.
        """
        try:
            response = self._chat(model=model, messages=messages, stream=False)
            return self._extract_text(response)
        except Exception as e:
            logger.warning("_chat_text falló con modelo %s: %s", model, e)
            # Fallback al modelo local si Groq falla
            if self._is_groq(model):
                try:
                    response = self._chat(model=_DEFAULT_LOCAL, messages=messages, stream=False)
                    return self._extract_text(response)
                except Exception as e2:
                    logger.error("Fallback local también falló: %s", e2)
            return ""

    def _extract_text(self, response) -> str:
        """Extrae el texto de un response de Groq o Ollama (no stream)."""
        # Groq
        if hasattr(response, "choices") and response.choices:
            content = response.choices[0].message.content
            return content or ""
        # Ollama dict
        if isinstance(response, dict):
            return response.get("message", {}).get("content", "")
        # Ollama objeto
        if hasattr(response, "message"):
            msg = response.message
            if hasattr(msg, "content"):
                return msg.content or ""
        return str(response)

    def _extract_stream_token(self, chunk, is_groq: bool) -> str:
        """Extrae un token de un chunk de streaming."""
        if is_groq:
            if hasattr(chunk, "choices") and chunk.choices:
                delta = chunk.choices[0].delta
                return delta.content or "" if hasattr(delta, "content") else ""
        else:
            # Ollama streaming chunk
            if isinstance(chunk, dict):
                return chunk.get("message", {}).get("content", "")
            if hasattr(chunk, "message"):
                msg = chunk.message
                return msg.content or "" if hasattr(msg, "content") else ""
        return ""

    # ── Utilities ─────────────────────────────────────────────────────────────

    def generate_title(self, query: str, model: Optional[str] = None) -> str:
        """Genera título corto de sesión. Usa el modelo liviano siempre."""
        fast = model if model else self.fast_model
        try:
            prompt = (
                f"Genera un título muy corto y descriptivo (máximo 5 palabras) "
                f"para un análisis de datos que empieza con: '{query[:120]}'. "
                f"Devuelve SOLO el título, sin comillas ni puntos."
            )
            title = self._chat_text(
                model=fast,
                messages=[{"role": "user", "content": prompt}],
            ).strip().strip('"').strip("'")
            return " ".join(title.split()[:5]) or "Nuevo Análisis"
        except Exception:
            return "Nuevo Análisis de Datos"

    def sanitize_json(self, text: str) -> str:
        """Extrae el primer objeto JSON válido del texto."""
        text = text.strip()
        # Eliminar posibles bloques de markdown
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        start = text.find("{")
        if start == -1:
            raise ValueError(f"No se encontró formato JSON en la acción: {text[:50]}...")
            
        depth, in_string, escape_next = 0, False, False
        for i, ch in enumerate(text[start:], start=start):
            if escape_next:
                escape_next = False
                continue
            if ch == "\\" and in_string:
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start: i + 1]
                    
        # Fallback si el balanceo natural falla: intentar de la primera { a la última }
        end = text.rfind("}")
        if end > start:
            return text[start: end + 1]
            
        raise ValueError("El JSON en la acción está incompleto o malformado.")

    def _inject_file_path(self, tool_name: str, params: dict, file_context: Optional[FileContext]) -> dict:
        """Inyecta file_path en params si la tool lo requiere."""
        if not file_context or not file_context.is_loaded:
            return params
        tool_entry = self.registry.tools.get(tool_name)
        if not tool_entry:
            return params
        sig = _inspect.signature(tool_entry["func"])
        if "file_path" in sig.parameters:
            params = dict(params)
            params["file_path"] = file_context.file_path
        return params

    def serialize_observation(self, observation) -> str:
        """Convierte resultado de tool a texto seguro para el contexto del LLM."""
        if hasattr(observation, "to_dict"):
            # DataFrame — solo primeras 10 filas, no todo el dataset
            preview = observation.head(10).fillna("").astype(str)
            return json.dumps(preview.to_dict(orient="records"), ensure_ascii=False)
        try:
            return json.dumps(observation, ensure_ascii=False, default=str)
        except Exception:
            return str(observation)[:2000]

    # ── System Prompt ──────────────────────────────────────────────────────────

    def _build_system_prompt(
        self,
        persona: AgentPersona,
        file_context: Optional[FileContext],
        tools_list: str,
    ) -> str:
        profile = PERSONA_PROFILES[persona]

        file_block = (
            file_context.to_prompt_block()
            if file_context and file_context.is_loaded
            else "Archivo: ninguno cargado. NO inventes datos si no tienes archivo."
        )

        priority_tools = (
            f"Prioriza estas tools en este orden: {', '.join(profile['priority_tools'])}"
            if profile["priority_tools"]
            else "Usa las tools que mejor se ajusten a la solicitud."
        )

        return f"""Eres DATAMIND 2.0 — {profile['title']}.

{file_block}

════════════════════════════════════════
REGLA ABSOLUTA — NUNCA INVENTES DATOS
════════════════════════════════════════
- NUNCA estimes, supongas ni inventes valores numéricos.
- Para CUALQUIER cálculo (suma, promedio, conteo, ranking, etc.) DEBES usar
  execute_python_code o una herramienta. NUNCA calcules mentalmente.
- Si no tienes los datos, di: "Necesito inspeccionar el archivo primero."

════════════════════════════════════════
TU ROL Y ESTILO
════════════════════════════════════════
Foco    : {profile['focus']}
Estilo  : {profile['style']}
Métricas clave: {profile['key_metrics']}
{priority_tools}

════════════════════════════════════════
FORMATO DE SALIDA — OBLIGATORIO
════════════════════════════════════════
Usa EXACTAMENTE estas tres etiquetas en este orden:

THOUGHT: [Una sola línea. Separa pasos con " · ". Máx 80 palabras. Sin Markdown.]
  Ejemplo: 🧠 Analizar ventas · 💻 código → groupby + sort · ✅ resultado exacto listo

ACTION tiene DOS formas posibles:

  FORMA 1 — Ejecutar código Python (usa esto para TODOS los cálculos):
  ACTION: {{"type": "code", "code": "result = df.groupby('col')['val'].sum().sort_values(ascending=False)\nprint(result.head(10))"}}

  FORMA 2 — Llamar herramienta especializada (clustering, ARIMA, Pareto, etc.):
  ACTION: {{"type": "tool", "tool": "nombre_tool", "params": {{"param": "valor"}}}}

  Sin acción: ACTION: ninguna

  REGLAS DEL CÓDIGO:
  - El DataFrame es `df`. Siempre asigna el resultado final a `result`.
  - Usa print() para valores intermedios que quieras ver.
  - Una sola ACTION por turno.
  - NUNCA incluyas file_path ni imports — ya están disponibles.

INSIGHT: [Respuesta final]
  - Empieza DIRECTO con el hallazgo más importante.
  - Máx 5 párrafos × 5 líneas. **Negritas** solo para cifras clave (máx 2/párrafo).
  - Prosa fluida, sin listas con guiones.
  - Cierra con UNA pregunta de acción concreta.

════════════════════════════════════════
HERRAMIENTAS ESPECIALIZADAS
════════════════════════════════════════
{tools_list}

════════════════════════════════════════
CODE EXECUTOR (para cálculos exactos)
════════════════════════════════════════
{CODE_EXECUTOR_DESCRIPTION}
"""

    def _build_messages(
        self,
        session_id: str,
        persona: AgentPersona,
        file_context: Optional[FileContext],
    ) -> list:
        """Construye el historial de mensajes con system prompt."""
        tools_list = self.registry.get_tool_definitions()
        system = self._build_system_prompt(persona, file_context, tools_list)

        raw_history = get_chat_history(session_id, limit=10)
        history = [{"role": m["role"], "content": m["content"]} for m in raw_history]

        return [{"role": "system", "content": system}] + history

    # ── ReAct Loop (bloqueante) ────────────────────────────────────────────────

    def process_request(
        self,
        user_query: str,
        session_id: str = "default",
        model: str = "llama3.1",
        file_context: Optional[FileContext] = None,
    ) -> dict:
        """Bucle ReAct bloqueante. Mantenido por compatibilidad con /analyze."""
        # Resolver file_context desde store si no se pasó explícitamente
        if file_context is None:
            file_context = get_session_file(session_id)

        has_file = file_context is not None and file_context.is_loaded

        # Clasificar intención
        intent = self._classifier.classify(user_query, has_file=has_file)

        save_message(session_id, "user", user_query)

        # Respuestas directas sin ReAct
        if intent == IntentType.CHAT:
            reply = get_chat_response(user_query)
            save_message(session_id, "assistant", reply)
            return {"thought": "", "insight": reply}

        if intent == IntentType.NEEDS_FILE:
            save_message(session_id, "assistant", NEEDS_FILE_RESPONSE)
            return {"thought": "", "insight": NEEDS_FILE_RESPONSE}

        # Seleccionar persona
        persona = select_persona_from_context(user_query, file_context)
        logger.info("[Agent] Persona: %s | Intent: %s", persona, intent)

        messages = self._build_messages(session_id, persona, file_context)
        messages.append({"role": "user", "content": user_query})

        main = model if model else self.main_model
        max_steps, step = 5, 0
        full_thought: list[str] = []

        while step < max_steps:
            try:
                content = self._chat_text(model=main, messages=messages)

                if "THOUGHT:" in content:
                    thought = content.split("ACTION:")[0].replace("THOUGHT:", "").strip()
                    if "INSIGHT:" in thought:
                        thought = thought.split("INSIGHT:")[0].strip()
                    full_thought.append(thought)

                if "ACTION:" in content:
                    action_raw = content.split("ACTION:")[1].split("INSIGHT:")[0].strip()
                    if action_raw.lower() == "ninguna":
                        pass  # Sin herramienta, ir al INSIGHT
                    else:
                        try:
                            action_data = json.loads(self.sanitize_json(action_raw))
                            action_type = action_data.get("type", "tool")

                            # ── Tipo: código Python ──────────────────────────
                            if action_type == "code":
                                code = action_data.get("code", "").strip()
                                if not code:
                                    raise ValueError("El bloque de código está vacío.")

                                if not (file_context and file_context.is_loaded):
                                    raise ValueError("No hay archivo cargado para ejecutar código.")

                                df = load_dataframe(file_context.file_path)
                                if df is None:
                                    raise ValueError(f"No se pudo cargar el archivo: {file_context.file_path}")

                                logger.info("[Agent] Ejecutando código Python (%d chars)", len(code))
                                code_result = self._code_executor.execute(code, df)
                                obs_text = code_result.to_llm_text()

                            # ── Tipo: herramienta especializada ──────────────
                            else:
                                tool_name = action_data.get("tool", action_data.get("tool_name", ""))
                                if not tool_name:
                                    raise ValueError("No se especificó nombre de herramienta.")
                                params = self._inject_file_path(
                                    tool_name,
                                    action_data.get("params", {}),
                                    file_context,
                                )
                                logger.info("[Agent] Tool: %s", tool_name)
                                obs = self.registry.execute_tool(tool_name, **params)
                                obs_text = self.serialize_observation(obs)

                            messages.append({"role": "assistant", "content": content})
                            messages.append({"role": "user", "content": f"OBSERVED: {obs_text}"})
                            step += 1
                            continue

                        except Exception as e:
                            logger.warning("[Agent] Action error: %s", e)
                            messages.append({
                                "role": "user",
                                "content": (
                                    f"ERROR: {e}. Revisa tu ACTION e intenta de nuevo, "
                                    "o entrega el INSIGHT con los datos que ya tienes."
                                ),
                            })
                            step += 1
                            continue

                # Extraer INSIGHT
                insight = content.split("INSIGHT:")[-1].strip() if "INSIGHT:" in content else content.strip()
                thought_str = " · ".join(t for t in full_thought if t)
                full_content = f"<thought>{thought_str}</thought>\n\n{insight}" if thought_str else insight
                save_message(session_id, "assistant", full_content)
                return {"thought": thought_str, "insight": insight}

            except Exception as e:
                logger.error("[Agent] Critical error: %s", e)
                return {
                    "thought": "❌ Error en razonamiento.",
                    "insight": f"Ocurrió un error: {e}. Por favor intenta de nuevo.",
                }

        timeout = "El proceso de razonamiento excedió los pasos permitidos. ¿Podemos intentar con una pregunta más específica?"
        save_message(session_id, "assistant", timeout)
        return {"thought": "⏳ Max steps.", "insight": timeout}

    # ── ReAct Loop (streaming async) ───────────────────────────────────────────

    async def stream_request(
        self,
        user_query: str,
        session_id: str = "default",
        model: str = "llama3.1",
        file_context: Optional[FileContext] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Generador async que emite eventos SSE tipados.

        Eventos emitidos:
          {"type": "intent",        "value": "ANALYSIS"}
          {"type": "persona",       "value": "FINANCIAL_ANALYST"}
          {"type": "thought",       "content": "..."}
          {"type": "action",        "tool": "nombre"}
          {"type": "observation",   "summary": "..."}
          {"type": "insight_token", "token": "..."}
          {"type": "done"}
          {"type": "error",         "message": "..."}
        """
        def emit(payload: dict) -> str:
            return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        try:
            # Resolver file_context
            if file_context is None:
                file_context = get_session_file(session_id)

            has_file = file_context is not None and file_context.is_loaded

            # ── Clasificar intención ──────────────────────────────────────────
            intent = self._classifier.classify(user_query, has_file=has_file)
            yield emit({"type": "intent", "value": intent.value})

            save_message(session_id, "user", user_query)

            # ── Respuestas directas sin ReAct ─────────────────────────────────
            if intent == IntentType.CHAT:
                reply = get_chat_response(user_query)
                save_message(session_id, "assistant", reply)
                # Emitir token a token para efecto visual
                for i in range(0, len(reply), 6):
                    yield emit({"type": "insight_token", "token": reply[i:i+6]})
                yield emit({"type": "done"})
                return

            if intent == IntentType.NEEDS_FILE:
                save_message(session_id, "assistant", NEEDS_FILE_RESPONSE)
                for i in range(0, len(NEEDS_FILE_RESPONSE), 6):
                    yield emit({"type": "insight_token", "token": NEEDS_FILE_RESPONSE[i:i+6]})
                yield emit({"type": "done"})
                return

            # ── Seleccionar persona ───────────────────────────────────────────
            persona = select_persona_from_context(user_query, file_context)
            yield emit({"type": "persona", "value": persona.value})
            logger.info("[Agent] Persona: %s | Model: %s", persona, model)

            messages = self._build_messages(session_id, persona, file_context)
            messages.append({"role": "user", "content": user_query})

            main = model if model else self.main_model
            max_steps, step = 5, 0
            full_thought_parts: list[str] = []
            insight_full = ""

            while step < max_steps:
                # Llamada bloqueante para THOUGHT + ACTION
                content = self._chat_text(model=main, messages=messages)

                # ── THOUGHT ───────────────────────────────────────────────────
                if "THOUGHT:" in content:
                    thought = content.split("ACTION:")[0].replace("THOUGHT:", "").strip()
                    if "INSIGHT:" in thought:
                        thought = thought.split("INSIGHT:")[0].strip()
                    full_thought_parts.append(thought)
                    yield emit({"type": "thought", "content": thought})

                # ── ACTION ────────────────────────────────────────────────────
                if "ACTION:" in content:
                    action_raw = content.split("ACTION:")[1].split("INSIGHT:")[0].strip()

                    if action_raw.lower() != "ninguna":
                        try:
                            action_data = json.loads(self.sanitize_json(action_raw))
                            action_type = action_data.get("type", "tool")

                            # ── Tipo: código Python ──────────────────────────
                            if action_type == "code":
                                code = action_data.get("code", "").strip()
                                if not code:
                                    raise ValueError("El bloque de código está vacío.")

                                if not (file_context and file_context.is_loaded):
                                    raise ValueError("No hay archivo cargado para ejecutar código.")

                                df = load_dataframe(file_context.file_path)
                                if df is None:
                                    raise ValueError(f"No se pudo cargar: {file_context.file_path}")

                                yield emit({"type": "action", "tool": "⚙️ execute_python_code"})
                                logger.info("[Agent] Ejecutando código (%d chars)", len(code))

                                code_result = self._code_executor.execute(code, df)
                                obs_text = code_result.to_llm_text()

                                obs_summary = (
                                    f"✅ Código ejecutado · {obs_text[:120]}…"
                                    if len(obs_text) > 120
                                    else f"✅ {obs_text}"
                                )
                                if not code_result.success:
                                    obs_summary = f"❌ Error: {code_result.error[:100]}"

                            # ── Tipo: herramienta especializada ──────────────
                            else:
                                tool_name = action_data.get("tool", action_data.get("tool_name", ""))
                                if not tool_name:
                                    raise ValueError("No se especificó nombre de herramienta.")
                                params = self._inject_file_path(
                                    tool_name,
                                    action_data.get("params", {}),
                                    file_context,
                                )
                                yield emit({"type": "action", "tool": tool_name})
                                logger.info("[Agent] Tool: %s", tool_name)
                                obs = self.registry.execute_tool(tool_name, **params)
                                obs_text = self.serialize_observation(obs)
                                obs_summary = obs_text[:150] + "…" if len(obs_text) > 150 else obs_text

                            yield emit({"type": "observation", "summary": obs_summary})
                            messages.append({"role": "assistant", "content": content})
                            messages.append({"role": "user", "content": f"OBSERVED: {obs_text}"})
                            step += 1
                            continue

                        except Exception as e:
                            logger.warning("[Agent] Action error: %s", e)
                            messages.append({
                                "role": "user",
                                "content": (
                                    f"ERROR: {e}. Revisa tu ACTION e intenta de nuevo "
                                    "o entrega el INSIGHT con los datos que ya tienes."
                                ),
                            })
                            step += 1
                            continue

                # ── INSIGHT — streaming real ───────────────────────────────────
                insight_prefix = (
                    content.split("INSIGHT:")[-1].strip()
                    if "INSIGHT:" in content
                    else content.strip()
                )

                is_groq = self._is_groq(main)

                if insight_prefix:
                    # El INSIGHT llegó completo en el mismo response — streaming simulado
                    # para mantener UX uniforme
                    insight_full = insight_prefix
                    chunk_size = 5
                    for i in range(0, len(insight_full), chunk_size):
                        yield emit({"type": "insight_token", "token": insight_full[i:i+chunk_size]})
                else:
                    # No hay INSIGHT todavía — hacer segunda llamada en modo stream real
                    stream_messages = messages + [
                        {"role": "assistant", "content": content},
                        {
                            "role": "user",
                            "content": (
                                "Ahora entrega ÚNICAMENTE el INSIGHT final. "
                                "Sin THOUGHT ni ACTION. Empieza directo con el análisis."
                            ),
                        },
                    ]
                    try:
                        stream_resp = self._chat(model=main, messages=stream_messages, stream=True)
                        for chunk in stream_resp:
                            token = self._extract_stream_token(chunk, is_groq)
                            if token:
                                insight_full += token
                                yield emit({"type": "insight_token", "token": token})
                    except Exception as e:
                        logger.error("[Agent] Streaming error: %s", e)
                        fallback = "Error al generar respuesta en streaming. Por favor intenta de nuevo."
                        yield emit({"type": "insight_token", "token": fallback})
                        insight_full = fallback

                # Persistir y terminar
                thought_str = " · ".join(t for t in full_thought_parts if t)
                full_content = f"<thought>{thought_str}</thought>\n\n{insight_full}" if thought_str else insight_full
                save_message(session_id, "assistant", full_content)
                yield emit({"type": "done"})
                return

            # Max steps alcanzado
            timeout = "El proceso de razonamiento fue demasiado largo. ¿Podemos intentar con una pregunta más específica?"
            save_message(session_id, "assistant", timeout)
            for i in range(0, len(timeout), 6):
                yield emit({"type": "insight_token", "token": timeout[i:i+6]})
            yield emit({"type": "done"})

        except Exception as e:
            logger.error("[Agent] Critical stream error: %s", e)
            yield emit({"type": "error", "message": str(e)})
            yield emit({"type": "done"})