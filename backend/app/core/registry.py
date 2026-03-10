import importlib
import inspect
import logging
import os
from typing import Dict, Any, Callable


logger = logging.getLogger(__name__)

class ToolRegistry:
    """Registrador de herramientas para el Analista de Datos."""
    def __init__(self):
        self.tools: Dict[str, Dict[str, Any]] = {}

    def register_tool(self, name: str, description: str, func: Callable):
        """Registra una función como herramienta."""
        if name in self.tools:
            logger.warning("Tool '%s' ya existía y será sobreescrita.", name)
        self.tools[name] = {
            "name": name,
            "description": description,
            "func": func,
            "parameters": str(inspect.signature(func))
        }
        logger.info("Herramienta registrada: %s", name)

    def get_tool_definitions(self) -> str:
        """Retorna una descripción legible para el LLM."""
        definitions = []
        for name, info in self.tools.items():
            definitions.append(f"- {name}: {info['description']} (Firma: {info['parameters']})")
        return "\n".join(definitions)

    def execute_tool(self, name: str, **kwargs) -> Any:
        """Ejecuta una herramienta registrada."""
        if name not in self.tools:
            raise ValueError(f"Herramienta '{name}' no encontrada.")
        return self.tools[name]["func"](**kwargs)

    def load_tools_from_directory(self, directory: str):
        """Carga automáticamente herramientas desde archivos en un directorio."""
        if not os.path.exists(directory):
            logger.warning("Directorio no existe: %s", directory)
            return
            
        for filename in os.listdir(directory):
            if filename.endswith(".py") and not filename.startswith("__"):
                module_name = filename[:-3]
                # Importar el módulo dinámicamente
                try:
                    # Asumimos que el path de importación es app.tools.module_name
                    module = importlib.import_module(f"app.tools.{module_name}")
                    # Buscar funciones con un decorador especial o simplemente todas (simplificado)
                    for member_name, member in inspect.getmembers(module, inspect.isfunction):
                        # Aquí podrías filtrar si solo quieres herramientas con decoradores @tool
                        # Registramos todas las funciones que no empiecen con _ (privadas)
                        if not member_name.startswith("_") and member.__module__ == module.__name__:
                           self.register_tool(member_name, member.__doc__ or "S/D", member)
                except Exception as e:
                    logger.exception("Error al cargar %s: %s", module_name, e)

registry = ToolRegistry()
# Auto-carga al importar el registry
# Calculamos la ruta absoluta de la carpeta tools relativa a este archivo
tools_path = os.path.join(os.path.dirname(__file__), "..", "tools")
registry.load_tools_from_directory(tools_path)
