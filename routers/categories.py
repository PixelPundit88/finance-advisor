from fastapi import APIRouter, Depends, HTTPException
from models import CategoryCreate, CategoryUpdate
from database import get_db
from routers.auth import get_current_user
from typing import Optional

router = APIRouter(prefix="/categories", tags=["categories"])

@router.get("/")
async def get_categories(
    _type: Optional[str] = None,
    current_user=Depends(get_current_user),
    conn=Depends(get_db)
):
    query = """
        SELECT category_id, name, type
        FROM categories
        WHERE user_id = %s
    """
    params = [current_user["user_id"]]

    if type:
        if type not in ("income", "expense", "asset"):
            raise HTTPException(status_code=400, detail="Type must be 'income', 'expense' or 'asset'")
        query += " AND type = %s"
        params.append(type)

    query += " ORDER BY type, name"

    async with conn.cursor() as cur:
        await cur.execute(query, params)
        rows = await cur.fetchall()

    return [
        {
            "category_id": r[0],
            "name": r[1],
            "type": r[2]
        }
        for r in rows
    ]


@router.post("/", status_code=201)
async def create_category(
    req: CategoryCreate,
    current_user=Depends(get_current_user),
    conn=Depends(get_db)
):
    if req.type not in ("income", "expense", "asset"):
        raise HTTPException(status_code=400, detail="Type must be 'income', 'expense' or 'asset'")

    async with conn.cursor() as cur:

        await cur.execute(
            "SELECT category_id FROM categories WHERE user_id = %s AND name = %s",
            (current_user["user_id"], req.name)
        )
        if await cur.fetchone():
            raise HTTPException(status_code=400, detail="Category with this name already exists")

        await cur.execute(
            "INSERT INTO categories (user_id, name, type) VALUES (%s, %s, %s) RETURNING category_id",
            (current_user["user_id"], req.name, req.type)
        )
        row = await cur.fetchone()

    await conn.commit()
    return {"message": "Category created", "category_id": row[0]}


@router.put("/{category_id}")
async def update_category(
    category_id: int,
    req: CategoryUpdate,
    current_user=Depends(get_current_user),
    conn=Depends(get_db)
):
    async with conn.cursor() as cur:

        await cur.execute(
            "SELECT category_id FROM categories WHERE category_id = %s AND user_id = %s",
            (category_id, current_user["user_id"])
        )
        if not await cur.fetchone():
            raise HTTPException(status_code=404, detail="Category not found")


        if req.name:
            await cur.execute(
                """
                SELECT category_id FROM categories
                WHERE user_id = %s AND name = %s AND category_id != %s
                """,
                (current_user["user_id"], req.name, category_id)
            )
            if await cur.fetchone():
                raise HTTPException(status_code=400, detail="Category with this name already exists")


        fields = []
        params = []

        if req.name is not None:
            fields.append("name = %s")
            params.append(req.name)
        if req.type is not None:
            if req.type not in ("income", "expense", "asset"):
                raise HTTPException(status_code=400, detail="Type must be 'income', 'expense' or 'asset'")
            fields.append("type = %s")
            params.append(req.type)

        if not fields:
            raise HTTPException(status_code=400, detail="No fields to update")

        params.append(category_id)
        await cur.execute(
            f"UPDATE categories SET {', '.join(fields)} WHERE category_id = %s",
            params
        )

    await conn.commit()
    return {"message": "Category updated"}


@router.delete("/{category_id}")
async def delete_category(
    category_id: int,
    current_user=Depends(get_current_user),
    conn=Depends(get_db)
):
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT COUNT(*) FROM transactions WHERE category_id = %s",
            (category_id,)
        )
        row = await cur.fetchone()
        if row[0] > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete — {row[0]} transaction(s) are using this category. Reassign them first."
            )

        await cur.execute(
            "DELETE FROM categories WHERE category_id = %s AND user_id = %s",
            (category_id, current_user["user_id"])
        )
        deleted = cur.rowcount

    await conn.commit()

    if not deleted:
        raise HTTPException(status_code=404, detail="Category not found")

    return {"message": "Category deleted"}