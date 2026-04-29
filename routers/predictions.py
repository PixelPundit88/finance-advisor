from fastapi import APIRouter, Depends
from database import get_db
from routers.auth import get_current_user
from errors import NotFoundException

router = APIRouter(prefix="/predictions", tags=["predictions"])

@router.get("/")
async def get_predictions(
    current_user=Depends(get_current_user),
    conn=Depends(get_db)
):
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT
                prediction_id,
                month,
                predicted_expense,
                created_at
            FROM predictions
            WHERE user_id = %s
            ORDER BY month DESC
            """,
            (current_user["user_id"],)
        )
        rows = await cur.fetchall()

    if not rows:
        raise NotFoundException("No predictions found. Run /analysis/predict first.")

    return [
        {
            "prediction_id": r[0],
            "month": r[1].strftime("%Y-%m"),
            "predicted_expense": float(r[2]),
            "created_at": r[3]
        }
        for r in rows
    ]


@router.get("/{prediction_id}")
async def get_prediction(
    prediction_id: int,
    current_user=Depends(get_current_user),
    conn=Depends(get_db)
):
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT
                prediction_id,
                month,
                predicted_expense,
                created_at
            FROM predictions
            WHERE prediction_id = %s AND user_id = %s
            """,
            (prediction_id, current_user["user_id"])
        )
        row = await cur.fetchone()

    if not row:
        raise NotFoundException("Prediction not found")

    return {
        "prediction_id": row[0],
        "month": row[1].strftime("%Y-%m"),
        "predicted_expense": float(row[2]),
        "created_at": row[3]
    }


@router.delete("/{prediction_id}")
async def delete_prediction(
    prediction_id: int,
    current_user=Depends(get_current_user),
    conn=Depends(get_db)
):
    async with conn.cursor() as cur:
        await cur.execute(
            "DELETE FROM predictions WHERE prediction_id = %s AND user_id = %s",
            (prediction_id, current_user["user_id"])
        )
        deleted = cur.rowcount

    await conn.commit()

    if not deleted:
        raise NotFoundException("Prediction not found")

    return {"message": "Prediction deleted"}