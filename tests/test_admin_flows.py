import types
import pytest
from unittest.mock import AsyncMock, patch

from app.bot.handlers import (
    ADMIN_ADD_ORG_NAME,
    ADMIN_ADD_ORG_TYPE,
    ADMIN_ADD_ORG_EMAIL,
    ADMIN_IMPORT_GOOGLE_CITY,
    ADMIN_IMPORT_LOCATION_INPUT,
    handle_admin_import_google_input,
    handle_admin_import_location_inputs,
    handle_admin_import_google,
    handle_admin_import_location,
    handle_admin_add_org,
    handle_admin_add_org_name_input,
    handle_admin_add_org_type,
    handle_admin_add_org_email_input,
)
from telegram.ext import ConversationHandler


class MsgStub:
    def __init__(self, text=None, location=None):
        self.text = text
        self.location = location
        self.calls = []
        self.chat = types.SimpleNamespace(id=1)

    async def reply_text(self, *a, **k):
        self.calls.append((a, k))


class CqStub:
    def __init__(self, data=""):
        self.data = data
        self.message = types.SimpleNamespace(message_id=1)
        self.answered = False
        self.edited = []

    async def answer(self):
        self.answered = True

    async def edit_message_text(self, *a, **k):
        self.edited.append((a, k))


def make_context():
    return types.SimpleNamespace(user_data={})


@pytest.mark.asyncio
async def test_import_google_city_failure_ends_conversation():
    ctx = make_context()
    ctx.user_data["awaiting_google_city"] = True
    update = types.SimpleNamespace(message=MsgStub(text="רעננה"), effective_user=None, effective_chat=None)

    class _DummyGoogle:
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False
        async def search_veterinary_clinics(self, city: str):
            raise RuntimeError("API down")
        async def search_animal_shelters(self, city: str):
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

    with patch("app.services.google.GoogleService", return_value=_DummyGoogle()):
        with patch("app.bot.handlers.async_session_maker", return_value=_FakeSession()):
            res = await handle_admin_import_google_input(update, ctx)
            assert res == ConversationHandler.END
            assert "awaiting_google_city" not in ctx.user_data
            assert update.message.calls  # replied with error


@pytest.mark.asyncio
async def test_import_location_failure_ends_conversation():
    ctx = make_context()
    ctx.user_data["awaiting_import_location"] = True
    ctx.user_data["import_radius_m"] = 5000

    class _Loc:  # simple location stub
        latitude = 32.184
        longitude = 34.871

    update = types.SimpleNamespace(message=MsgStub(location=_Loc()), effective_user=None, effective_chat=None)

    class _DummyGoogle:
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False
        async def search_veterinary_nearby(self, loc, radius: int):
            raise RuntimeError("network")
        async def search_shelters_nearby(self, loc, radius: int):
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

    with patch("app.services.google.GoogleService", return_value=_DummyGoogle()):
        with patch("app.bot.handlers.async_session_maker", return_value=_FakeSession()):
            res = await handle_admin_import_location_inputs(update, ctx)
            assert res == ConversationHandler.END
            assert "awaiting_import_location" not in ctx.user_data
            assert "import_radius_m" not in ctx.user_data
            assert update.message.calls  # replied with error


@pytest.mark.asyncio
async def test_add_org_happy_path():
    ctx = make_context()
    # Start via callback
    cq = CqStub(data="admin_add_org")
    update_cq = types.SimpleNamespace(callback_query=cq, effective_user=None, effective_chat=None)
    state = await handle_admin_add_org(update_cq, ctx)
    assert state == ADMIN_ADD_ORG_NAME
    assert ctx.user_data["add_org"]["step"] == "name"

    # Provide name
    msg = MsgStub(text="צער בעלי חיים תל אביב")
    update_msg = types.SimpleNamespace(message=msg, effective_user=None, effective_chat=None)
    state = await handle_admin_add_org_name_input(update_msg, ctx)
    assert state == ADMIN_ADD_ORG_TYPE
    assert ctx.user_data["add_org"]["step"] == "type"
    assert ctx.user_data["add_org"]["name"]

    # Choose type
    cq2 = CqStub(data="admin_add_org_type_animal_shelter")
    update_cq2 = types.SimpleNamespace(callback_query=cq2, effective_user=None, effective_chat=None)
    state = await handle_admin_add_org_type(update_cq2, ctx)
    assert state == ADMIN_ADD_ORG_EMAIL
    assert ctx.user_data["add_org"]["step"] == "email"

    # Send email and commit
    class _FakeSession:
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False
        def add(self, *a, **k):
            return None
        async def commit(self):
            return None

    with patch("app.bot.handlers.async_session_maker", return_value=_FakeSession()):
        msg2 = MsgStub(text="amir@example.com")
        update_msg2 = types.SimpleNamespace(message=msg2, effective_user=None, effective_chat=None)
        end = await handle_admin_add_org_email_input(update_msg2, ctx)
        assert end == ConversationHandler.END
        assert "add_org" not in ctx.user_data


@pytest.mark.asyncio
async def test_import_google_city_success_flow():
    ctx = make_context()
    # Start via callback
    cq = CqStub(data="admin_import_google")
    update_cq = types.SimpleNamespace(callback_query=cq, effective_user=None, effective_chat=None)
    # Move to awaiting city state
    state = await handle_admin_import_google(update_cq, ctx)
    assert state == ADMIN_IMPORT_GOOGLE_CITY
    assert ctx.user_data.get("awaiting_google_city") is True

    # Prepare success google mock
    class _DummyGoogle:
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False
        async def search_veterinary_clinics(self, city: str):
            return [{"name": "Vet A", "place_id": "p1"}]
        async def search_animal_shelters(self, city: str):
            return [{"name": "Shelter B", "place_id": "p2"}]

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

    with patch("app.services.google.GoogleService", return_value=_DummyGoogle()):
        with patch("app.bot.handlers.async_session_maker", return_value=_FakeSession()):
            msg = MsgStub(text="רעננה")
            update_msg = types.SimpleNamespace(message=msg, effective_user=None, effective_chat=None)
            end = await handle_admin_import_google_input(update_msg, ctx)
            assert end == ConversationHandler.END
            assert "awaiting_google_city" not in ctx.user_data
            assert msg.calls  # some reply was sent