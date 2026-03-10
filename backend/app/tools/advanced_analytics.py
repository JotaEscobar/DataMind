import pandas as pd
from sklearn.cluster import KMeans
from statsmodels.tsa.arima.model import ARIMA
import scipy.stats as stats
from typing import Any, List, cast


def cluster_segmenter(df: pd.DataFrame, n_clusters: int = 3) -> pd.DataFrame:
    """
    Herramienta Elite 7: ClusterSegmenter.
    Segmenta entidades automáticament por similaridad (K-Means).
    """
    result = df.copy()
    numeric_df = result.select_dtypes(include=['number']).dropna()
    if numeric_df.empty:
        return result

    total_rows = len(numeric_df)
    safe_clusters = max(1, min(n_clusters, total_rows))
    model = KMeans(n_clusters=safe_clusters, random_state=42, n_init='auto')
    labels = model.fit_predict(numeric_df)

    result['segmento'] = pd.NA
    result.loc[numeric_df.index, 'segmento'] = labels
    return result

def cohort_tracker(df: pd.DataFrame, time_col: str, group_col: str) -> pd.DataFrame:
    """
    Herramienta Elite 8: CohortTracker.
    Análisis de comportamiento por periodos de tiempo (retención/grupos).
    """
    if time_col not in df.columns or group_col not in df.columns:
        return pd.DataFrame()

    working_df = df.copy()
    working_df[time_col] = pd.to_datetime(working_df[time_col], errors='coerce')
    working_df = working_df.dropna(subset=[time_col, group_col])
    if working_df.empty:
        return pd.DataFrame()

    working_df['event_period'] = working_df[time_col].dt.to_period('M')
    working_df['cohort'] = working_df.groupby(group_col)['event_period'].transform('min')
    working_df['period_index'] = (working_df['event_period'] - working_df['cohort']).apply(lambda x: x.n)

    cohort_counts = working_df.groupby(['cohort', 'period_index'])[group_col].nunique()
    cohort_frame = pd.DataFrame(cohort_counts).reset_index().rename(columns={group_col: 'users'})
    cohort = cohort_frame.pivot(index='cohort', columns='period_index', values='users')
    return cohort.sort_index()

def stat_tester(df: pd.DataFrame, group_col: str, value_col: str) -> dict:
    """
    Herramienta Elite 9: StatTester.
    T-Test para validar si las diferencias entre 2 grupos son reales (significancia).
    """
    if group_col not in df.columns or value_col not in df.columns:
        return {"error": "Columnas no válidas"}

    cleaned = df[[group_col, value_col]].dropna()
    groups: List[object] = list(dict.fromkeys(cleaned[group_col].tolist()))
    if len(groups) < 2:
        return {"error": "Se necesitan al menos 2 grupos."}

    group_1_values = cleaned.loc[cleaned[group_col] == groups[0], value_col]
    group_2_values = cleaned.loc[cleaned[group_col] == groups[1], value_col]
    g1 = pd.Series(pd.to_numeric(group_1_values, errors='coerce')).dropna()
    g2 = pd.Series(pd.to_numeric(group_2_values, errors='coerce')).dropna()
    if len(g1) == 0 or len(g2) == 0:
        return {"error": "No hay datos numéricos suficientes para comparar."}
    
    test_result = stats.ttest_ind(g1, g2, equal_var=False)
    t_stat_value = cast(Any, getattr(test_result, 'statistic', 0.0))
    p_val_value = cast(Any, getattr(test_result, 'pvalue', 1.0))
    t_stat = float(t_stat_value)
    p_val = float(p_val_value)
    
    return {
        "p_value": float(p_val),
        "is_significant": p_val < 0.05,
        "t_statistic": t_stat,
        "message": "Diferencia significativa" if p_val < 0.05 else "Sin evidencia de diferencia real"
    }

def forecaster(df: pd.DataFrame, target_col: str, periods: int = 5) -> dict:
    """
    Herramienta Elite 10: Forecaster.
    Predicción de valores futuros mediante ARIMA (Time Series).
    """
    try:
        if target_col not in df.columns:
            return {"error": "Columna objetivo no válida"}

        safe_periods = max(1, periods)
        series = pd.Series(pd.to_numeric(df[target_col], errors='coerce')).dropna().to_numpy()
        if len(series) < 3:
            return {"error": "Se requieren al menos 3 observaciones para pronóstico."}

        model = ARIMA(series, order=(1,1,1)).fit()
        forecast = [float(value) for value in model.forecast(steps=safe_periods)]
        return {
            "prediction": forecast,
            "next_value": forecast[0]
        }
    except Exception as e:
        return {"error": str(e)}
