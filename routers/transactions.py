from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from database import get_db
from routers.auth import get_current_user
from datetime import date
from typing import Optional
from models import TransactionCreate, TransactionUpdate
import csv
import io

router = APIRouter(prefix="/transactions", tags=["transactions"])

@router.post("/", status_code=201)
async def create_transaction(
    req: TransactionCreate,
    current_user=Depends(get_current_user),
    conn=Depends(get_db)
):
    if req.type not in ("income", "expense"):
        raise HTTPException(status_code=400, detail="Type must be 'income' or 'expense'")

    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")

    if req.category_id:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT category_id FROM categories WHERE category_id = %s AND user_id = %s",
                (req.category_id, current_user["user_id"])
            )
            if not await cur.fetchone():
                raise HTTPException(status_code=404, detail="Category not found")

    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO transactions (user_id, category_id, title, description, amount, type, date)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING transaction_id
            """,
            (
                current_user["user_id"],
                req.category_id,
                req.title,
                req.description,
                req.amount,
                req.type,
                req.date
            )
        )
        row = await cur.fetchone()

    await conn.commit()
    return {"message": "Transaction created", "transaction_id": row[0]}


@router.get("/")
async def get_transactions(
    _type: Optional[str] = None,        # filter by income/expense
    category_id: Optional[int] = None,  # filter by category
    from_date: Optional[date] = None,   # filter by date range
    to_date: Optional[date] = None,
    current_user=Depends(get_current_user),
    conn=Depends(get_db)
):
    query = """
        SELECT
            t.transaction_id,
            t.title,
            t.description,
            t.amount,
            t.type,
            t.date,
            t.created_at,
            c.name AS category_name
        FROM transactions t
        LEFT JOIN categories c ON t.category_id = c.category_id
        WHERE t.user_id = %s
    """
    params = [current_user["user_id"]]

    if type:
        query += " AND t.type = %s"
        params.append(type)

    if category_id:
        query += " AND t.category_id = %s"
        params.append(category_id)

    if from_date:
        query += " AND t.date >= %s"
        params.append(from_date)

    if to_date:
        query += " AND t.date <= %s"
        params.append(to_date)

    query += " ORDER BY t.date DESC"

    async with conn.cursor() as cur:
        await cur.execute(query, params)
        rows = await cur.fetchall()

    return [
        {
            "transaction_id": r[0],
            "title": r[1],
            "description": r[2],
            "amount": float(r[3]),
            "type": r[4],
            "date": r[5],
            "created_at": r[6],
            "category_name": r[7],
        }
        for r in rows
    ]

@router.get("/export")
async def export_transactions(
    current_user=Depends(get_current_user),
    conn=Depends(get_db)
):
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT
                t.transaction_id,
                t.title,
                t.description,
                t.amount,
                t.type,
                t.date,
                t.created_at,
                COALESCE(c.name, 'Uncategorized') AS category
            FROM transactions t
            LEFT JOIN categories c ON t.category_id = c.category_id
            WHERE t.user_id = %s
            ORDER BY t.date DESC
            """,
            (current_user["user_id"],)
        )
        rows = await cur.fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail="No transactions to export.")

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "title", "description", "amount", "type", "date", "created_at", "category"])
    writer.writerows(rows)
    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=transactions.csv"}
    )

@router.get("/{transaction_id}")
async def get_transaction(
    transaction_id: int,
    current_user=Depends(get_current_user),
    conn=Depends(get_db)
):
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT
                t.transaction_id, t.title, t.description,
                t.amount, t.type, t.date, t.created_at,
                c.name AS category_name
            FROM transactions t
            LEFT JOIN categories c ON t.category_id = c.category_id
            WHERE t.transaction_id = %s AND t.user_id = %s
            """,
            (transaction_id, current_user["user_id"])
        )
        row = await cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Transaction not found")

    return {
        "transaction_id": row[0],
        "title": row[1],
        "description": row[2],
        "amount": float(row[3]),
        "type": row[4],
        "date": row[5],
        "created_at": row[6],
        "category_name": row[7],
    }

@router.put("/{transaction_id}")
async def update_transaction(
    transaction_id: int,
    req: TransactionUpdate,
    current_user=Depends(get_current_user),
    conn=Depends(get_db)
):
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT transaction_id FROM transactions WHERE transaction_id = %s AND user_id = %s",
            (transaction_id, current_user["user_id"])
        )
        if not await cur.fetchone():
            raise HTTPException(status_code=404, detail="Transaction not found")

        if req.category_id is not None:
            await cur.execute(
                "SELECT category_id FROM categories WHERE category_id = %s AND user_id = %s",
                (req.category_id, current_user["user_id"])
            )
            if not await cur.fetchone():
                raise HTTPException(status_code=404, detail="Category not found or doesn't belong to you")

        fields = []
        params = []

        if req.title is not None:
            fields.append("title = %s")
            params.append(req.title)
        if req.description is not None:
            fields.append("description = %s")
            params.append(req.description)
        if req.amount is not None:
            if req.amount <= 0:
                raise HTTPException(status_code=400, detail="Amount must be positive")
            fields.append("amount = %s")
            params.append(req.amount)
        if req.type is not None:
            if req.type not in ("income", "expense"):
                raise HTTPException(status_code=400, detail="Type must be 'income' or 'expense'")
            fields.append("type = %s")
            params.append(req.type)
        if req.category_id is not None:
            fields.append("category_id = %s")
            params.append(req.category_id)
        if req.date is not None:
            fields.append("date = %s")
            params.append(req.date)

        if not fields:
            raise HTTPException(status_code=400, detail="No fields to update")

        params.append(transaction_id)
        await cur.execute(
            f"UPDATE transactions SET {', '.join(fields)} WHERE transaction_id = %s",
            params
        )

    await conn.commit()
    return {"message": "Transaction updated"}


@router.delete("/{transaction_id}")
async def delete_transaction(
    transaction_id: int,
    current_user=Depends(get_current_user),
    conn=Depends(get_db)
):
    async with conn.cursor() as cur:
        await cur.execute(
            "DELETE FROM transactions WHERE transaction_id = %s AND user_id = %s",
            (transaction_id, current_user["user_id"])
        )
        deleted = cur.rowcount

    await conn.commit()

    if not deleted:
        raise HTTPException(status_code=404, detail="Transaction not found")

    return {"message": "Transaction deleted"}

