from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from ml.utils import build_transaction_df

MODEL_DIR = Path(__file__).resolve().parent / "models"


class ModelNotReady(Exception):
    # Raised when model hasn't been trained yet
    pass


def _load(user_id: str, model_name: str):
    path = MODEL_DIR / f"user_{user_id}_{model_name}.joblib"
    if not path.exists():
        raise ModelNotReady(f"Model '{model_name}' not trained yet.")
    return joblib.load(path)


def _build_transaction_df(rows) -> pd.DataFrame:
    df = build_transaction_df(rows)
    return df


async def predict_next_month_expense(user_id: str, conn) -> dict:
    reg = _load(user_id, "expense_reg")

    async with conn.cursor() as cur:
        await cur.execute("""
            SELECT TO_CHAR(date, 'YYYY-MM') AS month
            FROM transactions
            WHERE user_id = %s AND type = 'expense'
            GROUP BY TO_CHAR(date, 'YYYY-MM')
            ORDER BY TO_CHAR(date, 'YYYY-MM')
        """, (user_id,))
        months = [row[0] for row in await cur.fetchall()]

    if not months:
        raise ModelNotReady("No expense months found.")

    next_index = np.array([[len(months)]])
    predicted = float(reg.predict(next_index)[0])
    predicted = max(0.0, predicted)

    last_month = pd.to_datetime(months[-1] + "-01")
    next_month = (last_month + pd.DateOffset(months=1)).strftime("%Y-%m")

    confidence = "low" if len(months) < 3 else ("medium" if len(months) < 6 else "high")
    return {
        "month": next_month,
        "predicted_expense": round(predicted, 2),
        "confidence": confidence
    }


async def get_cluster_results(user_id: str, conn) -> list[dict]:
    bundle = _load(user_id, "cluster_bundle")
    kmeans = bundle["kmeans"]
    scaler = bundle["scaler"]
    cluster_label_map = bundle["cluster_label_map"]

    async with conn.cursor() as cur:
        await cur.execute("""
            SELECT COALESCE(c.name, 'Uncategorized') AS category_name,
                   AVG(t.amount) AS avg_amount,
                   COUNT(*) AS transaction_count,
                   SUM(t.amount) AS total_spent
            FROM transactions t
            LEFT JOIN categories c ON t.category_id = c.category_id
            WHERE t.user_id = %s AND t.type = 'expense'
            GROUP BY c.name
            ORDER BY total_spent DESC
        """, (user_id,))
        rows = await cur.fetchall()

    if not rows:
        raise ModelNotReady("No categories to cluster.")

    df = pd.DataFrame(rows, columns=["category_name", "avg_amount", "transaction_count", "total_spent"])
    df = df.astype({"avg_amount": float, "total_spent": float, "transaction_count": int})
    X = df[["avg_amount", "transaction_count"]].values
    X_scaled = scaler.transform(X)
    df["cluster"] = kmeans.predict(X_scaled)

    return [
        {
            "category_name": row["category_name"],
            "cluster": int(row["cluster"]),
            "cluster_label": cluster_label_map[row["cluster"]],
            "avg_amount": round(float(row["avg_amount"]), 2),
            "transaction_count": int(row["transaction_count"])
        }
        for _, row in df.iterrows()
    ]


async def detect_anomaly_transactions(user_id: str, conn) -> tuple[list[dict], float]:
    bundle = _load(user_id, "anomaly_bundle")
    iso = bundle["isolation_forest"]
    scaler = bundle["scaler"]
    overall_avg = bundle["overall_avg"]

    async with conn.cursor() as cur:
        await cur.execute("""
            SELECT t.transaction_id, t.title, t.amount, t.date,
                   COALESCE(c.name, 'Uncategorized') AS category_name
            FROM transactions t
            LEFT JOIN categories c ON t.category_id = c.category_id
            WHERE t.user_id = %s AND t.type = 'expense'
            ORDER BY t.date DESC
        """, (user_id,))
        rows = await cur.fetchall()

    if not rows:
        raise ModelNotReady("No expense transactions.")

    df = _build_transaction_df(rows)
    features = df[["amount", "day_of_week", "day_of_month"]].values
    features_scaled = scaler.transform(features)

    preds = iso.predict(features_scaled)
    scores = iso.score_samples(features_scaled)
    min_score, max_score = scores.min(), scores.max()

    anomalies = []
    for i, (_, row) in enumerate(df.iterrows()):
        if preds[i] == -1:
            if max_score != min_score:
                normalized = 1 - (scores[i] - min_score) / (max_score - min_score)
            else:
                normalized = 1.0
            multiplier = round(row["amount"] / overall_avg, 1) if overall_avg > 0 else 0
            reason = (
                f"Amount of {row['amount']:.2f} is {multiplier}x "
                f"the overall average expense ({overall_avg:.2f})"
            )
            anomalies.append({
                "transaction_id": int(row["transaction_id"]),
                "title": row["title"],
                "amount": float(row["amount"]),
                "category_name": row["category_name"],
                "date": row["date"].strftime("%Y-%m-%d"),
                "anomaly_score": round(float(normalized), 3),
                "reason": reason
            })

    anomalies.sort(key=lambda x: x["anomaly_score"], reverse=True)
    return anomalies, overall_avg