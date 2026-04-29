import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import IsolationForest
from sklearn.cluster import KMeans
from fastapi import APIRouter, Depends, HTTPException
from database import get_db
from errors import NotFoundException, BadRequestException
from routers.auth import get_current_user
import pandas as pd
from models import (
    CategorySummary,
    MonthlySummary,
    SummaryResponse,
    PredictionResponse,
    CategoryCluster,
    ClusterResponse,
    AnomalyTransaction,
    AnomalyResponse,
)

router = APIRouter(prefix="/analysis", tags=["analysis"])

@router.get("/summary", response_model=SummaryResponse)
async def get_summary(
    current_user=Depends(get_current_user),
    conn=Depends(get_db)
):
    user_id = current_user["user_id"]

    # MONTHLY TOTALS(INCOME, EXPENSE)
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT
                TO_CHAR(date, 'YYYY-MM') AS month,
                SUM(CASE WHEN type = 'income' THEN amount ELSE 0 END) AS total_income,
                SUM(CASE WHEN type = 'expense' THEN amount ELSE 0 END) AS total_expense
            FROM transactions
            WHERE user_id = %s
            GROUP BY TO_CHAR(date, 'YYYY-MM')
            ORDER BY TO_CHAR(date, 'YYYY-MM') DESC
            """,
            (user_id,)
        )
        monthly_rows = await cur.fetchall()

    # TOP 5 EXPENSE CATEGORIES
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT
                COALESCE(c.name, 'Uncategorized') AS category_name,
                SUM(t.amount) AS total_spent,
                COUNT(*) AS transaction_count
            FROM transactions t
            LEFT JOIN categories c ON t.category_id = c.category_id
            WHERE t.user_id = %s AND t.type = 'expense'
            GROUP BY category_name
            ORDER BY total_spent DESC
            LIMIT 5
            """,
            (user_id,)
        )
        category_rows = await cur.fetchall()

    # overall totals
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT
                SUM(CASE WHEN type = 'income' THEN amount ELSE 0 END) AS total_income,
                SUM(CASE WHEN type = 'expense' THEN amount ELSE 0 END) AS total_expense
            FROM transactions
            WHERE user_id = %s
            """,
            (user_id,)
        )
        totals = await cur.fetchone()

    if not monthly_rows and not category_rows:
        raise NotFoundException("No transactions found. Add some transactions first.")

    total_income = float(totals[0] or 0)
    total_expense = float(totals[1] or 0)

    if total_income == 0 and total_expense == 0:
        raise NotFoundException("No transaction amounts found.")

    monthly = [
        MonthlySummary(
            month=r[0],
            total_income=float(r[1]),
            total_expense=float(r[2]),
            net=float(r[1]) - float(r[2])
        )
        for r in monthly_rows
    ]

    top_expense_categories = [
        CategorySummary(
            category_name=r[0],
            total_spent=float(r[1]),
            transaction_count=r[2]
        )
        for r in category_rows
    ]

    return SummaryResponse(
        monthly=monthly,
        top_expense_categories=top_expense_categories,
        total_income=total_income,
        total_expense=total_expense,
        net_savings=total_income - total_expense
    )

# PREDICT
@router.get("/predict", response_model=PredictionResponse)
async def predict_expense(
    current_user=Depends(get_current_user),
    conn=Depends(get_db)
):
    user_id = current_user["user_id"]

    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT
                TO_CHAR(date, 'YYYY-MM') AS month,
                SUM(amount) AS total_expense
            FROM transactions
            WHERE user_id = %s AND type = 'expense'
            GROUP BY TO_CHAR(date, 'YYYY-MM')
            ORDER BY TO_CHAR(date, 'YYYY-MM')
            """,
            (user_id,)
        )
        rows = await cur.fetchall()

    if not rows:
        raise NotFoundException("No expense transactions found to predict from.")
    if len(rows) < 2:
        raise BadRequestException("Not enough data to predict. Add at least 2 months of expenses.")

    df = pd.DataFrame(rows, columns=["month", "total_expense"])
    df["total_expense"] = df["total_expense"].astype(float)

    X = np.arange(len(df)).reshape(-1, 1)
    y = df["total_expense"].values

    model = LinearRegression()
    model.fit(X, y)

    next_index = np.array([[len(df)]])
    predicted = float(model.predict(next_index)[0])
    predicted = max(0.0, predicted)

    last_month = pd.to_datetime(df["month"].iloc[-1] + "-01")
    next_month = (last_month + pd.DateOffset(months=1)).strftime("%Y-%m")

    if len(df) < 3:
        confidence = "low"
    elif len(df) < 6:
        confidence = "medium"
    else:
        confidence = "high"

    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO predictions (user_id, month, predicted_expense)
            VALUES (%s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (user_id, next_month + "-01", round(predicted, 2))
        )
    await conn.commit()

    return PredictionResponse(
        month=next_month,
        predicted_expense=round(predicted, 2),
        confidence=confidence
    )

# CLUSTERS
@router.get("/clusters", response_model=ClusterResponse)
async def get_clusters(
    current_user=Depends(get_current_user),
    conn=Depends(get_db)
):
    user_id = current_user["user_id"]

    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT
                COALESCE(c.name, 'Uncategorized') AS category_name,
                AVG(t.amount) AS avg_amount,
                COUNT(*) AS transaction_count,
                SUM(t.amount) AS total_spent
            FROM transactions t
            LEFT JOIN categories c ON t.category_id = c.category_id
            WHERE t.user_id = %s AND t.type = 'expense'
            GROUP BY c.name
            ORDER BY total_spent DESC
            """,
            (user_id,)
        )
        rows = await cur.fetchall()

    if not rows:
        raise NotFoundException("No expense transactions found to cluster.")

    if len(rows) < 2:
        raise BadRequestException("Not enough categories to cluster. Add transactions in at least 2 different categories.")

    df = pd.DataFrame(rows, columns=["category_name", "avg_amount", "transaction_count", "total_spent"])
    df["avg_amount"] = df["avg_amount"].astype(float)
    df["total_spent"] = df["total_spent"].astype(float)

    X = df[["avg_amount", "transaction_count"]].values

    # scaling features so avg_amount doesn't dominate transaction_count
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    n_clusters = min(3, len(df))

    # train KMeans
    model = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    df["cluster"] = model.fit_predict(X_scaled)

    # labeling clusters based on total_spent
    cluster_totals = df.groupby("cluster")["total_spent"].mean().sort_values(ascending=False)
    labels = ["high spend", "moderate", "low spend"]
    cluster_label_map = {
        cluster_id: labels[i]
        for i, cluster_id in enumerate(cluster_totals.index)
    }

    return ClusterResponse(
        clusters=[
            CategoryCluster(
                category_name=row["category_name"],
                cluster=int(row["cluster"]),
                cluster_label=cluster_label_map[row["cluster"]],
                avg_amount=round(float(row["avg_amount"]), 2),
                transaction_count=int(row["transaction_count"])
            )
            for _, row in df.iterrows()
        ]
    )

# ANOMALIES

@router.get("/anomalies", response_model=AnomalyResponse)
async def detect_anomalies(
    current_user=Depends(get_current_user),
    conn=Depends(get_db)
):
    user_id = current_user["user_id"]

    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT
                t.transaction_id,
                t.title,
                t.amount,
                t.date,
                COALESCE(c.name, 'Uncategorized') AS category_name
            FROM transactions t
            LEFT JOIN categories c ON t.category_id = c.category_id
            WHERE t.user_id = %s AND t.type = 'expense'
            ORDER BY t.date DESC
            """,
            (user_id,)
        )
        rows = await cur.fetchall()

    if not rows:
        raise NotFoundException("No expense transactions found.")

    if len(rows) < 5:
        raise BadRequestException("Add at least 5 expense transactions.")

    df = pd.DataFrame(rows, columns=["transaction_id", "title", "amount", "date", "category_name"])
    df["amount"] = df["amount"].astype(float)
    df["date"] = pd.to_datetime(df["date"])
    df["day_of_week"] = df["date"].dt.dayofweek
    df["day_of_month"] = df["date"].dt.day

    features = df[["amount", "day_of_week", "day_of_month"]].values

    scaler = StandardScaler()
    features_scaled = scaler.fit_transform(features)

    model = IsolationForest(
        contamination=0.2,
        random_state=42,
        n_estimators=100
    )
    scores = model.fit_predict(features_scaled)
    raw_scores = model.score_samples(features_scaled)

    min_score = raw_scores.min()
    max_score = raw_scores.max()

    overall_avg = df["amount"].mean()

    anomalies = []

    for i, (idx, row) in enumerate(df.iterrows()):
        if scores[i] == -1:
            if max_score != min_score:
                normalized = 1 - (raw_scores[i] - min_score) / (max_score - min_score)
            else:
                normalized = 1.0

            multiplier = round(row["amount"] / overall_avg, 1)
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

    if anomalies:
        async with conn.cursor() as cur:
            await cur.executemany(
                """
                INSERT INTO anomalies (transaction_id, score, reason, flagged_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT DO NOTHING
                """,
                [
                    (a["transaction_id"], a["anomaly_score"], a["reason"])
                    for a in anomalies
                ]
            )
        await conn.commit()

    return AnomalyResponse(
        anomalies=[AnomalyTransaction(**a) for a in anomalies],
        total_flagged=len(anomalies)
    )