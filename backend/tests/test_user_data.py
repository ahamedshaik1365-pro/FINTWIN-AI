from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from pathlib import Path
import json

from app.main import Base, app, get_db, settings


engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
Base.metadata.create_all(engine)


def override_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_db
client = TestClient(app)


def register(email: str, name: str):
    response = client.post("/api/v1/auth/register", json={"email": email, "password": "example-password-123", "full_name": name})
    assert response.status_code == 201, response.text
    return response.json()["access_token"]


def test_transactions_and_dashboard_are_user_scoped():
    token_a = register("a@example.com", "A")
    token_b = register("b@example.com", "B")
    auth_a = {"Authorization": f"Bearer {token_a}"}
    auth_b = {"Authorization": f"Bearer {token_b}"}

    added = client.post("/api/v1/transactions", headers=auth_a, json={"merchant":"Salary","category":"Income","kind":"income","amount":"92000"})
    assert added.status_code == 201
    client.post("/api/v1/transactions", headers=auth_a, json={"merchant":"Rent","category":"Housing","kind":"expense","amount":"18200"})

    summary = client.get("/api/v1/dashboard/summary", headers=auth_a).json()
    assert summary["income"] == "92000.00"
    assert summary["expenses"] == "18200.00"
    assert client.get("/api/v1/transactions", headers=auth_b).json()["items"] == []
    assert client.get("/api/v1/dashboard/summary", headers=auth_b).json()["source"] == "empty"


def test_invalid_transaction_amount_is_rejected():
    token = register("c@example.com", "C")
    response = client.post("/api/v1/transactions", headers={"Authorization":f"Bearer {token}"}, json={"merchant":"Invalid","category":"Other","kind":"expense","amount":"-1"})
    assert response.status_code == 422


def test_supplied_synthetic_users_dataset_trains_against_a_baseline(monkeypatch):
    tmp_path=Path(__file__).resolve().parents[1]/".test-runtime"
    monkeypatch.setattr(settings,"model_dir",str(tmp_path/"models"))
    monkeypatch.setattr(settings,"upload_dir",str(tmp_path/"uploads"))
    Path(settings.model_dir).mkdir(parents=True)
    Path(settings.upload_dir).mkdir(parents=True)
    token=register("ml@example.com","ML User")
    headers={"Authorization":f"Bearer {token}"}
    sample=Path(__file__).resolve().parents[2]/"public"/"datasets"/"users.csv"
    with sample.open("rb") as stream:
        uploaded=client.post("/api/v1/datasets",headers=headers,files={"file":("fintwin_synthetic_users.csv",stream,"text/csv")})
    assert uploaded.status_code==200
    data=uploaded.json()
    assert data["validation"]["rows"]==500
    assert len(data["checksum"])==64
    features=["salary","monthly_expenses","emi_obligations","savings","current_fund","experience_years","city_tier","company_type","housing_type","supports_family","lifestyle_type","previous_salary","previous_discretionary","emi_ratio","emi_stress_score","monthly_surplus"]
    trained=client.post("/api/v1/training-runs",headers=headers,data={"dataset_id":data["id"],"target":"risk_flag_12m","feature_columns":json.dumps(features),"task":"classification"})
    assert trained.status_code==202, trained.text
    result=trained.json()
    assert result["approval_required"] is True
    assert result["model_active"] is False
    assert result["metrics"]["selected_model"] in {"random_forest","dummy_baseline"}
    assert "f1_macro" in result["metrics"]
    assert result["metrics"]["label_count"]==3
    print("Synthetic holdout metrics:",result["metrics"])
    activated=client.post(f"/api/v1/models/{result['model_id']}/activate",headers=headers)
    assert activated.status_code==200
    import pandas as pd
    record=json.loads(pd.read_csv(sample,usecols=features).iloc[0].to_json())
    prediction=client.post(f"/api/v1/models/{result['model_id']}/predict",headers=headers,json=record)
    assert prediction.status_code==200
    assert prediction.json()["task"]=="classification"
    assert prediction.json()["prediction"] in {"Low","Medium","High"}
    other=register("other-ml@example.com","Other")
    hidden=client.get("/api/v1/models",headers={"Authorization":f"Bearer {other}"})
    assert hidden.json()["items"]==[]
