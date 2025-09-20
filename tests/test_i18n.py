import types
import pytest
from unittest.mock import AsyncMock, patch

from app.bot.handlers import show_language_menu, handle_language_selection


class MsgStub:
    def __init__(self):
        self.calls = []
    async def reply_text(self, *a, **k):
        self.calls.append((a, k))


class CqStub:
    def __init__(self, data):
        self.data = data
        self.edited = []
        self.answered = False
        self.message = MsgStub()
    async def answer(self):
        self.answered = True
    async def edit_message_text(self, *a, **k):
        self.edited.append((a, k))


def make_ctx():
    return types.SimpleNamespace(user_data={})


@pytest.mark.asyncio
async def test_show_language_menu_sends_buttons():
    ctx = make_ctx()
    msg = MsgStub()
    update = types.SimpleNamespace(message=msg)
    await show_language_menu(update, ctx)
    assert msg.calls


@pytest.mark.asyncio
async def test_handle_language_selection_updates_context():
    ctx = make_ctx()
    cq = CqStub("set_lang_en")
    update = types.SimpleNamespace(
        callback_query=cq,
        effective_user=types.SimpleNamespace(
            id=12345,
            username="testuser",
            full_name="Test User",
            language_code="he",
            first_name="Test",
        ),
    )
    # Patch i18n setter if needed
    with patch("app.bot.handlers.set_user_language", new=AsyncMock()) as set_lang:
        await handle_language_selection(update, ctx)
        # The preference should be stored in context
        assert ctx.user_data.get("language") == "en"
