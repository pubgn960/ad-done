"""
Regression tests for Strict Order Validation (Email + Supported CP Package required in same message).
Uses fake test data only.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock

import handlers
from handlers import source_group_handler
from email_parser import extract_email, extract_valid_cp_package
from database import (
    BOT_SETTINGS,
    CLIENT_GROUPS_CACHE,
    init_db,
    get_pending_orders,
    get_pending_order_by_email,
    delete_orders_by_email,
)

CLIENT_CHAT_ID = -100666000111222
LOADER_CHAT_ID = -100666000333444
PAYMENT_CHAT_ID = -100666000555666
CUSTOMER_UID = 8000000001
BOT_UID = 8000000002

VALID_EMAIL_1 = "strict.cust1@example.com"
VALID_EMAIL_2 = "strict.cust2@example.com"
EMBEDDED_NUM_EMAIL = "player.5000@example.com"


def make_client_update(
    *,
    text=None,
    caption=None,
    is_bot=False,
    message_id=5001,
    user_id=CUSTOMER_UID,
):
    user = MagicMock()
    user.id = user_id
    user.is_bot = is_bot
    user.username = "FakeOrderBot" if is_bot else "fake_user"

    chat = MagicMock()
    chat.id = CLIENT_CHAT_ID
    chat.title = "Strict Test Client Group"

    message = MagicMock()
    message.message_id = message_id
    message.text = text
    message.caption = caption
    message.reply_text = AsyncMock()

    update = MagicMock()
    update.effective_message = message
    update.effective_chat = chat
    update.effective_user = user
    return update, message


def make_bot_context():
    context = MagicMock()
    copied = MagicMock()
    copied.message_id = 777001
    context.bot.copy_message = AsyncMock(return_value=copied)
    context.bot.send_message = AsyncMock(return_value=copied)
    context.bot.set_message_reaction = AsyncMock(return_value=True)
    return context


class TestStrictParsers(unittest.TestCase):
    """Unit tests for email and CP package strict parsers."""

    def test_valid_emails_accepted(self):
        self.assertEqual(extract_email("Email: example@gmail.com / 5000 CP"), "example@gmail.com")
        self.assertEqual(extract_email("Login: test.user+1@outlook.com"), "test.user+1@outlook.com")
        self.assertEqual(extract_email("Send to john@hotmail.com."), "john@hotmail.com")

    def test_malformed_emails_rejected(self):
        for bad in [
            "Email: invalid@ / 5000 CP",
            "Email: @gmail.com / 5000 CP",
            "Email: user@domain / 5000 CP",
            "Email: user@.com / 5000 CP",
            "Email: user@..com / 5000 CP",
            "Email: user@-bad.com / 5000 CP",
            "Email: user@bad..com / 5000 CP",
            "Email: .@gmail.com / 5000 CP",
            "Email: user@gmail.c / 5000 CP",
            "Email: user@gmail.com123 / 5000 CP",
        ]:
            self.assertIsNone(extract_email(bad), f"Should reject malformed email in: {bad}")

    def test_cp_packages_catalog_and_formats(self):
        self.assertEqual(extract_valid_cp_package("5000 CP"), "5000 CP")
        self.assertEqual(extract_valid_cp_package("5000cp"), "5000 CP")
        self.assertEqual(extract_valid_cp_package("2,400 CP"), "2400 CP")
        self.assertEqual(extract_valid_cp_package("12k CP"), "12000 CP")
        self.assertEqual(extract_valid_cp_package("Email: example@gmail.com / 5000"), "5000 CP")

    def test_unsupported_or_embedded_numbers_rejected(self):
        self.assertIsNone(extract_valid_cp_package("Berna SUY1995 8000+8000??"))
        self.assertIsNone(extract_valid_cp_package("Email: example@gmail.com / 12345 CP"))
        self.assertIsNone(extract_valid_cp_package(EMBEDDED_NUM_EMAIL))
        self.assertIsNone(extract_valid_cp_package("Price is 5000.00 PKR"))


class TestStrictOrderHandler(unittest.IsolatedAsyncioTestCase):
    """Integration tests verifying strict Email + CP enforcement in source_group_handler."""

    async def asyncSetUp(self):
        await init_db()
        self._saved = {
            k: BOT_SETTINGS.get(k)
            for k in ("delivery_group_id", "payment_review_group_id", "is_active")
        }
        BOT_SETTINGS["delivery_group_id"] = LOADER_CHAT_ID
        BOT_SETTINGS["payment_review_group_id"] = PAYMENT_CHAT_ID
        BOT_SETTINGS["is_active"] = True
        CLIENT_GROUPS_CACHE[CLIENT_CHAT_ID] = "A"
        handlers.SEEN_MESSAGE_TEXT.clear()
        for em in (VALID_EMAIL_1, VALID_EMAIL_2, EMBEDDED_NUM_EMAIL):
            await delete_orders_by_email(em)

    async def asyncTearDown(self):
        for em in (VALID_EMAIL_1, VALID_EMAIL_2, EMBEDDED_NUM_EMAIL):
            await delete_orders_by_email(em)
        CLIENT_GROUPS_CACHE.pop(CLIENT_CHAT_ID, None)
        BOT_SETTINGS.update(self._saved)

    async def _assert_ignored(self, *, text=None, caption=None, is_bot=False, msg_id=5001):
        before = len(await get_pending_orders())
        update, message = make_client_update(
            text=text,
            caption=caption,
            is_bot=is_bot,
            message_id=msg_id,
            user_id=BOT_UID if is_bot else CUSTOMER_UID,
        )
        context = make_bot_context()

        await source_group_handler(update, context)

        after_orders = await get_pending_orders()
        self.assertEqual(len(after_orders), before, f"No DB order should be created for: {text or caption}")
        for o in after_orders:
            self.assertNotIn("@customer.com", o.email)
        context.bot.set_message_reaction.assert_not_awaited()
        context.bot.copy_message.assert_not_awaited()
        context.bot.send_message.assert_not_awaited()
        message.reply_text.assert_not_awaited()

    async def test_cp_only_messages_ignored(self):
        await self._assert_ignored(text="5000 CP", msg_id=5101)
        await self._assert_ignored(text="Berna SUY1995 8000+8000??", msg_id=5102)
        await self._assert_ignored(text="Is 5000 CP available?", msg_id=5103)

    async def test_email_only_messages_ignored(self):
        await self._assert_ignored(text=VALID_EMAIL_1, msg_id=5201)
        await self._assert_ignored(text=EMBEDDED_NUM_EMAIL, msg_id=5202)

    async def test_invalid_email_with_valid_cp_ignored(self):
        await self._assert_ignored(text="Email: invalid@ / 5000 CP", msg_id=5301)
        await self._assert_ignored(text="Email: user@..com / 2400cp", msg_id=5302)

    async def test_two_separate_messages_not_combined(self):
        await self._assert_ignored(text=VALID_EMAIL_1, msg_id=5401)
        await self._assert_ignored(text="5000 CP", msg_id=5402)
        self.assertIsNone(await get_pending_order_by_email(VALID_EMAIL_1))

    async def test_valid_email_and_cp_creates_one_order(self):
        update, message = make_client_update(
            text=f"Email: {VALID_EMAIL_1} / 2400cp",
            message_id=5501,
        )
        context = make_bot_context()

        await source_group_handler(update, context)

        order = await get_pending_order_by_email(VALID_EMAIL_1)
        self.assertIsNotNone(order)
        self.assertEqual(order.email, VALID_EMAIL_1)
        self.assertEqual(order.package, "2400 CP")
        context.bot.set_message_reaction.assert_awaited_once()
        context.bot.copy_message.assert_awaited_once()

    async def test_photo_caption_requires_both_fields(self):
        await self._assert_ignored(caption="5000 CP", msg_id=5601)
        await self._assert_ignored(caption=VALID_EMAIL_2, msg_id=5602)

        update, _ = make_client_update(
            caption=f"Email: {VALID_EMAIL_2} / 5000",
            message_id=5603,
        )
        context = make_bot_context()
        await source_group_handler(update, context)

        order = await get_pending_order_by_email(VALID_EMAIL_2)
        self.assertIsNotNone(order)
        self.assertEqual(order.package, "5000 CP")

    async def test_duplicate_protection_for_valid_orders(self):
        context = make_bot_context()
        first, _ = make_client_update(text=f"Email: {VALID_EMAIL_1} / 5000 CP", message_id=5701)
        await source_group_handler(first, context)

        second, second_msg = make_client_update(text=f"Email: {VALID_EMAIL_1} / 5000 CP", message_id=5702)
        await source_group_handler(second, context)

        second_msg.reply_text.assert_awaited_once()
        self.assertEqual(context.bot.copy_message.await_count, 1)

    async def test_bot_originated_validation_enforced(self):
        # Bot-originated incomplete message must be ignored
        await self._assert_ignored(text="Fast Recharge 32\n5000cp\nActivision", is_bot=True, msg_id=5801)

        # Bot-originated valid message must succeed
        update, _ = make_client_update(
            text=f"Fast Recharge 32\nEmail: {VALID_EMAIL_2}\nPass: fake\n5000cp\nActivision",
            is_bot=True,
            message_id=5802,
        )
        context = make_bot_context()
        await source_group_handler(update, context)

        order = await get_pending_order_by_email(VALID_EMAIL_2)
        self.assertIsNotNone(order)
        self.assertEqual(order.package, "5000 CP")


if __name__ == "__main__":
    unittest.main()
