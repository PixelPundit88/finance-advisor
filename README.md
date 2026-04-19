# Personal Finance Advisor API

A FastAPI backend with PostgreSQL, scikit-learn ML analysis and DeepSeek AI advisor.

## Stack
- FastAPI
- PostgreSQL + psycopg3
- scikit-learn (Linear Regression, KMeans, Isolation Forest)
- DeepSeek API
- JWT Authentication

## Setup

1. Clone the repo
2. Create virtual environment
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
```
3. Install dependencies
```bash
pip install -r requirements.txt
```
4. Copy `.env.example` to `.env` and fill in your values
```bash
cp .env.example .env
```
5. Create PostgreSQL database and run schema
```bash
psql -U postgres -c "CREATE DATABASE FinDB;"
psql -U postgres -d FinDB -f schema.sql
```
6. Run the app
```bash
uvicorn main:app --reload
```
7. Visit `http://127.0.0.1:8000/docs`

## Endpoints

### Auth
- `POST /auth/register`
- `POST /auth/login`
- `GET /auth/me`

### Transactions
- `POST /transactions/`
- `GET /transactions/`
- `GET /transactions/export`
- `GET /transactions/{id}`
- `PUT /transactions/{id}`
- `DELETE /transactions/{id}`

### Categories
- `GET /categories/`
- `POST /categories/`
- `PUT /categories/{id}`
- `DELETE /categories/{id}`

### Assets
- `GET /assets/summary`
- `GET /assets/`
- `POST /assets/`
- `PUT /assets/{id}`
- `DELETE /assets/{id}`

### Analysis
- `GET /analysis/summary`
- `GET /analysis/predict`
- `GET /analysis/clusters`
- `GET /analysis/anomalies`

### Predictions
- `GET /predictions/`
- `GET /predictions/{id}`
- `DELETE /predictions/{id}`

### Anomalies
- `GET /anomalies/`
- `GET /anomaly/{id}`
- `DELETE /anomalies/{id}`

### Chat
- `POST /chat/`
- `GET /chat/sessions`
- `GET /chat/sessions/{id}`
- `DELETE /chat/sessions/{id}`