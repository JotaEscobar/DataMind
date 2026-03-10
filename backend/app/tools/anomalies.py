import pandas as pd
from sklearn.ensemble import IsolationForest


def anomaly_scanner(df: pd.DataFrame, target_col: str) -> pd.DataFrame:
    """
    Herramienta Elite 3: AnomalyScanner.
    Detección de outliers mediante Isolation Forest (ML).
    """
    if target_col not in df.columns or not pd.api.types.is_numeric_dtype(df[target_col]):
        return df

    result = df.copy()
    model = IsolationForest(random_state=42)
    clean_series = result[target_col].fillna(result[target_col].median()).to_numpy().reshape(-1, 1)
    prediction = model.fit_predict(clean_series)

    result['anomaly_score'] = prediction
    result['is_anomaly'] = prediction == -1
    return result
