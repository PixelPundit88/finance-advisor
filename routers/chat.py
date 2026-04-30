from fastapi import APIRouter, Depends
from database import get_db
from routers.auth import get_current_user
from openai import AsyncOpenAI
from openai.types.chat import (
    ChatCompletionSystemMessageParam,
    ChatCompletion,
)
from dotenv import load_dotenv
from models import ChatRequest
from errors import NotFoundException, BadRequestException, logger
from prompts.services import load_prompt, build_financial_context
import os

load_dotenv()

router = APIRouter(prefix="/chat", tags=["chat"])

client = AsyncOpenAI(
    base_url=os.getenv("DEEPSEEK_BASE_URL"),
    api_key=os.getenv("DEEPSEEK_API_KEY"),
)


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
            raise NotFoundException("Session not found.")
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

    try:
        financial_context = await build_financial_context(user_id, conn)
    except Exception:
        logger.exception("Failed to build financial context.")
        raise BadRequestException("Unable to load your financial data at the moment.")

    # GENERAL PROMPT
    system_prompt = load_prompt("advisor_prompt").format(financial_context=financial_context)

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
        raise NotFoundException("No chat sessions found.")

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
            raise NotFoundException("Session not found.")

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
        raise NotFoundException("Session not found.")

    return {"message": "Session deleted"}