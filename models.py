from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import date as date_type


# AUTH
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str

# TRANSACTIONS
class TransactionCreate(BaseModel):
    title: str
    description: Optional[str] = None
    amount: float
    type: str
    category_id: Optional[int] = None
    date: date_type

class TransactionUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    amount: Optional[float] = None
    type: Optional[str] = None
    category_id: Optional[int] = None
    date: Optional[date_type] = None

# CATEGORIES
class CategoryCreate(BaseModel):
    name: str
    type: str  # "income", "expense", "asset"

class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None

# ASSETS
class AssetCreate(BaseModel):
    name: str
    ticker: str
    quantity: float
    buy_price: float
    current_price: Optional[float] = None
    purchase_date: date_type

class AssetUpdate(BaseModel):
    name: Optional[str] = None
    ticker: Optional[str] = None
    quantity: Optional[float] = None
    buy_price: Optional[float] = None
    current_price: Optional[float] = None
    purchase_date: Optional[date_type] = None

# ANALYSIS
class CategorySummary(BaseModel):
    category_name: str
    total_spent: float
    transaction_count: int

class MonthlySummary(BaseModel):
    month: str
    total_income: float
    total_expense: float
    net: float

class SummaryResponse(BaseModel):
    monthly: list[MonthlySummary]
    top_expense_categories: list[CategorySummary]
    total_income: float
    total_expense: float
    net_savings: float

class PredictionResponse(BaseModel):
    month: str
    predicted_expense: float
    confidence: str

class CategoryCluster(BaseModel):
    category_name: str
    cluster: int
    cluster_label: str
    avg_amount: float
    transaction_count: int

class ClusterResponse(BaseModel):
    clusters: list[CategoryCluster]

class AnomalyTransaction(BaseModel):
    transaction_id: int
    title: str
    amount: float
    category_name: Optional[str]
    date: str
    anomaly_score: float
    reason: str

class AnomalyResponse(BaseModel):
    anomalies: list[AnomalyTransaction]
    total_flagged: int

# CHAT
class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None