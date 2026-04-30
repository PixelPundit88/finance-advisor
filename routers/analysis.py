from fastapi import APIRouter, Depends
from database import get_db
from errors import NotFoundException, BadRequestException
from routers.auth import get_current_user
from ml.predictor import (
    predict_next_month_expense,
    get_cluster_results,
    detect_anomaly_transactions,
    ModelNotReady
)
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

    try:
        result = await predict_next_month_expense(user_id, conn)
    except ModelNotReady as e:
        raise BadRequestException(str(e))

    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO predictions (user_id, month, predicted_expense)
            VALUES (%s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (user_id, result["month"] + "-01", result["predicted_expense"])
        )
    await conn.commit()
    return PredictionResponse(**result)

# CLUSTERS
@router.get("/clusters", response_model=ClusterResponse)
async def get_clusters(
    current_user=Depends(get_current_user),
    conn=Depends(get_db)
):
    user_id = current_user["user_id"]

    try:
        clusters = await get_cluster_results(user_id, conn)
    except ModelNotReady as e:
        raise BadRequestException(str(e))
    return ClusterResponse(clusters=[CategoryCluster(**c) for c in clusters])

# ANOMALIES

@router.get("/anomalies", response_model=AnomalyResponse)
async def detect_anomalies(
    current_user=Depends(get_current_user),
    conn=Depends(get_db)
):
    user_id = current_user["user_id"]

    try:
        anomalies, _ = await detect_anomaly_transactions(user_id, conn)
    except ModelNotReady as e:
        raise BadRequestException(str(e))

    if anomalies:
        async with conn.cursor() as cur:
            await cur.executemany(
                """
                INSERT INTO anomalies (transaction_id, score, reason, flagged_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT DO NOTHING
                """,
                [(a["transaction_id"], a["anomaly_score"], a["reason"]) for a in anomalies]
            )
        await conn.commit()

    return AnomalyResponse(
        anomalies=[AnomalyTransaction(**a) for a in anomalies],
        total_flagged=len(anomalies)
    )