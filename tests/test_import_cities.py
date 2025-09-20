import types
import pytest
from unittest.mock import AsyncMock, patch

from app.bot.handlers import (
    handle_admin_manage_import_cities,
    handle_admin_import_cities_add,
    handle_admin_import_cities_remove,
    handle_admin_import_cities_run,
    handle_admin_import_cities_inputs,
    IMPORT_CITIES_REDIS_KEY,
)


class MsgStub:
    def __init__(self, text=None):
        self.text = text
        self.calls = []
    async def reply_text(self, *a, **k):
        self.calls.append((a, k))


class CqStub:
    def __init__(self, data):
        self.data = data
        self.answered = False
        self.edited = []
        self.message = MsgStub()
    async def answer(self):
        self.answered = True
    async def edit_message_text(self, *a, **k):
        self.edited.append((a, k))


def make_ctx():
    return types.SimpleNamespace(user_data={})


@pytest.mark.asyncio
async def test_manage_import_cities_loads_list():
    ctx = make_ctx()
    cq = CqStub("admin_import_cities")
    update = types.SimpleNamespace(callback_query=cq)
    with patch("app.bot.handlers.redis_client.smembers", new=AsyncMock(return_value={"תל אביב", "רעננה"})):
        await handle_admin_manage_import_cities(update, ctx)
        # Should show list
        assert cq.edited
        assert "ערים מוגדרות" in cq.edited[-1][0][0]


@pytest.mark.asyncio
async def test_import_cities_add_flow_and_inputs():
    ctx = make_ctx()
    # Start add
    cq = CqStub("admin_import_cities_add")
    update_cq = types.SimpleNamespace(callback_query=cq)
    await handle_admin_import_cities_add(update_cq, ctx)
    assert ctx.user_data.get("awaiting_import_cities_add") is True

    # Provide input
    msg = MsgStub(text="רעננה, הרצליה\nכפר סבא")
    update_msg = types.SimpleNamespace(message=msg)
    with patch("app.bot.handlers.redis_client.sadd", new=AsyncMock(return_value=3)):
        with patch("app.bot.handlers.redis_client.smembers", new=AsyncMock(return_value={"רעננה", "הרצליה", "כפר סבא"})):
            await handle_admin_import_cities_inputs(update_msg, ctx)
            assert msg.calls
            assert ctx.user_data.get("awaiting_import_cities_add") is None


@pytest.mark.asyncio
async def test_import_cities_remove_flow_and_inputs():
    ctx = make_ctx()
    # Start remove
    cq = CqStub("admin_import_cities_remove")
    update_cq = types.SimpleNamespace(callback_query=cq)
    with patch("app.bot.handlers.redis_client.smembers", new=AsyncMock(return_value={"רעננה", "תל אביב"})):
        await handle_admin_import_cities_remove(update_cq, ctx)
    assert ctx.user_data.get("awaiting_import_cities_remove") is True

    # Provide input to remove
    msg = MsgStub(text="תל אביב\nחיפה")
    update_msg = types.SimpleNamespace(message=msg)
    async def fake_srem(key, member):
        return 1 if member in {"תל אביב"} else 0
    with patch("app.bot.handlers.redis_client.srem", new=AsyncMock(side_effect=fake_srem)):
        with patch("app.bot.handlers.redis_client.smembers", new=AsyncMock(return_value={"רעננה"})):
            await handle_admin_import_cities_inputs(update_msg, ctx)
            assert msg.calls
            assert ctx.user_data.get("awaiting_import_cities_remove") is None


@pytest.mark.asyncio
async def test_import_cities_run_summarizes():
    ctx = make_ctx()
    cq = CqStub("admin_import_cities_run")
    update_cq = types.SimpleNamespace(callback_query=cq)
    with patch("app.bot.handlers.redis_client.smembers", new=AsyncMock(return_value={"רעננה"})):
        # Mock Google service and DB
        class _DummyGoogle:
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc, tb):
                return False
            async def search_veterinary_clinics(self, city):
                return [{"name": "VetX", "place_id": "px"}]
            async def search_animal_shelters(self, city):
                return []
        class _FakeSession:
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc, tb):
                return False
            async def execute(self, *a, **k):
                class _R:
                    def scalar_one_or_none(self_inner):
                        return None
                return _R()
            def add(self, *a, **k):
                return None
            async def commit(self):
                return None
        with patch("app.bot.handlers.GoogleService", return_value=_DummyGoogle()):
            with patch("app.bot.handlers.async_session_maker", return_value=_FakeSession()):
                await handle_admin_import_cities_run(update_cq, ctx)
                # Should edit summary text with totals
                assert cq.edited
                assert "ייבוא הושלם" in cq.edited[-1][0][0]

