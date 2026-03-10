import pandas as pd
import os
from typing import Dict, Any

def inspect_data_structure(file_path: str) -> Dict[str, Any]:
    """
    Herramienta Elite 1: DataInspector.
    Analiza la estructura, tipos y salud de cualquier dataset (CSV, XLSX).
    """
    if not os.path.exists(file_path):
        return {"error": f"Archivo no encontrado en {file_path}"}
        
    # Identificar extensión y cargar
    ext = os.path.splitext(file_path)[1].lower()
    
    try:
        if ext == '.csv':
            df = pd.read_csv(file_path)
        elif ext in ['.xlsx', '.xls']:
            df = pd.read_excel(file_path)
        else:
            return {"error": f"Formato '{ext}' no soportado."}
            
        # Análisis de Salud del Dato
        report = {
            "columns": list(df.columns),
            "total_rows": len(df),
            "total_cols": len(df.columns),
            "missing_values": df.isnull().sum().to_dict(),
            "data_types": df.dtypes.astype(str).to_dict(),
            "preview_head": df.head(5).to_dict(orient='records'),
            "summary_stats": df.describe().to_dict() if df.select_dtypes(include='number').any().any() else "No numeric columns"
        }
        
        return {
            "status": "success",
            "report": report,
            "message": f"Dataset de {len(df)} filas inspeccionado correctamente."
        }
        
    except Exception as e:
        return {"error": f"Fallo al inspeccionar: {str(e)}"}
