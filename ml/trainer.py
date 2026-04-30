from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from sklearn.ensemble import IsolationForest
from ml.utils import build_transaction_df

MODEL_DIR = Path(__file__).resolve().parent / "models"
MODEL_DIR.mkdir(exist_ok=True)


async def train_for_user(user_id: str, conn):

    # Expense Regression
    async with conn.cursor() as cur:
        await cur.execute("""
            SELECT TO_CHAR(date, 'YYYY-MM') AS month,
                   SUM(amount) AS total_expense
            FROM transactions
            WHERE user_id = %s AND type = 'expense'
            GROUP BY TO_CHAR(date, 'YYYY-MM')
            ORDER BY TO_CHAR(date, 'YYYY-MM')
        """, (user_id,))
        rows = await cur.fetchall()

    reg_path = MODEL_DIR / f"user_{user_id}_expense_reg.joblib"
    if len(rows) >= 2:
        df = pd.DataFrame(rows, columns=["month", "total_expense"]).astype({"total_expense": float})
        X = np.arange(len(df)).reshape(-1, 1)
        y = df["total_expense"].values
        reg = LinearRegression()
        reg.fit(X, y)
        joblib.dump(reg, reg_path)
    else:
        reg_path.unlink(missing_ok=True)

    # KMeans Clustering
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
        cat_rows = await cur.fetchall()

    bundle_path = MODEL_DIR / f"user_{user_id}_cluster_bundle.joblib"
    if len(cat_rows) >= 2:
        df = pd.DataFrame(cat_rows, columns=["category_name", "avg_amount", "transaction_count", "total_spent"])
        df = df.astype({"avg_amount": float, "total_spent": float, "transaction_count": int})
        X = df[["avg_amount", "transaction_count"]].values
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        n_clusters = min(3, len(df))
        kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        kmeans.fit(X_scaled)
        df["cluster"] = kmeans.labels_
        cluster_totals = df.groupby("cluster")["total_spent"].mean().sort_values(ascending=False)
        labels = ["high spend", "moderate", "low spend"]
        cluster_label_map = {cid: labels[i] for i, cid in enumerate(cluster_totals.index)}
        bundle = {
            "kmeans": kmeans,
            "scaler": scaler,
            "cluster_label_map": cluster_label_map
        }
        joblib.dump(bundle, bundle_path)
    else:
        bundle_path.unlink(missing_ok=True)

    # Isolation Forest Anomaly
    async with conn.cursor() as cur:
        await cur.execute("""
            SELECT transaction_id, title, amount, date,
                   COALESCE(c.name, 'Uncategorized') AS category_name
            FROM transactions t
            LEFT JOIN categories c ON t.category_id = c.category_id
            WHERE t.user_id = %s AND t.type = 'expense'
            ORDER BY t.date DESC
        """, (user_id,))
        tx_rows = await cur.fetchall()

    anom_path = MODEL_DIR / f"user_{user_id}_anomaly_bundle.joblib"
    if len(tx_rows) >= 5:
        df = build_transaction_df(tx_rows)
        features = df[["amount", "day_of_week", "day_of_month"]].values
        scaler = StandardScaler()
        features_scaled = scaler.fit_transform(features)
        iso = IsolationForest(contamination=0.2, random_state=42, n_estimators=100)
        iso.fit(features_scaled)
        bundle = {
            "isolation_forest": iso,
            "scaler": scaler,
            "overall_avg": float(df["amount"].mean())
        }
        joblib.dump(bundle, anom_path)
    else:
        anom_path.unlink(missing_ok=True)