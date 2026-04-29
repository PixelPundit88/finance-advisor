from fastapi import APIRouter, Depends
from database import get_db
from errors import BadRequestException, NotFoundException
from routers.auth import get_current_user
from models import AssetCreate, AssetUpdate

router = APIRouter(prefix="/assets", tags=["assets"])

@router.get("/summary")
async def get_portfolio_summary(
    current_user=Depends(get_current_user),
    conn=Depends(get_db)
):
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT
                COUNT(*) AS total_assets,
                SUM(quantity * buy_price) AS total_invested,
                SUM(quantity * COALESCE(current_price, buy_price)) AS total_current_value
            FROM assets
            WHERE user_id = %s
            """,
            (current_user["user_id"],)
        )
        row = await cur.fetchone()

    total_invested = float(row[1] or 0)
    total_current = float(row[2] or 0)
    profit_loss = total_current - total_invested
    profit_loss_pct = (profit_loss / total_invested * 100) if total_invested > 0 else 0

    return {
        "total_assets": row[0],
        "total_invested": round(total_invested, 2),
        "total_current_value": round(total_current, 2),
        "profit_loss": round(profit_loss, 2),
        "profit_loss_pct": round(profit_loss_pct, 2)
    }


@router.get("/")
async def get_assets(
    current_user=Depends(get_current_user),
    conn=Depends(get_db)
):
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT
                asset_id,
                name,
                ticker,
                quantity,
                buy_price,
                current_price,
                purchase_date,
                -- profit/loss per asset
                ROUND((COALESCE(current_price, buy_price) - buy_price) * quantity, 2) AS profit_loss,
                -- profit/loss percentage
                ROUND(
                    CASE WHEN buy_price > 0
                    THEN ((COALESCE(current_price, buy_price) - buy_price) / buy_price) * 100
                    ELSE 0 END,
                2) AS profit_loss_pct
            FROM assets
            WHERE user_id = %s
            ORDER BY purchase_date DESC
            """,
            (current_user["user_id"],)
        )
        rows = await cur.fetchall()

    return [
        {
            "asset_id": r[0],
            "name": r[1],
            "ticker": r[2].upper(),
            "quantity": float(r[3]),
            "buy_price": float(r[4]),
            "current_price": float(r[5]) if r[5] else None,
            "purchase_date": r[6],
            "profit_loss": float(r[7]),
            "profit_loss_pct": float(r[8])
        }
        for r in rows
    ]


@router.post("/", status_code=201)
async def create_asset(
    req: AssetCreate,
    current_user=Depends(get_current_user),
    conn=Depends(get_db)
):
    async with conn.cursor() as cur:
        # check duplicate ticker for this user
        await cur.execute(
            "SELECT asset_id FROM assets WHERE user_id = %s AND ticker = %s",
            (current_user["user_id"], req.ticker.upper())
        )
        if await cur.fetchone():
            raise BadRequestException(
                f"Asset with ticker {req.ticker.upper()} already exists. Use PUT to update it."
            )

        await cur.execute(
            """
            INSERT INTO assets (user_id, name, ticker, quantity, buy_price, current_price, purchase_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING asset_id
            """,
            (
                current_user["user_id"],
                req.name,
                req.ticker.upper(),
                req.quantity,
                req.buy_price,
                req.current_price,
                req.purchase_date
            )
        )
        row = await cur.fetchone()

    await conn.commit()
    return {"message": "Asset created", "asset_id": row[0]}


@router.put("/{asset_id}")
async def update_asset(
    asset_id: int,
    req: AssetUpdate,
    current_user=Depends(get_current_user),
    conn=Depends(get_db)
):
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT asset_id FROM assets WHERE asset_id = %s AND user_id = %s",
            (asset_id, current_user["user_id"])
        )
        if not await cur.fetchone():
            raise NotFoundException("Asset not found")

        fields = []
        params = []

        for field, column in [
            (req.name, "name"),
            (req.ticker.upper() if req.ticker else None, "ticker"),
            (req.quantity, "quantity"),
            (req.buy_price, "buy_price"),
            (req.current_price, "current_price"),
            (req.purchase_date, "purchase_date"),
        ]:
            if field is not None:
                fields.append(f"{column} = %s")
                params.append(field)

        if not fields:
            raise BadRequestException("No fields to update")

        params.append(asset_id)
        await cur.execute(
            f"UPDATE assets SET {', '.join(fields)} WHERE asset_id = %s",
            params
        )

    await conn.commit()
    return {"message": "Asset updated"}


@router.delete("/{asset_id}")
async def delete_asset(
    asset_id: int,
    current_user=Depends(get_current_user),
    conn=Depends(get_db)
):
    async with conn.cursor() as cur:
        await cur.execute(
            "DELETE FROM assets WHERE asset_id = %s AND user_id = %s",
            (asset_id, current_user["user_id"])
        )
        deleted = cur.rowcount

    await conn.commit()

    if not deleted:
        raise NotFoundException("Asset not found")

    return {"message": "Asset deleted"}