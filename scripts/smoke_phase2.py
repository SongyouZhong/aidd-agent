"""Phase 2 end-to-end smoke test.

Exercises:
  - register / login / me / 401 on bad token
  - session CRUD + cross-user isolation (TC-1.1.1 / TC-1.1.2 / TC-1.1.3)
  - storage manager: append + load round-trip (Redis + SeaweedFS)

Run with the docker-compose middleware up:
    PYTHONPATH=. python scripts/smoke_phase2.py
"""

from __future__ import annotations

import asyncio
import secrets
import sys

import httpx

from app.core.config import settings
from app.main import app
from app.storage.manager import append_message, drop_session_cache, load_messages

API = settings.API_V1_PREFIX


def _ok(label: str) -> None:
    print(f"  [ok] {label}")


async def _http_flow(client: httpx.AsyncClient) -> None:
    suffix = secrets.token_hex(3)
    user_a = {"username": f"alice_{suffix}", "password": "pa55word!"}
    user_b = {"username": f"bob_{suffix}", "password": "pa55word!"}

    # --- register A & B ---
    r = await client.post(f"{API}/auth/register", json=user_a)
    assert r.status_code == 201, r.text
    token_a = r.json()["access_token"]
    _ok("register user A")

    r = await client.post(f"{API}/auth/register", json=user_b)
    assert r.status_code == 201, r.text
    token_b = r.json()["access_token"]
    _ok("register user B")

    # duplicate username → 409
    r = await client.post(f"{API}/auth/register", json=user_a)
    assert r.status_code == 409, r.text
    _ok("duplicate username rejected (409)")

    # bad password → 401
    r = await client.post(
        f"{API}/auth/login", json={"username": user_a["username"], "password": "wrong!!"}
    )
    assert r.status_code == 401, r.text
    _ok("wrong password rejected (401)")

    # /me with bad token → 401  (TC-1.1.3)
    r = await client.get(f"{API}/auth/me", headers={"Authorization": "Bearer bogus"})
    assert r.status_code == 401, r.text
    _ok("invalid JWT rejected (401)")

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # /me with good token
    r = await client.get(f"{API}/auth/me", headers=headers_a)
    assert r.status_code == 200 and r.json()["username"] == user_a["username"]
    _ok("/me returns current user")

    # --- A creates a session (TC-1.1.1) ---
    r = await client.post(
        f"{API}/sessions", json={"title": "靶点 EGFR 研究"}, headers=headers_a
    )
    assert r.status_code == 201, r.text
    a_session = r.json()
    _ok(f"A created session {a_session['id']}")

    # B should NOT see A's session (TC-1.1.2)
    r = await client.get(f"{API}/sessions", headers=headers_b)
    assert r.status_code == 200
    assert all(s["id"] != a_session["id"] for s in r.json())
    _ok("B cannot see A's session (cross-user isolation)")

    # B trying to mutate A's session → 403
    r = await client.patch(
        f"{API}/sessions/{a_session['id']}",
        json={"title": "hacked"},
        headers=headers_b,
    )
    assert r.status_code == 403, r.text
    _ok("B forbidden from modifying A's session (403)")

    # A renames own session
    r = await client.patch(
        f"{API}/sessions/{a_session['id']}",
        json={"title": "EGFR 抑制剂 v2"},
        headers=headers_a,
    )
    assert r.status_code == 200 and r.json()["title"] == "EGFR 抑制剂 v2"
    _ok("A renamed own session")

    # A deletes session
    r = await client.delete(f"{API}/sessions/{a_session['id']}", headers=headers_a)
    assert r.status_code == 204, r.text
    _ok("A deleted own session")


async def _storage_flow() -> None:
    session_id = "smoke-" + secrets.token_hex(4)
    await drop_session_cache(session_id)

    msgs = [
        {"role": "user", "content": "hello world"},
        {"role": "assistant", "content": "hi from agent"},
    ]
    for m in msgs:
        await append_message(session_id, m)
    _ok("appended 2 messages (Redis + SeaweedFS)")

    # fast path: Redis
    cached = await load_messages(session_id)
    assert cached == msgs, cached
    _ok("hot read from Redis matches")

    # cold path: drop cache, must rebuild from S3
    await drop_session_cache(session_id)
    cold = await load_messages(session_id)
    assert cold == msgs, cold
    _ok("cache miss → SeaweedFS rebuild matches (TC-1.2.2)")


async def main() -> int:
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            print("== HTTP flow ==")
            await _http_flow(client)
            print("== Storage flow ==")
            await _storage_flow()
    print("\nAll Phase 2 smoke checks passed ✅")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
