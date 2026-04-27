from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
import bcrypt
from jose import JWTError, jwt
from datetime import datetime, timedelta, UTC
from database import get_db
from dotenv import load_dotenv
import os
from routers.defaults import DEFAULT_CATEGORIES

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY") or ''
ALGORITHM = os.getenv("ALGORITHM") or ''

if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY is not set in .env")
if not ALGORITHM:
    raise RuntimeError("ALGORITHM is not set in .env")

router = APIRouter(prefix="/auth", tags=["auth"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))

def create_token(user_id: str) -> str:
    expire = datetime.now(UTC) + timedelta(
        minutes=int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))
    )
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    conn=Depends(get_db)
):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = str(payload.get("sub", ""))
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT user_id, email FROM users WHERE user_id = %s", (user_id,)
        )
        row = await cur.fetchone()

    if row is None:
        raise HTTPException(status_code=401, detail="User not found")

    return {"user_id": str(row[0]), "email": row[1]}


@router.post("/register", status_code=201)
async def register(req: RegisterRequest, conn=Depends(get_db)):
    if len(req.password.encode("utf-8")) > 72:
        raise HTTPException(status_code=400, detail="Password cannot exceed 72 characters")
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT user_id FROM users WHERE email = %s", (req.email,)
        )
        if await cur.fetchone():
            raise HTTPException(status_code=400, detail="Email already registered")

        await cur.execute(
            "INSERT INTO users (email, password_hash) VALUES (%s, %s) RETURNING user_id",
            (req.email, hash_password(req.password))
        )
        row = await cur.fetchone()
        user_id = str(row[0])

        await cur.executemany(
            "INSERT INTO categories (user_id, name, type) VALUES (%s, %s, %s)",
            [(user_id, name, type_) for name, type_ in DEFAULT_CATEGORIES]
        )

    await conn.commit()
    return {"message": "User registered successfully", "user_id": user_id}


@router.post("/login", response_model=TokenResponse)
async def login(form: OAuth2PasswordRequestForm = Depends(), conn=Depends(get_db)):
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT user_id, password_hash FROM users WHERE email = %s", (form.username,)
        )
        row = await cur.fetchone()

    if not row or not verify_password(form.password, row[1]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_token(str(row[0]))
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me")
async def me(current_user=Depends(get_current_user)):
    return current_user