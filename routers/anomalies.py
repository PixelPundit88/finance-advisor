from fastapi import APIRouter, Depends, HTTPException
from database import get_db
from routers.auth import get_current_user

router = APIRouter(prefix="/anomalies", tags=["anomalies"])

ANOMALY_SELECT = """
    SELECT
        a.anomaly_id,
        a.transaction_id,
        t.title,
        t.amount,
        t.date,
        COALESCE(c.name, 'Uncategorized') AS category_name,
        a.score,
        a.reason,
        a.flagged_at
    FROM anomalies a
    JOIN transactions t ON a.transaction_id = t.transaction_id
    LEFT JOIN categories c ON t.category_id = c.category_id
"""

def format_anomaly(r) -> dict:
    return {
        "anomaly_id": r[0],
        "transaction_id": r[1],
        "title": r[2],
        "amount": float(r[3]),
        "date": r[4].strftime("%Y-%m-%d"),
        "category_name": r[5],
        "score": float(r[6]),
        "reason": r[7],
        "flagged_at": r[8]
    }


@router.get("/")
async def get_anomalies(
    current_user=Depends(get_current_user),
    conn=Depends(get_db)
):
    async with conn.cursor() as cur:
        await cur.execute(
            ANOMALY_SELECT + "WHERE t.user_id = %s ORDER BY a.score DESC",
            (current_user["user_id"],)
        )
        rows = await cur.fetchall()

    if not rows:
        raise HTTPException(
            status_code=404,
            detail="No anomalies found. Run /analysis/anomalies first."
        )

    return [format_anomaly(r) for r in rows]


@router.get("/{anomaly_id}")
async def get_anomaly(
    anomaly_id: int,
    current_user=Depends(get_current_user),
    conn=Depends(get_db)
):
    async with conn.cursor() as cur:
        await cur.execute(
            ANOMALY_SELECT + "WHERE a.anomaly_id = %s AND t.user_id = %s",
            (anomaly_id, current_user["user_id"])
        )
        row = await cur.fetchone()

    if not row:
        raise HTTPException(status_code=404,
                            detail="Anomaly not found")

    return format_anomaly(row)


@router.delete("/{anomaly_id}")
async def delete_anomaly(
    anomaly_id: int,
    current_user=Depends(get_current_user),
    conn=Depends(get_db)
):
    async with conn.cursor() as cur:
        await cur.execute(
            """
            DELETE FROM anomalies a
            USING transactions t
            WHERE a.anomaly_id = %s
            AND a.transaction_id = t.transaction_id
            AND t.user_id = %s
            """,
            (anomaly_id, current_user["user_id"])
        )
        deleted = cur.rowcount

    await conn.commit()

    if not deleted:
        raise HTTPException(status_code=404,
                            detail="Anomaly not found")

    return {"message": "Anomaly deleted"}