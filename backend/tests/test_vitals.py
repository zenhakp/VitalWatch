"""
Tests for vitals ingestion, retrieval, anomaly detection, and simulator.
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.main import app
from app.db.database import get_db
from app.db.models import Base

TEST_DATABASE_URL = "sqlite+aiosqlite:///./test_vitals.db"
test_engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
TestSessionLocal = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


async def override_get_db():
    async with TestSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


app.dependency_overrides[get_db] = override_get_db

NORMAL_VITALS = {
    "heart_rate": 75.0,
    "spo2": 98.0,
    "blood_pressure_sys": 120.0,
    "blood_pressure_dia": 80.0,
    "temperature": 36.8,
    "respiratory_rate": 16.0,
}


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def patient_token(client):
    await client.post("/api/v1/auth/register", json={
        "email": "patient@vitals.com",
        "password": "testpass123",
        "full_name": "Vitals Patient",
        "phone": "9876543210",
        "role": "patient",
    })
    resp = await client.post("/api/v1/auth/login", json={
        "email": "patient@vitals.com",
        "password": "testpass123",
    })
    return resp.json()["access_token"]


@pytest_asyncio.fixture
async def patient_id(client, patient_token):
    resp = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {patient_token}"}
    )
    return resp.json()["id"]


@pytest_asyncio.fixture
async def doctor_token(client):
    await client.post("/api/v1/auth/register", json={
        "email": "doctor@vitals.com",
        "password": "testpass123",
        "full_name": "Dr Vitals",
        "phone": "9876543210",
        "role": "doctor",
    })
    # Doctor needs OTP — for tests we skip OTP by using a patient account
    # In real integration tests you'd mock the OTP
    return None


# ── Vitals Ingestion ──────────────────────────────────────────────────────────

class TestVitalsIngestion:
    async def test_ingest_normal_vitals_success(self, client, patient_token, patient_id):
        payload = {"patient_id": patient_id, **NORMAL_VITALS}
        resp = await client.post(
            "/api/v1/vitals/ingest",
            json=payload,
            headers={"Authorization": f"Bearer {patient_token}"}
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "reading_id" in data
        assert data["status"] == "ingested"

    async def test_ingest_requires_auth(self, client, patient_id):
        payload = {"patient_id": patient_id, **NORMAL_VITALS}
        resp = await client.post("/api/v1/vitals/ingest", json=payload)
        assert resp.status_code == 403

    async def test_ingest_invalid_heart_rate_rejected(self, client, patient_token, patient_id):
        payload = {"patient_id": patient_id, **NORMAL_VITALS, "heart_rate": 300.0}
        resp = await client.post(
            "/api/v1/vitals/ingest",
            json=payload,
            headers={"Authorization": f"Bearer {patient_token}"}
        )
        assert resp.status_code == 422

    async def test_ingest_invalid_spo2_rejected(self, client, patient_token, patient_id):
        payload = {"patient_id": patient_id, **NORMAL_VITALS, "spo2": 50.0}
        resp = await client.post(
            "/api/v1/vitals/ingest",
            json=payload,
            headers={"Authorization": f"Bearer {patient_token}"}
        )
        assert resp.status_code == 422

    async def test_ingest_invalid_temperature_rejected(self, client, patient_token, patient_id):
        payload = {"patient_id": patient_id, **NORMAL_VITALS, "temperature": 50.0}
        resp = await client.post(
            "/api/v1/vitals/ingest",
            json=payload,
            headers={"Authorization": f"Bearer {patient_token}"}
        )
        assert resp.status_code == 422

    async def test_ingest_invalid_patient_id_rejected(self, client, patient_token):
        payload = {"patient_id": "not-a-uuid", **NORMAL_VITALS}
        resp = await client.post(
            "/api/v1/vitals/ingest",
            json=payload,
            headers={"Authorization": f"Bearer {patient_token}"}
        )
        assert resp.status_code == 400


# ── Vitals Retrieval ──────────────────────────────────────────────────────────

class TestVitalsRetrieval:
    async def test_patient_can_read_own_vitals(self, client, patient_token, patient_id):
        # Ingest first
        await client.post(
            "/api/v1/vitals/ingest",
            json={"patient_id": patient_id, **NORMAL_VITALS},
            headers={"Authorization": f"Bearer {patient_token}"}
        )
        resp = await client.get(
            f"/api/v1/vitals/patient/{patient_id}",
            headers={"Authorization": f"Bearer {patient_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["heart_rate"] == pytest.approx(75.0, rel=0.01)

    async def test_vitals_are_decrypted_correctly(self, client, patient_token, patient_id):
        await client.post(
            "/api/v1/vitals/ingest",
            json={"patient_id": patient_id, **NORMAL_VITALS},
            headers={"Authorization": f"Bearer {patient_token}"}
        )
        resp = await client.get(
            f"/api/v1/vitals/patient/{patient_id}",
            headers={"Authorization": f"Bearer {patient_token}"}
        )
        reading = resp.json()[0]
        assert reading["spo2"] == pytest.approx(98.0, rel=0.01)
        assert reading["temperature"] == pytest.approx(36.8, rel=0.01)
        assert reading["blood_pressure_sys"] == pytest.approx(120.0, rel=0.01)

    async def test_patient_cannot_read_another_patients_vitals(
        self, client, patient_token, patient_id
    ):
        # Create second patient
        await client.post("/api/v1/auth/register", json={
            "email": "other@test.com",
            "password": "testpass123",
            "full_name": "Other Patient",
            "phone": "9876543210",
            "role": "patient",
        })
        other_login = await client.post("/api/v1/auth/login", json={
            "email": "other@test.com",
            "password": "testpass123",
        })
        other_token = other_login.json()["access_token"]
        other_me = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {other_token}"}
        )
        other_id = other_me.json()["id"]

        # Patient 1 tries to read Patient 2's vitals
        resp = await client.get(
            f"/api/v1/vitals/patient/{other_id}",
            headers={"Authorization": f"Bearer {patient_token}"}
        )
        assert resp.status_code == 403

    async def test_vitals_limit_parameter(self, client, patient_token, patient_id):
        # Ingest 5 readings
        for _ in range(5):
            await client.post(
                "/api/v1/vitals/ingest",
                json={"patient_id": patient_id, **NORMAL_VITALS},
                headers={"Authorization": f"Bearer {patient_token}"}
            )
        resp = await client.get(
            f"/api/v1/vitals/patient/{patient_id}?limit=3",
            headers={"Authorization": f"Bearer {patient_token}"}
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 3

    async def test_empty_vitals_returns_empty_list(self, client, patient_token, patient_id):
        resp = await client.get(
            f"/api/v1/vitals/patient/{patient_id}",
            headers={"Authorization": f"Bearer {patient_token}"}
        )
        assert resp.status_code == 200
        assert resp.json() == []


# ── Simulator ─────────────────────────────────────────────────────────────────

class TestSimulator:
    async def test_simulator_status_initially_stopped(self, client, patient_token):
        resp = await client.get(
            "/api/v1/vitals/simulator/status",
            headers={"Authorization": f"Bearer {patient_token}"}
        )
        assert resp.status_code == 200
        assert resp.json()["running"] is False

    async def test_simulator_start_and_stop(self, client, patient_token):
        # Start
        start_resp = await client.post(
            "/api/v1/vitals/simulator/start",
            headers={"Authorization": f"Bearer {patient_token}"}
        )
        assert start_resp.status_code == 200
        assert start_resp.json()["status"] in ("started", "already_running")

        # Stop
        stop_resp = await client.post(
            "/api/v1/vitals/simulator/stop",
            headers={"Authorization": f"Bearer {patient_token}"}
        )
        assert stop_resp.status_code == 200
        assert stop_resp.json()["status"] == "stopped"

    async def test_double_start_returns_already_running(self, client, patient_token):
        await client.post(
            "/api/v1/vitals/simulator/start",
            headers={"Authorization": f"Bearer {patient_token}"}
        )
        resp = await client.post(
            "/api/v1/vitals/simulator/start",
            headers={"Authorization": f"Bearer {patient_token}"}
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "already_running"

        # Cleanup
        await client.post(
            "/api/v1/vitals/simulator/stop",
            headers={"Authorization": f"Bearer {patient_token}"}
        )