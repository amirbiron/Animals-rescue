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
    show_admin_orgs_menu,
)
from telegram.ext import ConversationHandler
from telegram import ReplyKeyboardRemove, ReplyKeyboardMarkup


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
        # Use MsgStub so handlers can call query.message.reply_text(...)
        self.message = MsgStub()
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
            # Two replies: progress then error
            assert len(update.message.calls) >= 2
            assert "מבצע ייבוא" in update.message.calls[0][0][0]
            assert "שגיאה בייבוא" in update.message.calls[-1][0][0]


@pytest.mark.asyncio
async def test_show_admin_orgs_menu_permission_denied():
    # Mock get_or_create_user to return non-admin
    from app.models.database import UserRole
    ctx = make_context()
    msg = MsgStub(text="🏢 ניהול ארגונים")
    update = types.SimpleNamespace(message=msg, effective_user=types.SimpleNamespace(id=10), effective_chat=None)

    class _User:
        role = UserRole.REPORTER

    with patch("app.bot.handlers.get_or_create_user", new=AsyncMock(return_value=_User())):
        await show_admin_orgs_menu(update, ctx)
        # Should reply with permission_denied message (some text)
        assert msg.calls
        assert "אין לך הרשאה לבצע פעולה זו" in msg.calls[-1][0][0]



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
            # replied with error and keyboard removed is not relevant here
            assert update.message.calls


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
async def test_import_google_empty_city_stays_in_state():
    ctx = make_context()
    ctx.user_data["awaiting_google_city"] = True
    update = types.SimpleNamespace(message=MsgStub(text="   "), effective_user=None, effective_chat=None)
    res = await handle_admin_import_google_input(update, ctx)
    assert res == ADMIN_IMPORT_GOOGLE_CITY
    assert update.message.calls  # invalid input reply
    assert "קלט לא תקין" in update.message.calls[-1][0][0]


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
    # Validate i18n text contains Hebrew invalid_email
    last_text = msg.calls[-1][0][0]
    assert "כתובת אימייל לא תקינה" in last_text


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

    # Unknown radius text should keep waiting
    msg_unknown = MsgStub(text="רדיוס 7 ק""מ")
    res_u = await handle_admin_import_location_inputs(types.SimpleNamespace(message=msg_unknown, effective_user=None, effective_chat=None), ctx)
    assert res_u == ADMIN_IMPORT_LOCATION_INPUT

    # Choose radius
    msg_r = MsgStub(text="רדיוס 10 ק""מ")
    res_r = await handle_admin_import_location_inputs(types.SimpleNamespace(message=msg_r, effective_user=None, effective_chat=None), ctx)
    assert res_r == ADMIN_IMPORT_LOCATION_INPUT
    assert ctx.user_data.get("import_radius_m") == 10000

    # Send location with mocked Google and simulate dedup (second place duplicates)
    class _DummyGoogle:
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False
        async def search_veterinary_nearby(self, loc, radius: int):
            return [{"name": "Vet", "place_id": "dup"}]
        async def search_shelters_nearby(self, loc, radius: int):
            return [{"name": "Shelter", "place_id": "dup"}]

    class _FakeSession:
        def __init__(self):
            self.added = 0
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False
        async def execute(self, *a, **k):
            class _R:
                def scalar_one_or_none(self_inner):
                    # First call returns None (not exists), second returns a truthy object -> dedup
                    if getattr(self_inner, "_called", False):
                        return object()
                    self_inner._called = True
                    return None
            return _R()
        def add(self, *a, **k):
            self.added += 1
        async def commit(self):
            return None

    class _Loc:
        latitude = 32.18
        longitude = 34.87
    msg_loc = MsgStub(location=_Loc())
    with patch("app.services.google.GoogleService", return_value=_DummyGoogle()):
        session = _FakeSession()
        with patch("app.bot.handlers.async_session_maker", return_value=session):
            end = await handle_admin_import_location_inputs(types.SimpleNamespace(message=msg_loc, effective_user=None, effective_chat=None), ctx)
            assert end == ConversationHandler.END
            assert "awaiting_import_location" not in ctx.user_data
            assert "import_radius_m" not in ctx.user_data
            assert msg_loc.calls  # completion reply
            # Ensure keyboard is removed
            rm = msg_loc.calls[-1][1].get("reply_markup")
            assert isinstance(rm, ReplyKeyboardRemove)
            # Dedup ensured only one add
            assert session.added == 1


@pytest.mark.asyncio
async def test_import_google_city_dedup():
    ctx = make_context()
    # Start and move to awaiting city
    state = await handle_admin_import_google(types.SimpleNamespace(callback_query=CqStub(data="admin_import_google"), effective_user=None, effective_chat=None), ctx)
    assert state == ADMIN_IMPORT_GOOGLE_CITY

    class _DummyGoogle:
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False
        async def search_veterinary_clinics(self, city: str):
            return [{"name": "Vet", "place_id": "dup"}]
        async def search_animal_shelters(self, city: str):
            return [{"name": "Shelter", "place_id": "dup"}]

    class _FakeSession:
        def __init__(self):
            self.added = 0
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False
        async def execute(self, *a, **k):
            class _R:
                def scalar_one_or_none(self_inner):
                    if getattr(self_inner, "_called", False):
                        return object()
                    self_inner._called = True
                    return None
            return _R()
        def add(self, *a, **k):
            self.added += 1
        async def commit(self):
            return None

    with patch("app.services.google.GoogleService", return_value=_DummyGoogle()):
        session = _FakeSession()
        with patch("app.bot.handlers.async_session_maker", return_value=session):
            msg = MsgStub(text="רעננה")
            end = await handle_admin_import_google_input(types.SimpleNamespace(message=msg, effective_user=None, effective_chat=None), ctx)
            assert end == ConversationHandler.END
            assert msg.calls  # completion reply
            assert session.added == 1  # only first place added, duplicate skipped


@pytest.mark.asyncio
async def test_admin_add_org_type_sends_email_instructions_i18n():
    ctx = make_context()
    ctx.user_data["add_org"] = {"step": "type", "name": "Org Z"}
    cq = CqStub(data="admin_add_org_type_animal_shelter")
    update = types.SimpleNamespace(callback_query=cq, effective_user=None, effective_chat=None)
    res = await handle_admin_add_org_type(update, ctx)
    assert res == ADMIN_ADD_ORG_EMAIL
    # Message edited with email instructions
    assert cq.edited
    assert "הכנס כתובת אימייל" in cq.edited[-1][0][0]


@pytest.mark.asyncio
async def test_import_location_start_shows_keyboard():
    ctx = make_context()
    cq = CqStub(data="admin_import_location")
    update = types.SimpleNamespace(callback_query=cq, effective_user=None, effective_chat=None)
    res = await handle_admin_import_location(update, ctx)
    assert res == ADMIN_IMPORT_LOCATION_INPUT
    # The prompt and keyboard appear
    assert cq.message.calls
    km = cq.message.calls[-1][1].get("reply_markup")
    assert isinstance(km, ReplyKeyboardMarkup)


@pytest.mark.asyncio
async def test_import_google_start_prompts_city():
    ctx = make_context()
    cq = CqStub(data="admin_import_google")
    update = types.SimpleNamespace(callback_query=cq, effective_user=None, effective_chat=None)
    res = await handle_admin_import_google(update, ctx)
    assert res == ADMIN_IMPORT_GOOGLE_CITY
    assert cq.edited
    assert "הכנס שם עיר" in cq.edited[-1][0][0]


@pytest.mark.asyncio
async def test_add_org_empty_name_stays_in_state():
    ctx = make_context()
    ctx.user_data["add_org"] = {"step": "name"}
    msg = MsgStub(text="   ")
    res = await handle_admin_add_org_name_input(types.SimpleNamespace(message=msg, effective_user=None, effective_chat=None), ctx)
    assert res == ADMIN_ADD_ORG_NAME
    assert msg.calls  # invalid input reply


@pytest.mark.asyncio
async def test_add_org_email_creates_object_with_fields():
    ctx = make_context()
    ctx.user_data["add_org"] = {"step": "email", "name": "Org Y", "org_type": "animal_shelter"}

    class _FakeSession:
        def __init__(self):
            self.added = []
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False
        def add(self, obj):
            self.added.append(obj)
        async def commit(self):
            return None

    session = _FakeSession()
    with patch("app.bot.handlers.async_session_maker", return_value=session):
        msg = MsgStub(text="orgy@example.com")
        end = await handle_admin_add_org_email_input(types.SimpleNamespace(message=msg, effective_user=None, effective_chat=None), ctx)
        assert end == ConversationHandler.END
        assert session.added and session.added[0].name == "Org Y"
        assert session.added[0].email == "orgy@example.com"


@pytest.mark.asyncio
async def test_import_location_default_radius_used():
    ctx = make_context()
    # Start via callback and do not set radius
    _ = await handle_admin_import_location(types.SimpleNamespace(callback_query=CqStub(data="admin_import_location"), effective_user=None, effective_chat=None), ctx)

    class _DummyGoogle:
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False
        async def search_veterinary_nearby(self, loc, radius: int):
            assert radius == 10000
            return []
        async def search_shelters_nearby(self, loc, radius: int):
            assert radius == 10000
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

    class _Loc:
        latitude = 31.0
        longitude = 34.0
    msg_loc = MsgStub(location=_Loc())
    with patch("app.services.google.GoogleService", return_value=_DummyGoogle()):
        with patch("app.bot.handlers.async_session_maker", return_value=_FakeSession()):
            end = await handle_admin_import_location_inputs(types.SimpleNamespace(message=msg_loc, effective_user=None, effective_chat=None), ctx)
            assert end == ConversationHandler.END
            # Verify message mentions 10km
            last_text = msg_loc.calls[-1][0][0]
            assert "10" in last_text


@pytest.mark.asyncio
async def test_import_location_radius_20_selection():
    ctx = make_context()
    _ = await handle_admin_import_location(types.SimpleNamespace(callback_query=CqStub(data="admin_import_location"), effective_user=None, effective_chat=None), ctx)
    msg_r = MsgStub(text="רדיוס 20 ק""מ")
    res = await handle_admin_import_location_inputs(types.SimpleNamespace(message=msg_r, effective_user=None, effective_chat=None), ctx)
    assert res == ADMIN_IMPORT_LOCATION_INPUT
    assert ctx.user_data.get("import_radius_m") == 20000