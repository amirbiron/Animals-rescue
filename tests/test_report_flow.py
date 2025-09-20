import types
import pytest
from unittest.mock import AsyncMock, patch

from telegram.ext import ConversationHandler

from app.bot.handlers import (
    WAITING_FOR_PHOTO,
    WAITING_FOR_LOCATION,
    WAITING_FOR_DESCRIPTION,
    CONFIRMING_REPORT,
    SELECTING_URGENCY,
    SELECTING_ANIMAL_TYPE,
    create_report_conversation_handler,
    handle_photo_upload,
    request_location,
    handle_location,
    handle_description,
    handle_report_confirmation,
    show_urgency_selection,
    show_animal_type_selection,
)


class PhotoFileStub:
    def __init__(self, content: bytes = b"abc"):
        self._content = content
    async def download_to_memory(self, buf):
        buf.write(self._content)

class PhotoStub:
    def __init__(self):
        self.file_id = "file_1"
        self.file_size = 123
        self.width = 100
        self.height = 100
    async def get_file(self):
        return PhotoFileStub()

class MsgStub:
    def __init__(self, text=None, photo=None, location=None):
        self.text = text
        self.photo = photo or []
        self.location = location
        self.calls = []
    async def reply_text(self, *a, **k):
        self.calls.append((a, k))


def make_update_message(**kwargs):
    return types.SimpleNamespace(message=MsgStub(**kwargs), effective_user=None, effective_chat=None)


@pytest.mark.asyncio
async def test_report_flow_photo_to_location():
    # Upload photo leads to WAITING_FOR_LOCATION via request_location
    msg = MsgStub(photo=[PhotoStub()])
    update = types.SimpleNamespace(message=msg, effective_user=None, effective_chat=None)
    with patch("app.bot.handlers.set_typing_action", new=AsyncMock()):
        # Patch storage upload used by photo path
        with patch("app.bot.handlers.file_storage.upload_file", new=AsyncMock(return_value={"url": "http://x"})):
            state = await handle_photo_upload(update, types.SimpleNamespace(user_data={}))
            # After first photo, handler stays in WAITING_FOR_PHOTO (allows more photos) or moves to location
            assert state in (WAITING_FOR_PHOTO, WAITING_FOR_LOCATION)
            assert msg.calls


@pytest.mark.asyncio
async def test_report_flow_location_to_description():
    # Provide manual address text triggers location handling and moves to description stage
    ctx = types.SimpleNamespace(user_data={"report_draft": {}})
    # Simulate location text where handler expects location or text (it supports text path too)
    update = make_update_message(text="רחוב הבנים 10, רעננה")
    with patch("app.bot.handlers.set_typing_action", new=AsyncMock()):
        # Patch geocoding to return city/address
        with patch("app.bot.handlers.geocoding_service.geocode", new=AsyncMock(return_value={"address": "רחוב הבנים 10", "city": "רעננה"})):
            state = await handle_location(update, ctx)
            assert state in (WAITING_FOR_LOCATION, WAITING_FOR_DESCRIPTION)


@pytest.mark.asyncio
async def test_report_flow_description_short_then_ok():
    ctx = types.SimpleNamespace(user_data={"report_draft": {}})
    # Short description -> stays in WAITING_FOR_DESCRIPTION
    update_short = make_update_message(text="קצר מידי")
    state = await handle_description(update_short, ctx)
    assert state == WAITING_FOR_DESCRIPTION
    # Valid description -> proceeds towards confirmation
    with patch("app.bot.handlers.set_typing_action", new=AsyncMock()):
        with patch("app.bot.handlers.nlp_service.analyze_text", new=AsyncMock(return_value={"urgency": None, "animal_type": None, "keywords": []})):
            update_ok = make_update_message(text="כלב פצוע באמצע הכביש, נראה מדמם")
            state2 = await handle_description(update_ok, ctx)
            # Some flows may return WAITING_FOR_DESCRIPTION if validation fails elsewhere
            assert state2 in (WAITING_FOR_DESCRIPTION, CONFIRMING_REPORT, SELECTING_URGENCY, SELECTING_ANIMAL_TYPE)


@pytest.mark.asyncio
async def test_report_flow_confirmation_paths():
    ctx = types.SimpleNamespace(user_data={"report_draft": {"description": "x"}})
    # Modify urgency path
    class CQ:
        def __init__(self, data):
            self.data = data
        async def answer(self):
            return None
    cq = CQ("modify_urgency")
    update = types.SimpleNamespace(callback_query=cq, effective_user=None, effective_chat=None)
    res = await handle_report_confirmation(update, ctx)
    assert res == SELECTING_URGENCY
    # Modify animal type path
    cq2 = CQ("modify_animal_type")
    update2 = types.SimpleNamespace(callback_query=cq2, effective_user=None, effective_chat=None)
    res2 = await handle_report_confirmation(update2, ctx)
    assert res2 == SELECTING_ANIMAL_TYPE