from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from database import get_db
from routers.auth import get_current_user
from openai import AsyncOpenAI
from openai.types.chat import (
    ChatCompletionSystemMessageParam,
    ChatCompletion,
)
from dotenv import load_dotenv
import os

load_dotenv()

router = APIRouter(prefix="/chat", tags=["chat"])

client = AsyncOpenAI(
    base_url=os.getenv("DEEPSEEK_BASE_URL"),
    api_key=os.getenv("DEEPSEEK_API_KEY"),
)

class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


async def get_financial_context(user_id: str, conn) -> str:
    context_parts = []


    async with conn.cursor() as cur:

        await cur.execute(
            """
            SELECT month, predicted_expense
            FROM predictions
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (user_id,)
        )
        prediction = await cur.fetchone()

    if prediction:
        context_parts.append(
            f"Predicted expense for {prediction[0].strftime('%Y-%m')}: ${float(prediction[1]):.2f}"
        )

    # LAST 3 MONTH SUMMARY
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT
                TO_CHAR(date, 'YYYY-MM') AS month,
                SUM(CASE WHEN type = 'income' THEN amount ELSE 0 END) AS income,
                SUM(CASE WHEN type = 'expense' THEN amount ELSE 0 END) AS expense
            FROM transactions
            WHERE user_id = %s
            GROUP BY TO_CHAR(date, 'YYYY-MM')
            ORDER BY TO_CHAR(date, 'YYYY-MM') DESC
            LIMIT 3
            """,
            (user_id,)
        )
        monthly = await cur.fetchall()

    if monthly:
        context_parts.append("Recent monthly summary:")
        for m in monthly:
            net = float(m[1]) - float(m[2])
            context_parts.append(
                f"  {m[0]}: income=${float(m[1]):.2f}, expense=${float(m[2]):.2f}, net=${net:.2f}"
            )

    async with conn.cursor() as cur:

        await cur.execute(
            """
            SELECT
                COALESCE(c.name, 'Uncategorized'),
                SUM(t.amount)
            FROM transactions t
            LEFT JOIN categories c ON t.category_id = c.category_id
            WHERE t.user_id = %s AND t.type = 'expense'
            GROUP BY c.name
            ORDER BY SUM(t.amount) DESC
            LIMIT 5
            """,
            (user_id,)
        )
        categories = await cur.fetchall()

    if categories:
        context_parts.append("Top expense categories:")
        for cat in categories:
            context_parts.append(f"  {cat[0]}: ${float(cat[1]):.2f}")

    # RECENT ANOMALIES
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT
                t.title,
                t.amount,
                COALESCE(c.name, 'Uncategorized'),
                a.reason
            FROM anomalies a
            JOIN transactions t ON a.transaction_id = t.transaction_id
            LEFT JOIN categories c ON t.category_id = c.category_id
            WHERE t.user_id = %s
            ORDER BY a.score DESC
            LIMIT 3
            """,
            (user_id,)
        )
        anomalies = await cur.fetchall()

    if anomalies:
        context_parts.append("Flagged anomalies:")
        for a in anomalies:
            context_parts.append(f"  {a[0]} (${float(a[1]):.2f} in {a[2]}): {a[3]}")

    # PORTFOLIO SUMMARY
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT
                SUM(quantity * buy_price) AS invested,
                SUM(quantity * COALESCE(current_price, buy_price)) AS current_value
            FROM assets
            WHERE user_id = %s
            """,
            (user_id,)
        )
        portfolio = await cur.fetchone()

    if portfolio and portfolio[0]:
        invested = float(portfolio[0])
        current = float(portfolio[1])
        pl = current - invested
        context_parts.append(
            f"Investment portfolio: invested=${invested:.2f}, current=${current:.2f}, P&L=${pl:.2f}"
        )

    return "\n".join(context_parts) if context_parts else "No financial data available yet."


@router.post("/")
async def chat(
    req: ChatRequest,
    current_user=Depends(get_current_user),
    conn=Depends(get_db)
):
    user_id = current_user["user_id"]

    session_id = None #CHANGE

    if req.session_id:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT session_id FROM chat_sessions WHERE session_id = %s AND user_id = %s",
                (req.session_id, user_id)
            )
            session = await cur.fetchone()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        session_id = req.session_id
    else:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO chat_sessions (user_id) VALUES (%s) RETURNING session_id",
                (user_id,)
            )
            row = await cur.fetchone()
            session_id = str(row[0])
        await conn.commit()


    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT role, content FROM chat_messages
            WHERE session_id = %s
            ORDER BY created_at
            """,
            (session_id,)
        )
        history = await cur.fetchall()


    financial_context = await get_financial_context(user_id, conn)

    # GENERAL PROMPT
    system_prompt = f"""
    You are a personal finance advisor with access to the user's financial data.
    Be concise, specific and actionable in your advice, a creative in a way.
    Always reference the actual numbers from their data when relevant.
    Do not make up data that isn't provided.

    Here is the user's current financial snapshot:
    {financial_context}
    """

    # MESSAGES LIST
    messages: list[ChatCompletionSystemMessageParam] = [
        {"role": "system", "content": system_prompt}
    ]
    for r in history:
        messages.append({"role": r[0], "content": r[1]})  # type: ignore
    messages.append({"role": "user", "content": req.message})  # type: ignore

    # DEEPSEEK API CALL
    response: ChatCompletion = await client.chat.completions.create(
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        messages=messages,
    )
    reply = response.choices[0].message.content

    # SAVE MESSAGE AND REPLY
    async with conn.cursor() as cur:
        await cur.executemany(
            """
            INSERT INTO chat_messages (session_id, role, content)
            VALUES (%s, %s, %s)
            """,
            [
                (session_id, "user", req.message),
                (session_id, "assistant", reply)
            ]
        )
    await conn.commit()

    return {
        "session_id": session_id,
        "reply": reply
    }


@router.get("/sessions")
async def get_sessions(
    current_user=Depends(get_current_user),
    conn=Depends(get_db)
):
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT session_id, created_at
            FROM chat_sessions
            WHERE user_id = %s
            ORDER BY created_at DESC
            """,
            (current_user["user_id"],)
        )
        rows = await cur.fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail="No chat sessions found.")

    return [
        {
            "session_id": str(r[0]),
            "created_at": r[1]
        }
        for r in rows
    ]


@router.get("/sessions/{session_id}")
async def get_session_history(
    session_id: str,
    current_user=Depends(get_current_user),
    conn=Depends(get_db)
):
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT session_id FROM chat_sessions WHERE session_id = %s AND user_id = %s",
            (session_id, current_user["user_id"])
        )
        if not await cur.fetchone():
            raise HTTPException(status_code=404, detail="Session not found")

    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT role, content, created_at
            FROM chat_messages
            WHERE session_id = %s
            ORDER BY created_at
            """,
            (session_id,)
        )
        rows = await cur.fetchall()

    return [
        {
            "role": r[0],
            "content": r[1],
            "created_at": r[2]
        }
        for r in rows
    ]


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    current_user=Depends(get_current_user),
    conn=Depends(get_db)
):
    async with conn.cursor() as cur:
        await cur.execute(
            "DELETE FROM chat_sessions WHERE session_id = %s AND user_id = %s",
            (session_id, current_user["user_id"])
        )
        deleted = cur.rowcount

    await conn.commit()

    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")

    return {"message": "Session deleted"}