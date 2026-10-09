import hashlib
import io
import json
import os
import secrets
import uuid
import calendar
import httpx
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import jwt
import pandas as pd
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jwt import InvalidTokenError
from pwdlib import PasswordHash
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address


class Settings(BaseSettings):
    database_url: str = "sqlite:///./fintwin.db"
    jwt_secret: str = ""
    access_token_minutes: int = 30
    upload_dir: str = str(Path(__file__).resolve().parents[1] / "uploads")
    model_dir: str = str(Path(__file__).resolve().parents[1] / "artifacts")
    frontend_origins: str = "http://localhost:5173"
    app_env: str = "development"
    redis_url: str = ""
    setu_base_url: str = "https://fiu-sandbox.setu.co"
    setu_client_id: str = ""
    setu_client_secret: str = ""
    setu_product_instance_id: str = ""
    setu_access_token: str = ""
    setu_redirect_url: str = "http://localhost:5173/"
    setu_auth_url: str = ""
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
if not settings.jwt_secret:
    if settings.app_env == "production":
        raise RuntimeError("JWT_SECRET must be set in production")
    settings.jwt_secret = secrets.token_urlsafe(48)
Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
Path(settings.model_dir).mkdir(parents=True, exist_ok=True)
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
password_hash = PasswordHash.recommended()
oauth2 = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(120), default="")
    city: Mapped[str] = mapped_column(String(100), default="")
    monthly_salary: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    essential_expenses: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    employment_status: Mapped[str] = mapped_column(String(30), default="Employed")
    experience: Mapped[str] = mapped_column(String(30), default="1–2 years")
    currency: Mapped[str] = mapped_column(String(16), default="INR")
    photo_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="owner", cascade="all, delete-orphan")
    goals: Mapped[list["Goal"]] = relationship(back_populates="owner", cascade="all, delete-orphan")


class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    merchant: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(80), index=True)
    kind: Mapped[str] = mapped_column(String(12))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(180), unique=True, nullable=True)
    owner: Mapped[User] = relationship(back_populates="transactions")


class Goal(Base):
    __tablename__ = "goals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    target_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    current_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    target_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    owner: Mapped[User] = relationship(back_populates="goals")


class Bill(Base):
    __tablename__ = "bills"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    category: Mapped[str] = mapped_column(String(80), default="Bills & utilities")
    due_date: Mapped[date] = mapped_column(Date)
    recurrence: Mapped[str] = mapped_column(String(12), default="monthly")
    reminder_days: Mapped[int] = mapped_column(default=3)
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("user_id", "bill_id", "due_date", name="uq_notification_bill_due"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    bill_id: Mapped[str | None] = mapped_column(ForeignKey("bills.id", ondelete="CASCADE"), nullable=True)
    title: Mapped[str] = mapped_column(String(160))
    message: Mapped[str] = mapped_column(String(400))
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class BankConnection(Base):
    __tablename__ = "bank_connections"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(40), default="setu_aa")
    consent_id: Mapped[str] = mapped_column(String(100), unique=True)
    consent_url: Mapped[str] = mapped_column(String(500))
    consent_status: Mapped[str] = mapped_column(String(30), default="PENDING")
    data_session_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    masked_accounts_json: Mapped[str] = mapped_column(Text, default="[]")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Dataset(Base):
    __tablename__ = "datasets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(500))
    checksum: Mapped[str] = mapped_column(String(64))
    rows: Mapped[int] = mapped_column(default=0)
    columns_json: Mapped[str] = mapped_column(Text, default="[]")
    validation_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class TrainingRun(Base):
    __tablename__ = "training_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"))
    target: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(24), default="queued")
    metrics_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ModelVersion(Base):
    __tablename__ = "model_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("training_runs.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(default=1)
    task: Mapped[str] = mapped_column(String(30))
    artifact_path: Mapped[str] = mapped_column(String(500))
    schema_json: Mapped[str] = mapped_column(Text)
    metrics_json: Mapped[str] = mapped_column(Text)
    approved: Mapped[bool] = mapped_column(default=False)
    active: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


app = FastAPI(title="FinTwin AI API", version="0.1.0", description="User-scoped financial tools and dataset-driven ML APIs.")
app.add_middleware(CORSMiddleware, allow_origins=[x.strip() for x in settings.frontend_origins.split(",")], allow_credentials=True, allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type"])
limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def token_for(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": user_id, "iat": now, "exp": now + timedelta(minutes=settings.access_token_minutes)}, settings.jwt_secret, algorithm="HS256")


def current_user(request: Request, token: str | None = Depends(oauth2), db: Session = Depends(get_db)) -> User:
    token = token or request.cookies.get("fintwin_session")
    if not token: raise HTTPException(status_code=401, detail="Sign in to continue", headers={"WWW-Authenticate":"Bearer"})
    try:
        user_id = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"]).get("sub")
    except InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Authentication expired or invalid", headers={"WWW-Authenticate": "Bearer"}) from exc
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication expired or invalid")
    return user


class RegisterInput(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    full_name: str = Field(min_length=1, max_length=120)


class TransactionInput(BaseModel):
    merchant: str = Field(min_length=1, max_length=160)
    category: str = Field(min_length=1, max_length=80)
    kind: str = Field(pattern="^(income|expense)$")
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    occurred_at: datetime | None = None
    note: str | None = Field(default=None, max_length=300)


class GoalInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    target_amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    current_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    target_date: datetime | None = None


class GoalProgressInput(BaseModel):
    current_amount: Decimal = Field(ge=0, max_digits=14, decimal_places=2)


class ProfileUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=120)
    city: str | None = Field(default=None, max_length=100)
    monthly_salary: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    essential_expenses: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    employment_status: str | None = Field(default=None, max_length=30)
    experience: str | None = Field(default=None, max_length=30)
    currency: str | None = Field(default=None, max_length=16)

class BillInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    category: str = Field(default="Bills & utilities", max_length=80)
    due_date: date
    recurrence: str = Field(default="monthly", pattern="^(once|weekly|monthly|yearly)$")
    reminder_days: int = Field(default=3, ge=0, le=30)

class BankConsentInput(BaseModel):
    vua: str = Field(min_length=6, max_length=100, pattern="^[^@\\s]{3,64}@[A-Za-z0-9.-]{2,100}$")
    from_date: date
    to_date: date

def bill_json(b: Bill) -> dict[str, Any]:
    return {"id":b.id,"name":b.name,"amount":str(b.amount),"category":b.category,"due_date":b.due_date.isoformat(),"recurrence":b.recurrence,"reminder_days":b.reminder_days,"active":b.active}

def make_bill_notifications(db: Session, user_id: str | None = None) -> int:
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date(); query = select(Bill).where(Bill.active.is_(True))
    if user_id: query = query.where(Bill.user_id == user_id)
    created = 0
    for bill in db.scalars(query).all():
        days = (bill.due_date - today).days
        if 0 <= days <= bill.reminder_days:
            existing = db.scalar(select(Notification).where(Notification.bill_id==bill.id, Notification.due_date==bill.due_date))
            if not existing:
                db.add(Notification(user_id=bill.user_id,bill_id=bill.id,due_date=bill.due_date,title=f"{bill.name} is due {('today' if days==0 else f'in {days} day(s)')}",message=f"{bill.category} · ₹{bill.amount} · due {bill.due_date.isoformat()}")); created += 1
    if created: db.commit()
    return created


def tx_json(t: Transaction) -> dict[str, Any]:
    return {"id": t.id, "merchant": t.merchant, "category": t.category, "kind": t.kind, "amount": str(t.amount), "occurred_at": t.occurred_at.isoformat(), "note": t.note}


@app.get("/health")
def health():
    return {"status": "ok", "service": "fintwin-api"}


@app.post("/api/v1/auth/register", status_code=201)
@limiter.limit("5/hour")
def register(request: Request, body: RegisterInput, response: Response, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == body.email.lower())):
        raise HTTPException(409, "An account with that email already exists")
    user = User(email=body.email.lower(), password_hash=password_hash.hash(body.password), full_name=body.full_name)
    db.add(user); db.commit(); db.refresh(user)
    token=token_for(user.id); response.set_cookie("fintwin_session",token,httponly=True,secure=settings.app_env=="production",samesite="lax",max_age=settings.access_token_minutes*60,path="/")
    return {"access_token": token, "token_type": "bearer", "user": {"id": user.id, "email": user.email, "full_name": user.full_name}}


@app.post("/api/v1/auth/token")
@limiter.limit("8/minute")
def login(request: Request, response: Response, form: Any = Depends(OAuth2PasswordRequestForm), db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == form.username.lower()))
    if not user or not password_hash.verify(form.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password", headers={"WWW-Authenticate": "Bearer"})
    token=token_for(user.id); response.set_cookie("fintwin_session",token,httponly=True,secure=settings.app_env=="production",samesite="lax",max_age=settings.access_token_minutes*60,path="/")
    return {"access_token": token, "token_type": "bearer"}


@app.get("/api/v1/auth/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "email": user.email, "full_name": user.full_name}


@app.get("/api/v1/profile")
def profile(user: User = Depends(current_user)):
    return {"id": user.id, "email": user.email, "full_name": user.full_name, "city": user.city, "monthly_salary": str(user.monthly_salary), "essential_expenses": str(user.essential_expenses), "employment_status": user.employment_status, "experience": user.experience, "currency": user.currency, "photo_path": user.photo_path}


@app.patch("/api/v1/profile")
def update_profile(body: ProfileUpdate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(user, key, value)
    db.commit()
    return {"id": user.id, "email": user.email, "full_name": user.full_name, "city": user.city, "monthly_salary": str(user.monthly_salary), "essential_expenses": str(user.essential_expenses), "employment_status": user.employment_status, "experience": user.experience, "currency": user.currency}


@app.post("/api/v1/profile/photo")
async def upload_photo(file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(current_user)):
    if file.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(415, "Upload a PNG, JPEG, or WebP image")
    data = await file.read(4_000_001)
    if len(data) > 4_000_000:
        raise HTTPException(413, "Image must be 4 MB or smaller")
    ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[file.content_type]
    name = f"{user.id}-{uuid.uuid4().hex}{ext}"
    Path(settings.upload_dir, name).write_bytes(data)
    user.photo_path = name; db.commit()
    return {"photo_path": name}


@app.get("/api/v1/profile/photo")
def get_profile_photo(user: User = Depends(current_user)):
    if not user.photo_path:
        raise HTTPException(404, "No profile photo has been uploaded")
    path = Path(settings.upload_dir, user.photo_path).resolve()
    if path.parent != Path(settings.upload_dir).resolve() or not path.is_file():
        raise HTTPException(404, "Profile photo not found")
    return FileResponse(path, headers={"Cache-Control": "private, no-store"})


@app.get("/api/v1/transactions")
def list_transactions(limit: int = 100, offset: int = 0, db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(select(Transaction).where(Transaction.user_id == user.id).order_by(Transaction.occurred_at.desc()).offset(offset).limit(min(max(limit, 1), 250))).all()
    return {"items": [tx_json(t) for t in rows], "offset": offset, "limit": limit}


@app.post("/api/v1/transactions", status_code=201)
def create_transaction(body: TransactionInput, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = Transaction(user_id=user.id, merchant=body.merchant.strip(), category=body.category.strip(), kind=body.kind, amount=body.amount, occurred_at=body.occurred_at or datetime.now(timezone.utc), note=body.note)
    db.add(row); db.commit(); db.refresh(row)
    return tx_json(row)


@app.delete("/api/v1/transactions/{record_id}", status_code=204)
def delete_transaction(record_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = db.scalar(select(Transaction).where(Transaction.id == record_id, Transaction.user_id == user.id))
    if not row: raise HTTPException(404, "Transaction not found")
    db.delete(row); db.commit()


@app.get("/api/v1/dashboard/summary")
def dashboard_summary(db: Session = Depends(get_db), user: User = Depends(current_user)):
    now = datetime.now(timezone.utc)
    rows = db.scalars(select(Transaction).where(Transaction.user_id == user.id)).all()
    rows = [t for t in rows if t.occurred_at.replace(tzinfo=t.occurred_at.tzinfo or timezone.utc) >= now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)]
    income = sum((t.amount for t in rows if t.kind == "income"), Decimal("0"))
    expenses = sum((t.amount for t in rows if t.kind == "expense"), Decimal("0"))
    savings = income - expenses
    return {"currency": "INR", "income": str(income), "expenses": str(expenses), "cash_flow": str(savings), "savings_rate": str(round(float(savings / income * 100), 2)) if income > 0 else None, "source": "user_records" if rows else "empty"}


@app.get("/api/v1/dashboard/spending-breakdown")
def spending_breakdown(db: Session = Depends(get_db), user: User = Depends(current_user)):
    now = datetime.now(timezone.utc)
    rows = db.scalars(select(Transaction).where(Transaction.user_id == user.id, Transaction.kind == "expense")).all()
    rows = [t for t in rows if t.occurred_at.replace(tzinfo=t.occurred_at.tzinfo or timezone.utc) >= now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)]
    result: dict[str, Decimal] = {}
    for row in rows: result[row.category] = result.get(row.category, Decimal("0")) + row.amount
    return {"items": [{"category": k, "amount": str(v)} for k, v in result.items()], "source": "user_records" if rows else "empty"}


@app.get("/api/v1/goals")
def list_goals(db: Session = Depends(get_db), user: User = Depends(current_user)):
    items = db.scalars(select(Goal).where(Goal.user_id == user.id)).all()
    return {"items": [{"id": g.id, "name": g.name, "target_amount": str(g.target_amount), "current_amount": str(g.current_amount), "target_date": g.target_date.isoformat() if g.target_date else None} for g in items]}


@app.get("/api/v1/bills")
def list_bills(db: Session = Depends(get_db), user: User = Depends(current_user)):
    make_bill_notifications(db, user.id)
    bills=db.scalars(select(Bill).where(Bill.user_id==user.id).order_by(Bill.due_date)).all()
    return {"items":[bill_json(b) for b in bills]}

@app.post("/api/v1/bills", status_code=201)
def create_bill(body: BillInput, db: Session=Depends(get_db), user: User=Depends(current_user)):
    bill=Bill(user_id=user.id, **body.model_dump()); db.add(bill); db.commit(); db.refresh(bill)
    make_bill_notifications(db,user.id)
    return bill_json(bill)

@app.patch("/api/v1/bills/{bill_id}")
def update_bill(bill_id: str, body: BillInput, db: Session=Depends(get_db), user: User=Depends(current_user)):
    bill=db.scalar(select(Bill).where(Bill.id==bill_id,Bill.user_id==user.id))
    if not bill: raise HTTPException(404,"Bill not found")
    for key,value in body.model_dump().items(): setattr(bill,key,value)
    db.commit(); db.refresh(bill); make_bill_notifications(db,user.id); return bill_json(bill)

@app.post("/api/v1/bills/{bill_id}/paid")
def pay_bill(bill_id: str, db: Session=Depends(get_db), user: User=Depends(current_user)):
    bill=db.scalar(select(Bill).where(Bill.id==bill_id,Bill.user_id==user.id, Bill.active.is_(True)))
    if not bill: raise HTTPException(404,"Active bill not found")
    tx=Transaction(user_id=user.id,merchant=bill.name,category=bill.category,kind="expense",amount=bill.amount,note="Bill payment")
    db.add(tx)
    if bill.recurrence=="once": bill.active=False
    elif bill.recurrence=="weekly": bill.due_date += timedelta(days=7)
    elif bill.recurrence=="yearly": bill.due_date=date(bill.due_date.year+1,bill.due_date.month,min(bill.due_date.day,calendar.monthrange(bill.due_date.year+1,bill.due_date.month)[1]))
    else:
        month=bill.due_date.month%12+1; year=bill.due_date.year+(bill.due_date.month//12)
        bill.due_date=date(year,month,min(bill.due_date.day,calendar.monthrange(year,month)[1]))
    db.commit(); make_bill_notifications(db,user.id); return {"bill":bill_json(bill),"transaction":tx_json(tx)}

@app.delete("/api/v1/bills/{bill_id}", status_code=204)
def delete_bill(bill_id: str, db: Session=Depends(get_db), user: User=Depends(current_user)):
    bill=db.scalar(select(Bill).where(Bill.id==bill_id,Bill.user_id==user.id))
    if not bill: raise HTTPException(404,"Bill not found")
    for notification in db.scalars(select(Notification).where(Notification.bill_id==bill.id)).all(): db.delete(notification)
    db.delete(bill); db.commit()

@app.get("/api/v1/notifications")
def list_notifications(db: Session=Depends(get_db), user: User=Depends(current_user)):
    make_bill_notifications(db,user.id)
    rows=db.scalars(select(Notification).where(Notification.user_id==user.id).order_by(Notification.created_at.desc()).limit(50)).all()
    return {"items":[{"id":n.id,"title":n.title,"message":n.message,"read":n.read_at is not None,"created_at":n.created_at.isoformat()} for n in rows]}

@app.patch("/api/v1/notifications/{notification_id}/read")
def read_notification(notification_id: str, db: Session=Depends(get_db), user: User=Depends(current_user)):
    n=db.scalar(select(Notification).where(Notification.id==notification_id,Notification.user_id==user.id))
    if not n: raise HTTPException(404,"Notification not found")
    n.read_at=datetime.now(timezone.utc); db.commit(); return {"id":n.id,"read":True}

def setu_headers() -> dict[str,str]:
    if not settings.setu_access_token or not settings.setu_product_instance_id:
        raise HTTPException(503,"Setu FIU product credentials and an access token are required. Bank passwords are never collected by FinTwin.")
    return {"Authorization":f"Bearer {settings.setu_access_token}","x-product-instance-id":settings.setu_product_instance_id,"Content-Type":"application/json"}

def setu_request(method: str, path: str, **kwargs):
    try:
        response=httpx.request(method,settings.setu_base_url.rstrip("/")+path,headers=setu_headers(),timeout=25,**kwargs)
    except httpx.HTTPError as exc: raise HTTPException(502,"Could not reach the configured Setu service") from exc
    if response.status_code >= 400: raise HTTPException(502,f"Setu request failed ({response.status_code}); check FIU credentials and configuration")
    return response.json() if response.content else {}

def connection_json(c: BankConnection):
    return {"id":c.id,"provider":c.provider,"consent_status":c.consent_status,"consent_url":c.consent_url,"accounts":json.loads(c.masked_accounts_json),"last_synced_at":c.last_synced_at.isoformat() if c.last_synced_at else None}

@app.get("/api/v1/bank-connections")
def list_bank_connections(db: Session=Depends(get_db), user: User=Depends(current_user)):
    return {"configured":bool(settings.setu_access_token and settings.setu_product_instance_id),"items":[connection_json(c) for c in db.scalars(select(BankConnection).where(BankConnection.user_id==user.id).order_by(BankConnection.created_at.desc())).all()]}

@app.post("/api/v1/bank-connections/consents", status_code=201)
def create_bank_consent(body: BankConsentInput, db: Session=Depends(get_db), user: User=Depends(current_user)):
    if body.from_date >= body.to_date or body.to_date > datetime.now(ZoneInfo("Asia/Kolkata")).date(): raise HTTPException(422,"Choose a valid date range ending today or earlier")
    payload={"consentDuration":{"unit":"MONTH","value":12},"consentMode":"STORE","fetchType":"ONETIME","consentTypes":["TRANSACTIONS"],"fiTypes":["DEPOSIT"],"vua":body.vua,"purpose":{"code":"102","text":"Personal finance management"},"dataRange":{"from":body.from_date.isoformat()+"T00:00:00Z","to":body.to_date.isoformat()+"T23:59:59Z"},"dataLife":{"unit":"MONTH","value":1},"frequency":{"unit":"MONTH","value":1},"redirectUrl":settings.setu_redirect_url}
    result=setu_request("POST","/consents",json=payload)
    cid=result.get("id") or result.get("consentId"); url=result.get("url") or result.get("consentUrl")
    if not cid or not url: raise HTTPException(502,"Setu did not return a consent ID and approval URL")
    conn=BankConnection(user_id=user.id,consent_id=cid,consent_url=url); db.add(conn); db.commit(); db.refresh(conn); return connection_json(conn)

@app.post("/api/v1/bank-connections/{connection_id}/refresh")
def refresh_bank_consent(connection_id: str, db: Session=Depends(get_db), user: User=Depends(current_user)):
    c=db.scalar(select(BankConnection).where(BankConnection.id==connection_id,BankConnection.user_id==user.id))
    if not c: raise HTTPException(404,"Connection not found")
    result=setu_request("GET",f"/consents/{c.consent_id}"); c.consent_status=str(result.get("status",c.consent_status)).upper()
    if c.consent_status in {"ACTIVE","READY"} and not c.data_session_id:
        session=setu_request("POST","/sessions",json={"consentId":c.consent_id}); c.data_session_id=session.get("id") or session.get("sessionId")
    db.commit(); return connection_json(c)

@app.post("/api/v1/bank-connections/{connection_id}/sync")
def sync_bank_data(connection_id: str, db: Session=Depends(get_db), user: User=Depends(current_user)):
    c=db.scalar(select(BankConnection).where(BankConnection.id==connection_id,BankConnection.user_id==user.id))
    if not c: raise HTTPException(404,"Connection not found")
    if not c.data_session_id: raise HTTPException(409,"Approve consent and refresh the connection first")
    result=setu_request("GET",f"/sessions/{c.data_session_id}"); data=result.get("data",result); imported=0; accounts=[]
    for fi in data.get("fips",[]):
        for account in fi.get("accounts",[]):
            masked=account.get("maskedAccountNumber") or account.get("masked_account_number")
            if masked: accounts.append({"masked_account_number":masked,"type":account.get("type","DEPOSIT")})
            txn_data=account.get("transactions",{}); txn_rows=txn_data.get("transaction",[]) if isinstance(txn_data,dict) else txn_data if isinstance(txn_data,list) else []
            for item in txn_rows:
                external=f"setu:{c.id}:{item.get('txnId') or item.get('transactionId') or hashlib.sha256(json.dumps(item,sort_keys=True).encode()).hexdigest()}"
                if db.scalar(select(Transaction).where(Transaction.external_ref==external)): continue
                amount=Decimal(str(item.get("amount","0"))); kind="income" if str(item.get("type",item.get("txnType","DEBIT"))).upper() in {"CREDIT","CR"} else "expense"
                date_value=item.get("valueDate") or item.get("transactionDate") or item.get("txnDate")
                parsed_date=pd.to_datetime(date_value,utc=True,errors="coerce") if date_value else None
                occurred=parsed_date.to_pydatetime() if parsed_date is not None and not pd.isna(parsed_date) else datetime.now(timezone.utc)
                db.add(Transaction(user_id=user.id,merchant=(item.get("narration") or item.get("txnNote") or "Bank transaction")[:160],category="Bank transaction",kind=kind,amount=abs(amount),occurred_at=occurred,note="Imported with user-approved Account Aggregator consent",external_ref=external)); imported+=1
    c.masked_accounts_json=json.dumps(accounts); c.last_synced_at=datetime.now(timezone.utc); db.commit()
    return {"imported":imported,"connection":connection_json(c)}

@app.delete("/api/v1/bank-connections/{connection_id}", status_code=204)
def revoke_bank_consent(connection_id: str, db: Session=Depends(get_db), user: User=Depends(current_user)):
    c=db.scalar(select(BankConnection).where(BankConnection.id==connection_id,BankConnection.user_id==user.id))
    if not c: raise HTTPException(404,"Connection not found")
    setu_request("POST",f"/consents/{c.consent_id}/revoke",json={}); c.consent_status="REVOKED"; db.commit()


@app.post("/api/v1/goals", status_code=201)
def create_goal(body: GoalInput, db: Session = Depends(get_db), user: User = Depends(current_user)):
    goal = Goal(user_id=user.id, name=body.name, target_amount=body.target_amount, current_amount=body.current_amount, target_date=body.target_date)
    db.add(goal); db.commit(); db.refresh(goal)
    return {"id": goal.id, "name": goal.name, "target_amount": str(goal.target_amount), "current_amount": str(goal.current_amount)}


@app.patch("/api/v1/goals/{goal_id}")
def update_goal_progress(goal_id: str, body: GoalProgressInput, db: Session = Depends(get_db), user: User = Depends(current_user)):
    goal = db.scalar(select(Goal).where(Goal.id == goal_id, Goal.user_id == user.id))
    if not goal:
        raise HTTPException(404, "Goal not found")
    goal.current_amount = body.current_amount
    db.commit(); db.refresh(goal)
    return {"id": goal.id, "name": goal.name, "target_amount": str(goal.target_amount), "current_amount": str(goal.current_amount), "target_date": goal.target_date.isoformat() if goal.target_date else None}


@app.delete("/api/v1/goals/{goal_id}", status_code=204)
def delete_goal(goal_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    goal = db.scalar(select(Goal).where(Goal.id == goal_id, Goal.user_id == user.id))
    if not goal:
        raise HTTPException(404, "Goal not found")
    db.delete(goal); db.commit()


@app.post("/api/v1/forecasts")
def forecast(months: int = 3, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if months not in (1, 2, 3): raise HTTPException(422, "Forecast horizon must be 1, 2, or 3 months")
    rows = db.scalars(select(Transaction).where(Transaction.user_id == user.id)).all()
    if len(rows) < 3: return {"status": "insufficient_data", "months": months, "minimum_records": 3, "assumptions": ["At least three records are needed for this baseline."]}
    incomes = [float(t.amount) for t in rows if t.kind == "income"]; expenses = [float(t.amount) for t in rows if t.kind == "expense"]
    avg_income = sum(incomes)/max(len(incomes),1); avg_expenses = sum(expenses)/max(len(expenses),1)
    return {"status":"baseline_estimate","months":[{"month":i+1,"income":round(avg_income,2),"expenses":round(avg_expenses,2),"net":round(avg_income-avg_expenses,2)} for i in range(months)],"assumptions":["Simple average of recorded transactions; no seasonality or scheduled items assumed."],"source":"user_records"}


@app.post("/api/v1/simulations")
def simulate(monthly_contribution: Decimal = Form(...), annual_return_percent: Decimal = Form(...), years: int = Form(...), user: User = Depends(current_user)):
    if monthly_contribution < 0 or not 0 <= annual_return_percent <= 30 or not 1 <= years <= 50: raise HTTPException(422, "Invalid simulation assumptions")
    r = float(annual_return_percent) / 1200
    fv = float(monthly_contribution) * (((1+r)**(years*12)-1)/r) if r else float(monthly_contribution)*years*12
    return {"projected_value": round(fv,2), "contributions": str(monthly_contribution*12*years), "assumptions":{"annual_return_percent":str(annual_return_percent),"years":years,"compounding":"monthly"},"disclaimer":"Illustrative calculation; returns are not guaranteed."}


@app.post("/api/v1/datasets")
async def upload_dataset(file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(current_user)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".csv", ".xlsx", ".xls"}: raise HTTPException(415, "Upload a CSV or Excel file")
    data = await file.read(20_000_001)
    if len(data) > 20_000_000: raise HTTPException(413, "Dataset must be 20 MB or smaller")
    try:
        frame = pd.read_csv(io.BytesIO(data)) if suffix == ".csv" else pd.read_excel(io.BytesIO(data))
    except Exception as exc:
        raise HTTPException(422, "Could not parse the dataset. Check its file format and encoding.") from exc
    if frame.empty or len(frame.columns) == 0: raise HTTPException(422, "Dataset has no data rows or columns")
    if len(frame) > 250_000 or len(frame.columns) > 150: raise HTTPException(422, "Dataset exceeds the 250,000 row or 150 column limit")
    columns = [{"name":str(c),"dtype":str(frame[c].dtype),"missing":int(frame[c].isna().sum()),"unique":int(frame[c].nunique(dropna=True))} for c in frame.columns]
    # Dataset content stays private to this account. Names are never used as file paths.
    dataset_id = str(uuid.uuid4()); checksum = hashlib.sha256(data).hexdigest()
    stored = Path(settings.upload_dir, f"{user.id}-{dataset_id}{suffix}"); stored.write_bytes(data)
    report = {"rows":len(frame),"columns":len(columns),"duplicate_rows":int(frame.duplicated().sum()),"missing_cells":int(frame.isna().sum().sum()),"warnings":(["Dataset contains personally identifying field names; review before training."] if any(x in str(c['name']).lower() for c in columns for x in ["email","phone","name","address","account"]) else [])}
    item = Dataset(id=dataset_id,user_id=user.id,filename=Path(file.filename or "dataset").name,stored_path=str(stored),checksum=checksum,rows=len(frame),columns_json=json.dumps(columns),validation_json=json.dumps(report))
    db.add(item); db.commit()
    return {"id":dataset_id,"filename":item.filename,"checksum":checksum,"validation":report,"columns":columns}


@app.get("/api/v1/datasets")
def list_datasets(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(select(Dataset).where(Dataset.user_id == user.id).order_by(Dataset.created_at.desc())).all()
    return {"items":[{"id":d.id,"filename":d.filename,"rows":d.rows,"checksum":d.checksum,"created_at":d.created_at.isoformat()} for d in rows]}


def background_train(run_id: str, dataset_id: str, target: str, feature_columns: str, task: str, user_id: str):
    db=SessionLocal()
    try:
        user=db.get(User,user_id)
        if user: train_model(dataset_id,target,feature_columns,task,db=db,user=user,run_id=run_id)
    except Exception as exc:
        run=db.get(TrainingRun,run_id)
        if run: run.status="failed"; run.metrics_json=json.dumps({"error":str(exc)[:300]}); db.commit()
    finally: db.close()

try:
    from celery import Celery
    celery_app = Celery("fintwin", broker=settings.redis_url or "redis://localhost:6379/0")
    celery_app.conf.beat_schedule = {"daily-bill-reminders": {"task":"app.main.daily_bill_reminders","schedule":86400.0}}
    celery_app.conf.timezone = "UTC"
    @celery_app.task(name="app.main.queued_training")
    def queued_training(run_id, dataset_id, target, feature_columns, task, user_id):
        background_train(run_id,dataset_id,target,feature_columns,task,user_id)
    @celery_app.task(name="app.main.daily_bill_reminders")
    def daily_bill_reminders():
        db=SessionLocal()
        try: make_bill_notifications(db)
        finally: db.close()
except ImportError:
    celery_app = None

@app.post("/api/v1/training-runs", status_code=202)
def train_model(dataset_id: str = Form(...), target: str = Form(...), feature_columns: str = Form(...), task: str = Form("regression"), background_tasks: BackgroundTasks = None, db: Session = Depends(get_db), user: User = Depends(current_user), run_id: str | None = None):
    dataset = db.scalar(select(Dataset).where(Dataset.id == dataset_id, Dataset.user_id == user.id))
    if not dataset: raise HTTPException(404,"Dataset not found")
    if run_id:
        queued_run=db.scalar(select(TrainingRun).where(TrainingRun.id==run_id,TrainingRun.user_id==user.id,TrainingRun.dataset_id==dataset.id))
        if not queued_run: raise HTTPException(404,"Training run not found")
    path = Path(dataset.stored_path); suffix=path.suffix.lower()
    frame = pd.read_csv(path) if suffix==".csv" else pd.read_excel(path)
    features = json.loads(feature_columns)
    if target not in frame.columns or not features or any(f not in frame.columns for f in features): raise HTTPException(422,"Target and all feature columns must exist in the uploaded dataset")
    if target in features: raise HTTPException(422,"Target column cannot also be a feature")
    if frame[target].isna().any(): raise HTTPException(422,"Target values contain missing rows; resolve these before training")
    if len(frame)<30: raise HTTPException(422,"At least 30 labelled rows are required for a train/test evaluation")
    if task not in {"regression","classification"}: raise HTTPException(422,"Task must be regression or classification")
    if task == "regression" and not pd.api.types.is_numeric_dtype(frame[target]): raise HTTPException(422,"Regression target must be numeric")
    if task == "classification" and frame[target].nunique()<2: raise HTTPException(422,"Classification target must contain at least two classes")
    # Never allow identifiable fields or known future outcomes to silently become predictors.
    pii_tokens={"user","id","name","full","email","phone","address","account","pan","aadhaar"}
    if any(str(col).strip().lower() in {"age","city"} or set(str(col).strip().lower().split("_")) & pii_tokens for col in features): raise HTTPException(422,"Remove personally identifying fields from the feature list")
    future_labels={"had_layoff_in_year","min_savings_12m","savings_12m_actual","risk_flag_12m"}
    if any(str(col).strip().lower() in future_labels for col in features): raise HTTPException(422,"Remove future outcome labels from the feature list to prevent target leakage")
    from sklearn.compose import ColumnTransformer
    from sklearn.dummy import DummyClassifier, DummyRegressor
    from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
    from sklearn.impute import SimpleImputer
    from sklearn.metrics import accuracy_score, f1_score, mean_absolute_error, mean_squared_error, precision_score, r2_score, recall_score
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder
    import joblib
    clean=frame[features+[target]].dropna(subset=[target]).copy()
    if len(clean)<30: raise HTTPException(422,"Fewer than 30 labelled rows remain after validation")
    if len(clean)>50_000 and not run_id:
        run=TrainingRun(user_id=user.id,dataset_id=dataset.id,target=target,status="queued",metrics_json="{}")
        db.add(run); db.commit(); db.refresh(run)
        if background_tasks is None: raise HTTPException(503,"Background training is unavailable")
        if settings.redis_url and celery_app:
            try: queued_training.delay(run.id,dataset_id,target,feature_columns,task,user.id)
            except Exception as exc:
                run.status="failed"; run.metrics_json=json.dumps({"error":"Background queue is unavailable"}); db.commit()
                raise HTTPException(503,"The background training queue is unavailable") from exc
        else:
            background_tasks.add_task(background_train,run.id,dataset_id,target,feature_columns,task,user.id)
        return {"id":run.id,"status":"queued","message":"Large dataset queued for background training","rows":len(clean)}
    X=clean[features]; y=clean[target]
    numeric=[c for c in features if pd.api.types.is_numeric_dtype(X[c])]
    categorical=[c for c in features if c not in numeric]
    pre=ColumnTransformer(transformers=[("numeric",Pipeline([("impute",SimpleImputer(strategy="median"))]),numeric),("categorical",Pipeline([("impute",SimpleImputer(strategy="most_frequent")),("encode",OneHotEncoder(handle_unknown="ignore"))]),categorical)],remainder="drop")
    if task=="classification" and y.value_counts().min()<5:
        raise HTTPException(422,"Each class needs at least five labelled rows for a stratified train/validation/test split")
    stratify=y if task=="classification" else None
    try:
        X_train,X_holdout,y_train,y_holdout=train_test_split(X,y,test_size=.3,random_state=42,stratify=stratify)
        stratify_holdout=y_holdout if task=="classification" else None
        X_val,X_test,y_val,y_test=train_test_split(X_holdout,y_holdout,test_size=.5,random_state=43,stratify=stratify_holdout)
        if task=="regression":
            baseline=Pipeline([("preprocess",pre), ("model",DummyRegressor(strategy="mean"))])
            candidate=Pipeline([("preprocess",pre), ("model",RandomForestRegressor(n_estimators=160,min_samples_leaf=2,random_state=42,n_jobs=-1))])
        else:
            baseline=Pipeline([("preprocess",pre), ("model",DummyClassifier(strategy="most_frequent"))])
            candidate=Pipeline([("preprocess",pre), ("model",RandomForestClassifier(n_estimators=160,min_samples_leaf=2,random_state=42,class_weight="balanced",n_jobs=-1))])
        baseline.fit(X_train,y_train);candidate.fit(X_train,y_train)
        candidate_val=candidate.predict(X_val);baseline_val=baseline.predict(X_val)
        if task=="regression":
            use_candidate=mean_absolute_error(y_val,candidate_val)<=mean_absolute_error(y_val,baseline_val)
        else:
            use_candidate=f1_score(y_val,candidate_val,average="macro",zero_division=0)>=f1_score(y_val,baseline_val,average="macro",zero_division=0)
        selected=candidate if use_candidate else baseline
        pred=selected.predict(X_test);base_pred=baseline.predict(X_test);candidate_pred=candidate.predict(X_test)
    except Exception as exc:
        raise HTTPException(422,f"Could not train on this dataset split: {type(exc).__name__}") from exc
    if task=="regression":
        metrics={"mae":float(mean_absolute_error(y_test,pred)),"rmse":float(mean_squared_error(y_test,pred)**.5),"r2":float(r2_score(y_test,pred)),"baseline_mae":float(mean_absolute_error(y_test,base_pred)),"baseline_rmse":float(mean_squared_error(y_test,base_pred)**.5),"candidate_mae":float(mean_absolute_error(y_test,candidate_pred)),"selected_model":"random_forest" if use_candidate else "dummy_baseline"}
    else:
        metrics={"accuracy":float(accuracy_score(y_test,pred)),"precision_macro":float(precision_score(y_test,pred,average="macro",zero_division=0)),"recall_macro":float(recall_score(y_test,pred,average="macro",zero_division=0)),"f1_macro":float(f1_score(y_test,pred,average="macro",zero_division=0)),"baseline_accuracy":float(accuracy_score(y_test,base_pred)),"candidate_f1_macro":float(f1_score(y_test,candidate_pred,average="macro",zero_division=0)),"label_count":int(y.nunique()),"selected_model":"random_forest" if use_candidate else "dummy_baseline"}
    run=db.get(TrainingRun,run_id) if run_id else None
    if run:
        run.status="completed_pending_approval"; run.metrics_json=json.dumps(metrics)
    else:
        run=TrainingRun(user_id=user.id,dataset_id=dataset.id,target=target,status="completed_pending_approval",metrics_json=json.dumps(metrics))
        db.add(run)
    db.flush()
    version_number=(db.scalar(select(ModelVersion).where(ModelVersion.user_id==user.id).order_by(ModelVersion.created_at.desc())) or None)
    version=(version_number.version+1) if version_number else 1
    artifact=Path(settings.model_dir,f"{user.id}-{run.id}.joblib")
    schema={"target":target,"features":features,"dtypes":{c:str(X[c].dtype) for c in features},"categorical":categorical,"numeric":numeric,"split":"70/15/15 stratified random; seeds=42,43","test_rows":len(X_test),"validation_rows":len(X_val),"train_rows":len(X_train)}
    joblib.dump({"pipeline":selected,"schema":schema,"dataset_checksum":dataset.checksum,"task":task},artifact)
    model=ModelVersion(user_id=user.id,run_id=run.id,version=version,task=task,artifact_path=str(artifact),schema_json=json.dumps(schema),metrics_json=json.dumps(metrics))
    db.add(model);db.commit()
    return {"id":run.id,"status":run.status,"model_id":model.id,"version":version,"task":task,"rows":len(clean),"features":features,"target":target,"metrics":metrics,"baseline_included":True,"approval_required":True,"model_active":False}


@app.get("/api/v1/training-runs")
def training_runs(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows=db.scalars(select(TrainingRun).where(TrainingRun.user_id==user.id).order_by(TrainingRun.created_at.desc())).all()
    return {"items":[{"id":r.id,"dataset_id":r.dataset_id,"target":r.target,"status":r.status,"metrics":json.loads(r.metrics_json)} for r in rows]}

@app.get("/api/v1/training-runs/{run_id}")
def training_run_status(run_id: str, db: Session=Depends(get_db), user: User=Depends(current_user)):
    run=db.scalar(select(TrainingRun).where(TrainingRun.id==run_id,TrainingRun.user_id==user.id))
    if not run: raise HTTPException(404,"Training run not found")
    model=db.scalar(select(ModelVersion).where(ModelVersion.run_id==run.id))
    metrics=json.loads(run.metrics_json or "{}")
    return {"id":run.id,"status":run.status,"metrics":metrics,"model_id":model.id if model else None,"version":model.version if model else None,"task":model.task if model else None,"target":run.target}


@app.get("/api/v1/models")
def list_models(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows=db.scalars(select(ModelVersion).where(ModelVersion.user_id==user.id).order_by(ModelVersion.created_at.desc())).all()
    return {"items":[{"id":m.id,"version":m.version,"task":m.task,"metrics":json.loads(m.metrics_json),"approved":m.approved,"active":m.active,"created_at":m.created_at.isoformat()} for m in rows]}


@app.post("/api/v1/models/{model_id}/activate")
def activate_model(model_id: str, db: Session=Depends(get_db), user: User=Depends(current_user)):
    model=db.scalar(select(ModelVersion).where(ModelVersion.id==model_id,ModelVersion.user_id==user.id))
    if not model: raise HTTPException(404,"Model not found")
    if not Path(model.artifact_path).is_file(): raise HTTPException(409,"Trusted model artifact is missing")
    for other in db.scalars(select(ModelVersion).where(ModelVersion.user_id==user.id,ModelVersion.task==model.task)).all():
        other.active=False
    model.approved=True;model.active=True;db.commit()
    return {"id":model.id,"version":model.version,"approved":True,"active":True}


@app.post("/api/v1/models/{model_id}/predict")
def predict(model_id: str, payload: dict[str,Any], db: Session=Depends(get_db), user: User=Depends(current_user)):
    model=db.scalar(select(ModelVersion).where(ModelVersion.id==model_id,ModelVersion.user_id==user.id,ModelVersion.approved.is_(True)))
    if not model: raise HTTPException(404,"Approved model not found")
    path=Path(model.artifact_path).resolve()
    if Path(settings.model_dir).resolve() not in path.parents or not path.is_file(): raise HTTPException(409,"Artifact is outside the trusted model registry")
    import joblib
    bundle=joblib.load(path)
    features=bundle["schema"]["features"]
    if set(payload.keys())!=set(features): raise HTTPException(422,"Input fields must match the approved model feature schema")
    frame=pd.DataFrame([payload],columns=features)
    result=bundle["pipeline"].predict(frame)[0]
    return {"model_id":model.id,"version":model.version,"prediction":result.item() if hasattr(result,"item") else result,"task":model.task}


@app.get("/api/v1/ml/guide")
def ml_guide():
    return {"status":"ready_for_dataset","supported_uploads":["csv","xlsx","xls"],"supported_training":["regression","classification"],"guardrails":["No training occurs until an uploaded dataset and target are selected.","Transformations are fit on training data only.","Evaluate candidates against a simple baseline.","Require explicit approval before model activation.","Keep raw datasets private to the uploading account."]}
