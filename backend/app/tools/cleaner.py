import pandas as pd

def smart_cleaner(df: pd.DataFrame) -> pd.DataFrame:
    """
    Herramienta Elite 2: SmartCleaner.
    Normalización automática de strings, fechas y limpieza de nulos.
    """
    cleaned_df = df.copy()
    row_count = max(len(cleaned_df), 1)
    
    # 1. Limpieza de nombres de columnas
    cleaned_df.columns = [str(c).lower().strip().replace(' ', '_') for c in cleaned_df.columns]
    
    # 2. Detección y conversión de fechas
    for col in cleaned_df.columns:
        if cleaned_df[col].dtype == 'object':
            try:
                temp_dates = pd.to_datetime(cleaned_df[col], errors='coerce')
                if temp_dates.notnull().sum() / row_count > 0.6:
                    cleaned_df[col] = temp_dates
            except (TypeError, ValueError):
                pass
                
    # 3. Limpieza de strings (monedas S/, comas, etc.)
    for col in cleaned_df.select_dtypes(include=['object']).columns:
        if cleaned_df[col].str.contains(r'[S/\$\,]', na=False).any():
            normalized = cleaned_df[col].str.replace(r'[^\d\.-]', '', regex=True)
            numeric = pd.to_numeric(normalized, errors='coerce')
            if numeric.notnull().sum() / row_count > 0.6:
                cleaned_df[col] = numeric
            
    return cleaned_df
