from pathlib import Path
from typing import Any

PROMPTS_DIR = Path(__file__).resolve().parent

class PromptNotFoundError(Exception):
    """The requested prompt .md file does not exist."""
    pass

def load_prompt(name: str) -> str:
    path = PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise PromptNotFoundError(f"Prompt file '{name}.md' not found.")
    return path.read_text(encoding="utf-8")


async def build_financial_context(user_id: str, conn: Any) -> str:
    context_parts = []

    # Latest prediction
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT month, predicted_expense
            FROM predictions
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (user_id,),
        )
        prediction = await cur.fetchone()

    if prediction:
        context_parts.append(
            f"Predicted expense for {prediction[0].strftime('%Y-%m')}: ${float(prediction[1]):.2f}"
        )

    # Last 3 moths sum
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
            (user_id,),
        )
        monthly = await cur.fetchall()

    if monthly:
        context_parts.append("Recent monthly summary:")
        for m in monthly:
            net = float(m[1]) - float(m[2])
            context_parts.append(
                f"  {m[0]}: income=${float(m[1]):.2f}, expense=${float(m[2]):.2f}, net=${net:.2f}"
            )

    # Top expense categories
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
            (user_id,),
        )
        categories = await cur.fetchall()

    if categories:
        context_parts.append("Top expense categories:")
        for cat in categories:
            context_parts.append(f"  {cat[0]}: ${float(cat[1]):.2f}")

    # Recent Anomalies
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
            (user_id,),
        )
        anomalies = await cur.fetchall()

    if anomalies:
        context_parts.append("Flagged anomalies:")
        for a in anomalies:
            context_parts.append(f"  {a[0]} (${float(a[1]):.2f} in {a[2]}): {a[3]}")

    # Portfolio summary
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT
                SUM(quantity * buy_price) AS invested,
                SUM(quantity * COALESCE(current_price, buy_price)) AS current_value
            FROM assets
            WHERE user_id = %s
            """,
            (user_id,),
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