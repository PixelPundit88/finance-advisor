import pandas as pd

def build_transaction_df(rows) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["transaction_id", "title", "amount", "date", "category_name"])
    df["amount"] = df["amount"].astype(float)
    df["date"] = pd.to_datetime(df["date"])
    df["day_of_week"] = df["date"].dt.dayofweek
    df["day_of_month"] = df["date"].dt.day
    return df