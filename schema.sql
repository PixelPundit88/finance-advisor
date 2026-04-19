CREATE TABLE IF NOT EXISTS users (
    user_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email         VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at    TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS categories (
    category_id SERIAL PRIMARY KEY,
    user_id     UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    name        VARCHAR(100) NOT NULL,
    type        VARCHAR(20) NOT NULL CHECK (type IN ('income', 'expense', 'asset'))
);

CREATE TABLE IF NOT EXISTS transactions (
    transaction_id SERIAL PRIMARY KEY,
    user_id        UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    category_id    INT REFERENCES categories(category_id) ON DELETE SET NULL,
    title          VARCHAR(255) NOT NULL,
    description    TEXT,
    amount         NUMERIC(10, 2) NOT NULL,
    type           VARCHAR(20) NOT NULL CHECK (type IN ('income', 'expense')),
    date           DATE NOT NULL,
    created_at     TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS assets (
    asset_id       SERIAL PRIMARY KEY,
    user_id        UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    name           VARCHAR(255) NOT NULL,
    ticker         VARCHAR(20) NOT NULL,
    quantity       NUMERIC(10, 4) NOT NULL,
    buy_price      NUMERIC(10, 2) NOT NULL,
    current_price  NUMERIC(10, 2),
    purchase_date  DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS predictions (
    prediction_id     SERIAL PRIMARY KEY,
    user_id           UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    month             DATE NOT NULL,
    predicted_expense NUMERIC(10, 2) NOT NULL,
    created_at        TIMESTAMP DEFAULT NOW(),
    CONSTRAINT unique_user_month UNIQUE (user_id, month)
);

CREATE TABLE IF NOT EXISTS anomalies (
    anomaly_id     SERIAL PRIMARY KEY,
    transaction_id INT NOT NULL REFERENCES transactions(transaction_id) ON DELETE CASCADE,
    score          FLOAT NOT NULL,
    reason         TEXT,
    flagged_at     TIMESTAMP DEFAULT NOW(),
    CONSTRAINT unique_transaction_anomaly UNIQUE (transaction_id)
);

CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chat_messages (
    message_id  SERIAL PRIMARY KEY,
    session_id  UUID NOT NULL REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
    role        VARCHAR(20) NOT NULL,
    content     TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT NOW()
);