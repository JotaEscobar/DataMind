# 📊 Analista de Datos — Prototipo Inteligente

Analista de datos personal potenciado por IA (Groq y Ollama local), diseñado para realizar análisis estadísticos, detección de anomalías y generación de reportes interactivos directamente desde archivos CSV y Excel.

---

## 🚀 Inicio Rápido

### 1. Variables de Entorno (Obligatorio)
Crea una copia de `.env.example` y renómbralo a `.env`:
```bash
cp .env.example .env
```
Abre el archivo `.env` e ingresa tu clave de la API de Groq en `GROQ_API_KEY`.

### 2. Instalar Ollama (Opcional pero recomendado)
Descárgalo desde: [ollama.com/download/windows](https://ollama.com/download/windows)

Luego, abre una terminal y descarga el modelo (si deseas usarlo de respaldo o según el flujo local):
```bash
ollama pull llama3.1
```

### 3. Ejecutar la Aplicación
Simplemente haz doble clic en el archivo `start.bat`.

- Se creará automáticamente un entorno virtual (`venv`) si no existe.
- Se instalarán todas las dependencias necesarias.
- El servidor se abrirá en tu navegador en: [http://localhost:8000](http://localhost:8000)

### 4. Ejecutar con Docker (Backend + Frontend)
Si ya tienes Docker Desktop, puedes levantar todo con un solo comando:

```bash
docker compose up --build
```

También puedes usar `start-docker.bat` para iniciarlo con doble clic.

- Frontend: [http://localhost:5173](http://localhost:5173)
- Backend API: [http://localhost:8000](http://localhost:8000)

> Nota: el backend en Docker usa por defecto `OLLAMA_HOST=http://host.docker.internal:11434`.
> Asegúrate de tener Ollama corriendo en tu máquina host (`ollama serve`) y el modelo descargado (`ollama pull llama3.1`).

---

## 🧠 Capacidades del Analista

- **📎 Procesamiento Multiformato**: Carga y analiza archivos CSV y Excel (`.xlsx`, `.xls`).
- **💬 Interacción Natural**: Consultas en español sobre tus datos (ej: "¿Qué producto es el más rentable?").
- **📊 Visualización Dinámica**: Generación automática de gráficos (Barras, Líneas, Dispersión) adaptados a tu pregunta.
- **🔍 Análisis Avanzado (ML)**:
    - **Detección de Anomalías**: Identifica valores atípicos automáticamente.
    - **Estadísticas Predictivas**: Tendencias, correlaciones y segmentación (clustering).
- **📂 Exportación Profesional**: Genera reportes completos en **PDF** y presentaciones **PowerPoint** con un clic.
- **🔗 Cruce de Datos**: Capacidad de analizar y relacionar múltiples archivos simultáneamente.

---

## 🛠️ Tecnologías Utilizadas

- **Backend**: Python 3.10+, FastAPI, Pydantic.
- **IA/LLM**: Groq API (Llama 3.1/3), Ollama para procesamiento local.
- **Análisis de Datos**: Pandas, NumPy, Scikit-learn, Statsmodels.
- **Visualización**: Plotly (Gráficos interactivos).
- **Reportes**: ReportLab (PDF), Python-pptx (PowerPoint).
- **Frontend**: React 19, TypeScript, Vite, Tailwind CSS.

---

## 🗂️ Estructura del Proyecto

```text
analista/
├── backend/                # Lógica de servidor y núcleo de procesamiento
│   └── app/
│       ├── core/           # Orquestación de IA y base de datos
│       ├── services/       # Generadores de archivos (PDF/PPTX)
│       ├── tools/          # Herramientas de limpieza y analítica
│       └── main.py         # Entry point de FastAPI
├── data_storage/           # Almacenamiento local (SQLite y datasets)
├── exports/                # Reportes generados listos para descargar
├── frontend/               # Interfaz web (React + Vite)
├── uploads/                # Espacio temporal para archivos subidos
├── docker-compose.yml      # Orquestación local (backend + frontend)
├── requirements.txt        # Dependencias del proyecto
├── start.bat               # Arranque local backend
└── start-docker.bat        # Arranque Docker en un clic
```

---

## 📋 Requisitos del Sistema

- **OS**: Windows 10/11.
- **RAM**: 8GB mínimo (16GB recomendado para fluidez de IA).
- **GPU**: Opcional, pero recomendada para acelerar la respuesta de Ollama.
- **Espacio**: ~5GB para el modelo de lenguaje.

---

## ❓ Solución de Problemas

*   **"Ollama no encontrado"**: Asegúrate de que Ollama esté instalado y el proceso `ollama serve` esté activo.
*   **"Error al procesar"**: Revisa que hayas ejecutado `ollama pull llama3.1`.
*   **Lentitud inicial**: El primer análisis puede tardar unos segundos mientras el modelo se carga en la memoria RAM/VRAM.
