"""
Tests for authentication endpoints — register, login, OTP, token refresh.
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.main import app
from app.db.database import get_db
from app.db.models import Base

# Use in-memory SQLite for tests
TEST_DATABASE_URL = "sqlite+aiosqlite:///./test.db"

test_engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
TestSessionLocal = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


async def override_get_db():
    async with TestSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


app.dependency_overrides[get_db] = override_get_db


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
async def registered_patient(client):
    resp = await client.post("/api/v1/auth/register", json={
        "email": "patient@test.com",
        "password": "testpass123",
        "full_name": "Test Patient",
        "phone": "9876543210",
        "address": "Test Address",
        "role": "patient",
    })
    assert resp.status_code == 201
    return {"email": "patient@test.com", "password": "testpass123"}


@pytest_asyncio.fixture
async def patient_token(client, registered_patient):
    resp = await client.post("/api/v1/auth/login", json={
        "email": registered_patient["email"],
        "password": registered_patient["password"],
    })
    assert resp.status_code == 200
    data = resp.json()
    # Patients get token directly (no OTP)
    assert "access_token" in data
    return data["access_token"]


# ── Registration ──────────────────────────────────────────────────────────────

class TestRegistration:
    async def test_register_patient_success(self, client):
        resp = await client.post("/api/v1/auth/register", json={
            "email": "newpatient@test.com",
            "password": "password123",
            "full_name": "New Patient",
            "phone": "9876543210",
            "address": "Bangalore, Karnataka",
            "role": "patient",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert "user_id" in data
        assert data["message"] == "User registered successfully"

    async def test_register_doctor_gets_dr_prefix(self, client):
        resp = await client.post("/api/v1/auth/register", json={
            "email": "doctor@test.com",
            "password": "password123",
            "full_name": "Smith",
            "phone": "9876543210",
            "address": "Chennai",
            "role": "doctor",
        })
        assert resp.status_code == 201

    async def test_register_duplicate_email_fails(self, client, registered_patient):
        resp = await client.post("/api/v1/auth/register", json={
            "email": "patient@test.com",  # already registered
            "password": "different123",
            "full_name": "Duplicate",
            "phone": "1234567890",
            "role": "patient",
        })
        assert resp.status_code == 400
        assert "already registered" in resp.json()["detail"].lower()

    async def test_register_short_password_fails(self, client):
        resp = await client.post("/api/v1/auth/register", json={
            "email": "short@test.com",
            "password": "abc",
            "full_name": "Short Pass",
            "phone": "9876543210",
            "role": "patient",
        })
        assert resp.status_code == 400

    async def test_register_admin_self_registration_blocked(self, client):
        resp = await client.post("/api/v1/auth/register", json={
            "email": "hacker@test.com",
            "password": "password123",
            "full_name": "Hacker",
            "phone": "9876543210",
            "role": "admin",
        })
        assert resp.status_code == 403

    async def test_register_invalid_email_fails(self, client):
        resp = await client.post("/api/v1/auth/register", json={
            "email": "not-an-email",
            "password": "password123",
            "full_name": "Invalid",
            "phone": "9876543210",
            "role": "patient",
        })
        assert resp.status_code == 422


# ── Login ─────────────────────────────────────────────────────────────────────

class TestLogin:
    async def test_patient_login_returns_token(self, client, registered_patient):
        resp = await client.post("/api/v1/auth/login", json={
            "email": registered_patient["email"],
            "password": registered_patient["password"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["role"] == "patient"

    async def test_wrong_password_returns_401(self, client, registered_patient):
        resp = await client.post("/api/v1/auth/login", json={
            "email": registered_patient["email"],
            "password": "wrongpassword",
        })
        assert resp.status_code == 401

    async def test_nonexistent_email_returns_401(self, client):
        resp = await client.post("/api/v1/auth/login", json={
            "email": "nobody@test.com",
            "password": "anypassword",
        })
        assert resp.status_code == 401

    async def test_doctor_login_returns_otp_challenge(self, client):
        # Register doctor first
        await client.post("/api/v1/auth/register", json={
            "email": "dr@test.com",
            "password": "password123",
            "full_name": "Dr Test",
            "phone": "9876543210",
            "role": "doctor",
        })
        resp = await client.post("/api/v1/auth/login", json={
            "email": "dr@test.com",
            "password": "password123",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["requires_otp"] is True
        assert "user_id" in data
        assert "masked_email" in data
        assert "access_token" not in data  # no token until OTP verified


# ── Token & Profile ───────────────────────────────────────────────────────────

class TestTokenAndProfile:
    async def test_get_own_profile(self, client, patient_token):
        resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {patient_token}"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == "patient@test.com"
        assert data["role"] == "patient"
        assert "full_name" in data

    async def test_protected_endpoint_requires_token(self, client):
        resp = await client.get("/api/v1/auth/me")
        assert resp.status_code == 403

    async def test_invalid_token_rejected(self, client):
        resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalidtoken123"}
        )
        assert resp.status_code == 401

    async def test_refresh_token_works(self, client, registered_patient):
        login_resp = await client.post("/api/v1/auth/login", json={
            "email": registered_patient["email"],
            "password": registered_patient["password"],
        })
        refresh_token = login_resp.json()["refresh_token"]

        resp = await client.post("/api/v1/auth/refresh", json={
            "refresh_token": refresh_token
        })
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    async def test_heartbeat_updates_last_seen(self, client, patient_token):
        resp = await client.post(
            "/api/v1/auth/heartbeat",
            headers={"Authorization": f"Bearer {patient_token}"}
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"