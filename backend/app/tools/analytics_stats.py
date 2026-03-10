import pandas as pd
import numpy as np
import statsmodels.api as sm
from typing import cast


def trend_analyzer(df: pd.DataFrame, x_col: str, y_col: str) -> dict:
    """
    Herramienta Elite 4: TrendAnalyzer.
    Regresiones lineales para tendencias reales.
    """
    if x_col not in df.columns or y_col not in df.columns:
        return {"error": "Columnas no válidas"}

    subset = df[[x_col, y_col]].apply(pd.to_numeric, errors='coerce').dropna()
    if len(subset) < 2:
        return {"error": "No hay suficientes datos numéricos para tendencia"}

    X = sm.add_constant(subset[x_col])
    model = sm.OLS(subset[y_col], X).fit()
    prediction = model.predict(X)
    
    return {
        "slope": float(model.params.iloc[1]),
        "r_squared": float(model.rsquared),
        "prediction": [float(value) for value in prediction.tolist()]
    }

def correlation_discovery(df: pd.DataFrame) -> pd.DataFrame:
    """
    Herramienta Elite 5: CorrelationDiscovery.
    Genera matrices de interdependencia entre variables.
    """
    numeric_df = df.select_dtypes(include=[np.number])
    if numeric_df.empty: 
        return pd.DataFrame()
    return numeric_df.corr()

def pareto_engine(df: pd.DataFrame, category_col: str, value_col: str) -> pd.DataFrame:
    """
    Herramienta Elite 6: ParetoEngine.
    Identificación automática de factores críticos (80/20).
    """
    if category_col not in df.columns or value_col not in df.columns:
        return pd.DataFrame()

    grouped = cast(pd.Series, df.groupby(category_col, dropna=False)[value_col].sum())
    aggregated = cast(pd.DataFrame, grouped.reset_index())
    if value_col not in aggregated.columns:
        return pd.DataFrame()

    group_df = cast(
        pd.DataFrame,
        aggregated.sort_values(by=value_col, ascending=False).set_index(category_col),
    )
    total = group_df[value_col].sum()
    if total == 0:
        group_df['cumulative_percent'] = 0.0
        group_df['is_vital'] = False
        return group_df

    group_df['cumulative_percent'] = (group_df[value_col].cumsum() / total) * 100
    
    # Marcamos los 'Top Vital' (80% del impacto)
    group_df['is_vital'] = group_df['cumulative_percent'] <= 80
    return group_df
