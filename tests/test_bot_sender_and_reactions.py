"""
Regression tests for:
- Orders posted by another bot (sender.is_bot=True) in a Client Group, run through the real source_group_handler.
- Reactions / non-content updates never triggering replies or orders.
All data is fake.
"""

import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import handlers
from handlers import source_group_handler, edited_message_handler
from email_parser import extract_email, extract_package, extract_login_method
from database import (
    BOT_SETTINGS,
    CLIENT_GROUPS_CACHE,
    init_db,
    get_pending_orders,
    get_pending_order_by_email,
    delete_orders_by_email,
)

CLIENT_CHAT_ID = -100555000111222
LOADER_CHAT_ID = -100555000333444
FAKE_BOT_USER_ID = 7000000001
FAKE_EMAIL = "fake.bot.order@example.com"
BOT_ORDER_TEXT = f"Fast Recharge 32\nEmail: {FAKE_EMAIL}\nPass: notreal\n5000cp\nActivision"


def make_update(text, *, is_bot=True, message_id=9001, edit_date=None, user_id=FAKE_BOT_USER_ID):
    user = MagicMock()
    user.id = user_id
    user.is_bot = is_bot
    user.username = "FakeRechargeBot" if is_bot else "fake_customer"

    chat = MagicMock()
    chat.id = CLIENT_CHAT_ID
    chat.title = "Test Client Group"

    message = MagicMock()
    message.message_id = message_id
    message.text = text
    message.caption = None
    message.edit_date = edit_date
    message.reply_text = AsyncMock()

    update = MagicMock()
    update.effective_message = message
    update.edited_message = message if edit_date is not None else None
    update.effective_chat = chat
    update.effective_user = user
    return update, message


def make_context():
    context = MagicMock()
    copied = MagicMock()
    copied.message_id = 424242
    context.bot.copy_message = AsyncMock(return_value=copied)
    context.bot.send_message = AsyncMock(return_value=copied)
    context.bot.set_message_reaction = AsyncMock(return_value=True)
    return context


class _ClientGroupFixture(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self._saved = {k: BOT_SETTINGS.get(k) for k in ("delivery_group_id", "is_active")}
        BOT_SETTINGS["delivery_group_id"] = LOADER_CHAT_ID
        BOT_SETTINGS["is_active"] = True
        CLIENT_GROUPS_CACHE[CLIENT_CHAT_ID] = "A"
        handlers.SEEN_MESSAGE_TEXT.clear()
        await delete_orders_by_email(FAKE_EMAIL)

    async def asyncTearDown(self):
        await delete_orders_by_email(FAKE_EMAIL)
        CLIENT_GROUPS_CACHE.pop(CLIENT_CHAT_ID, None)
        BOT_SETTINGS.update(self._saved)


class TestBotOriginatedOrderParsing(unittest.TestCase):
    def test_parser_extracts_fields_from_bot_format(self):
        self.assertEqual(extract_email(BOT_ORDER_TEXT), FAKE_EMAIL)
        self.assertEqual(extract_package(BOT_ORDER_TEXT), "5000 CP")
        self.assertEqual(extract_login_method(BOT_ORDER_TEXT), "Activision")

    def test_login_method_absent(self):
        self.assertIsNone(extract_login_method("Email: a@example.com 5000cp"))


class TestBotOriginatedOrderHandler(_ClientGroupFixture):
    async def test_bot_sender_order_is_created_and_forwarded(self):
        update, message = make_update(BOT_ORDER_TEXT, is_bot=True)
        context = make_context()

        await source_group_handler(update, context)

        order = await get_pending_order_by_email(FAKE_EMAIL)
        self.assertIsNotNone(order, "bot-originated order should be created")
        self.assertEqual(order.package, "5000 CP")
        self.assertEqual(order.category, "A")
        context.bot.copy_message.assert_awaited_once()
        self.assertEqual(context.bot.copy_message.await_args.kwargs["chat_id"], LOADER_CHAT_ID)

    async def test_bot_sender_duplicate_protection_still_applies(self):
        context = make_context()
        first, _ = make_update(BOT_ORDER_TEXT, message_id=9101)
        await source_group_handler(first, context)

        second, second_msg = make_update(BOT_ORDER_TEXT, message_id=9102)
        await source_group_handler(second, context)

        second_msg.reply_text.assert_awaited_once()  # Duplicate prompt
        self.assertEqual(context.bot.copy_message.await_count, 1)  # Not forwarded twice

    async def test_bot_calculation_summary_ignored(self):
        update, message = make_update("Previous Total: 100\nAdded: 2300\nNew Total: 2400")
        context = make_context()
        before = len(await get_pending_orders())

        await source_group_handler(update, context)

        self.assertEqual(len(await get_pending_orders()), before)
        context.bot.copy_message.assert_not_awaited()
        message.reply_text.assert_not_awaited()


class TestReactionsAreIgnored(_ClientGroupFixture):
    async def test_update_without_edit_date_does_nothing(self):
        # Reaction-style update: same message, no edit_date
        update, message = make_update(BOT_ORDER_TEXT, is_bot=False, user_id=7000000002)
        update.edited_message = message
        context = make_context()
        before = len(await get_pending_orders())

        await edited_message_handler(update, context)

        message.reply_text.assert_not_awaited()
        context.bot.copy_message.assert_not_awaited()
        context.bot.send_message.assert_not_awaited()
        context.bot.set_message_reaction.assert_not_awaited()
        self.assertEqual(len(await get_pending_orders()), before)

    async def test_update_with_unchanged_text_does_nothing(self):
        handlers.remember_message_text(CLIENT_CHAT_ID, 9201, BOT_ORDER_TEXT)
        update, message = make_update(BOT_ORDER_TEXT, is_bot=False, message_id=9201,
                                      edit_date=1700000000, user_id=7000000002)
        context = make_context()

        await edited_message_handler(update, context)

        message.reply_text.assert_not_awaited()

    async def test_genuine_text_edit_still_notifies(self):
        handlers.remember_message_text(CLIENT_CHAT_ID, 9301, BOT_ORDER_TEXT)
        update, message = make_update(BOT_ORDER_TEXT + "\nedited", is_bot=False, message_id=9301,
                                      edit_date=1700000000, user_id=7000000002)
        context = make_context()

        await edited_message_handler(update, context)

        message.reply_text.assert_awaited_once()

    def test_no_reaction_handler_registered(self):
        main_src = Path(__file__).resolve().parent.parent.joinpath("main.py").read_text(encoding="utf-8")
        self.assertNotIn("MessageReactionHandler", main_src)
        self.assertNotIn("message_reaction", main_src)


if __name__ == "__main__":
    unittest.main()
