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


@pytest.mark.asyncio
async def test_import_google_input_guard_no_flag():
    # When not awaiting city, handler should not consume nor reply
    ctx = make_context()
    update = types.SimpleNamespace(message=MsgStub(text="ירושלים"), effective_user=None, effective_chat=None)
    res = await handle_admin_import_google_input(update, ctx)
    assert res == ADMIN_IMPORT_GOOGLE_CITY
    assert update.message.calls == []


@pytest.mark.asyncio
async def test_import_location_input_guard_no_flag():
    # Text radius with no awaiting flag
    ctx = make_context()
    update_txt = types.SimpleNamespace(message=MsgStub(text="רדיוס 5 ק""מ"), effective_user=None, effective_chat=None)
    res1 = await handle_admin_import_location_inputs(update_txt, ctx)
    assert res1 == ADMIN_IMPORT_LOCATION_INPUT
    assert update_txt.message.calls == []

    # Location with no awaiting flag
    class _Loc:
        latitude = 32.08
        longitude = 34.78
    update_loc = types.SimpleNamespace(message=MsgStub(location=_Loc()), effective_user=None, effective_chat=None)
    res2 = await handle_admin_import_location_inputs(update_loc, ctx)
    assert res2 == ADMIN_IMPORT_LOCATION_INPUT
    assert update_loc.message.calls == []


@pytest.mark.asyncio
async def test_add_org_handlers_guard_wrong_step():
    ctx = make_context()
    # name input while step is not set
    update_name = types.SimpleNamespace(message=MsgStub(text="שם כלשהו"), effective_user=None, effective_chat=None)
    res_name = await handle_admin_add_org_name_input(update_name, ctx)
    assert res_name == ADMIN_ADD_ORG_NAME
    assert update_name.message.calls == []

    # email input while step is not email
    ctx.user_data["add_org"] = {"step": "type", "name": "X"}
    update_email = types.SimpleNamespace(message=MsgStub(text="user@example.com"), effective_user=None, effective_chat=None)
    res_email = await handle_admin_add_org_email_input(update_email, ctx)
    assert res_email == ADMIN_ADD_ORG_EMAIL
    assert update_email.message.calls == []


@pytest.mark.asyncio
async def test_add_org_invalid_email_stays_in_state():
    ctx = make_context()
    # Move to email step first
    ctx.user_data["add_org"] = {"step": "email", "name": "Org X", "org_type": "animal_shelter"}
    msg = MsgStub(text="not-an-email")
    update = types.SimpleNamespace(message=msg, effective_user=None, effective_chat=None)
    res = await handle_admin_add_org_email_input(update, ctx)
    # Should stay in ADMIN_ADD_ORG_EMAIL and reply invalid
    assert res == ADMIN_ADD_ORG_EMAIL
    assert ctx.user_data["add_org"]["step"] == "email"
    assert msg.calls  # invalid email reply


@pytest.mark.asyncio
async def test_admin_add_org_type_without_name_shows_error():
    ctx = make_context()
    ctx.user_data["add_org"] = {"step": "type"}
    cq = CqStub(data="admin_add_org_type_animal_shelter")
    update = types.SimpleNamespace(callback_query=cq, effective_user=None, effective_chat=None)
    res = await handle_admin_add_org_type(update, ctx)
    # Handler responds with operation failed and stays in type state
    assert res == ADMIN_ADD_ORG_TYPE
    assert cq.edited  # some error message was sent


@pytest.mark.asyncio
async def test_import_location_success_flow():
    ctx = make_context()
    # Start via callback
    cq = CqStub(data="admin_import_location")
    update_cq = types.SimpleNamespace(callback_query=cq, effective_user=None, effective_chat=None)
    state = await handle_admin_import_location(update_cq, ctx)
    assert state == ADMIN_IMPORT_LOCATION_INPUT
    assert ctx.user_data.get("awaiting_import_location") is True

    # Choose radius
    msg_r = MsgStub(text="רדיוס 10 ק""מ")
    res_r = await handle_admin_import_location_inputs(types.SimpleNamespace(message=msg_r, effective_user=None, effective_chat=None), ctx)
    assert res_r == ADMIN_IMPORT_LOCATION_INPUT
    assert ctx.user_data.get("import_radius_m") == 10000

    # Send location with mocked Google
    class _DummyGoogle:
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False
        async def search_veterinary_nearby(self, loc, radius: int):
            return [{"name": "Vet", "place_id": "v1"}]
        async def search_shelters_nearby(self, loc, radius: int):
            return [{"name": "Shelter", "place_id": "s1"}]

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

    class _Loc:
        latitude = 32.18
        longitude = 34.87
    msg_loc = MsgStub(location=_Loc())
    with patch("app.services.google.GoogleService", return_value=_DummyGoogle()):
        with patch("app.bot.handlers.async_session_maker", return_value=_FakeSession()):
            end = await handle_admin_import_location_inputs(types.SimpleNamespace(message=msg_loc, effective_user=None, effective_chat=None), ctx)
            assert end == ConversationHandler.END
            assert "awaiting_import_location" not in ctx.user_data
            assert "import_radius_m" not in ctx.user_data
            assert msg_loc.calls  # completion reply