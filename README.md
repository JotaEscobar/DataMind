# 🧠 DataMind 2.0 — Analista de Datos IA Senior

![DataMind Logo](logo.png)

> **DataMind** es una plataforma de análisis de datos de última generación que combina la potencia de agentes inteligentes (ReAct) con la precisión de Python para transformar archivos crudos en insights estratégicos accionables.

[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/Frontend-React_19-61DAFB?style=for-the-badge&logo=react)](https://react.dev/)
[![Tailwind CSS](https://img.shields.io/badge/Styles-Tailwind_4.0-38B2AC?style=for-the-badge&logo=tailwind-css)](https://tailwindcss.com/)
[![Docker](https://img.shields.io/badge/Deployment-Docker-2496ED?style=for-the-badge&logo=docker)](https://www.docker.com/)

---

## ✨ Características Principales

*   🚀 **Diagnóstico Automático Instantáneo:** Al subir un archivo (CSV/Excel), el sistema genera un perfil estructural, detecta tipos de datos, calidad y el dominio del dataset sin tiempos de espera.
*   🤖 **Motor Agéntico ReAct:** No es solo un chat. El agente escribe y ejecuta código Python en tiempo real para realizar cálculos exactos, evitando las alucinaciones comunes en los LLMs.
*   🎭 **Personas Especializadas:** El sistema detecta la intención y el dominio para asignar el análisis a un experto:
    *   **Financial Analyst:** Rentabilidad y tendencias económicas.
    *   **Data Detective:** Anomalías, outliers e inconsistencias.
    *   **Statistician:** Significancia, p-values y correlaciones.
    *   **Growth Analyst:** Cohortes, retención y segmentación.
*   📊 **Dashboards Interactivos:** Genera tableros visuales compartibles mediante una URL única basada en UUID.
*   📄 **Reportería Ejecutiva:** Exporta tus hallazgos directamente a formatos profesionales **PDF** y presentaciones **PowerPoint (PPTX)**.
*   🌐 **Hybrid LLM Support:** Conectividad flexible con **Groq** (Llama 3.3 70B) para máxima potencia o **Ollama** para ejecución 100% local.

---

## 🛠️ Stack Tecnológico

### **Frontend**
- **Framework:** React 19 + TypeScript + Vite.
- **Estado:** Zustand (Global) & TanStack Query (Server State).
- **UI:** Tailwind CSS 4.0 + Framer Motion (Animaciones) + Lucide React.
- **Comunicación:** SSE (Server-Sent Events) para respuestas en streaming real.

### **Backend**
- **Framework:** FastAPI (Python 3.10+).
- **Procesamiento:** Pandas & NumPy.
- **Agente:** Arquitectura ReAct propia con clasificación de intención (IntentClassifier) y gestión de sesiones persistentes.
- **Exportación:** ReportLab (PDF) & Python-PPTX.

### **Infraestructura**
- **Containerización:** Docker & Docker Compose.
- **Persistencia:** Almacenamiento local estructurado en `data_storage/` y gestión de base de datos ligera para historial.

---

## 🚀 Instalación y Uso

### Requisitos Previos
- Docker & Docker Compose instalado.
- (Opcional) Una API Key de [Groq](https://console.groq.com/) para el modelo principal.
- (Opcional) [Ollama](https://ollama.ai/) instalado localmente si no deseas usar la nube.

### Configuración rápida (Docker)

1. **Clonar el repositorio:**
   ```bash
   git clone https://github.com/JotaEscobar/DataMind.git
   cd DataMind
   ```

2. **Configurar variables de entorno:**
   Copia el archivo de ejemplo y edita tus llaves:
   ```bash
   cp .env.example .env
   ```

3. **Levantar el proyecto:**
   ```bash
   docker-compose up --build -d
   ```

4. **Acceder a la aplicación:**
   - Frontend: [http://localhost:5173](http://localhost:5173)
   - API Docs: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## 💻 Desarrollo Local (Sin Docker)

Si prefieres correrlo manualmente:

**Backend:**
```bash
cd backend
python -m venv venv
source venv/bin/activate  # o venv\Scripts\activate en Windows
pip install -r requirements.txt
python -m app.main
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

---

## 📂 Estructura del Proyecto

```text
analista/
├── backend/
│   ├── app/
│   │   ├── core/      # Lógica del Agente, Clasificador de Intención
│   │   ├── services/  # Motores de exportación y Dashboards
│   │   └── main.py    # Endpoints de FastAPI
│   └── Dockerfile
├── frontend/
│   ├── src/           # Componentes React y Hooks de Zustand
│   └── Dockerfile
├── data_storage/      # Archivos subidos y persistencia
├── docker-compose.yml
└── requirements.txt
```

---

## 🤝 Contribuciones

Las contribuciones son bienvenidas. Si tienes una idea para mejorar el motor agéntico o añadir nuevas herramientas de análisis:

1. Haz un Fork del proyecto.
2. Crea una rama para tu feature (`git checkout -b feature/AmazingFeature`).
3. Haz commit de tus cambios (`git commit -m 'Add some AmazingFeature'`).
4. Haz Push a la rama (`git push origin feature/AmazingFeature`).
5. Abre un Pull Request.

---

## 📄 Licencia

Este proyecto está bajo la Licencia MIT. Consulta el archivo `LICENSE` para más detalles.

---
Elaborado con ❤️ por **[Jorge Escobar](https://github.com/JotaEscobar)**
