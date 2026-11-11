"""
Regression tests for Advanced Strict Order Detection (Universal Email + Normal/Double CP).
Uses fake test data only.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock

import handlers
from handlers import source_group_handler, duplicate_order_callback_handler
from email_parser import (
    extract_email,
    extract_double_cp_package,
    extract_valid_cp_package,
)
from database import (
    BOT_SETTINGS,
    CLIENT_GROUPS_CACHE,
    init_db,
    create_order,
    get_pending_orders,
    get_pending_order_by_email,
    delete_orders_by_email,
)

CLIENT_CHAT_ID = -100666000111222
LOADER_CHAT_ID = -100666000333444
PAYMENT_CHAT_ID = -100666000555666
CUSTOMER_UID = 8000000001
BOT_UID = 8000000002

TEST_EMAILS = [
    "user@company.pk",
    "user@proton.me",
    "user@custom-domain.co.uk",
    "user@yahoo.com",
    "strict.cust1@example.com",
    "strict.cust2@example.com",
    "player.5000@example.com",
    "bad_dup@invalid",
]


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


class TestUniversalEmailValidation(unittest.TestCase):
    """Tests universal email validation across providers, regional domains, and uncommon TLDs."""

    def test_universal_valid_domains(self):
        valid_cases = [
            "user@gmail.com",
            "user@outlook.com",
            "user@hotmail.com",
            "user@yahoo.com",
            "user@icloud.com",
            "user@proton.me",
            "user@company.com",
            "user@mybusiness.pk",
            "user@example.co.uk",
            "user@shop.com.pk",
            "user@charity.org.uk",
            "first.last+tag@brand.technology",
            "order@store.digital",
            "team@art.museum",
        ]
        for addr in valid_cases:
            self.assertEqual(extract_email(f"Email: {addr} 5000 CP"), addr, f"Should accept {addr}")

    def test_malformed_emails_rejected(self):
        bad_cases = [
            "user@",
            "@gmail.com",
            "user@gmail",
            "user@.com",
            "user@gmail..com",
            "user@gmail.c",
            "user..name@gmail.com",
            ".user@gmail.com",
            "user.@gmail.com",
            "user@-bad.com",
            "user@bad-.com",
            "a@@b.com",
            "user@gmail.com123",
        ]
        for bad in bad_cases:
            self.assertIsNone(extract_email(f"Email: {bad} / 5000 CP"), f"Should reject {bad}")


class TestNormalAndDoubleCPDetection(unittest.TestCase):
    """Tests normal CP package formats, Double CP event combos, and false-positive guards."""

    def test_normal_cp_formats(self):
        for raw, expected in [
            ("5000", "5000 CP"),
            ("5000 CP", "5000 CP"),
            ("5000cp", "5000 CP"),
            ("5k", "5000 CP"),
            ("5K CP", "5000 CP"),
            ("2400", "2400 CP"),
            ("2.4k", "2400 CP"),
            ("2,400 CP", "2400 CP"),
            ("12k", "12000 CP"),
        ]:
            self.assertEqual(extract_valid_cp_package(raw), expected, f"Failed for {raw}")

    def test_all_six_double_cp_combinations(self):
        expected_map = [
            ("80+80", "80+80", 160),
            ("400+400", "400+400", 800),
            ("800+800", "800+800", 1600),
            ("2000+2000", "2000+2000", 4000),
            ("4000+4000", "4000+4000", 8000),
            ("8000+8000", "8000+8000", 16000),
        ]
        for raw, combo, total in expected_map:
            res = extract_double_cp_package(raw)
            self.assertIsNotNone(res, f"Missing match for {raw}")
            self.assertEqual(res["combination"], combo)
            self.assertEqual(res["total_cp"], total)
            pkg_str = extract_valid_cp_package(raw)
            self.assertEqual(pkg_str, f"Double CP: {combo} (Total: {total} CP)")

    def test_double_cp_short_spaces_commas_and_k_formats(self):
        variants = [
            ("2+2", "2000+2000", 4000),
            ("4+4", "4000+4000", 8000),
            ("8+8", "8000+8000", 16000),
            ("2 + 2 CP", "2000+2000", 4000),
            ("4k+4k", "4000+4000", 8000),
            ("2k + 2k cp", "2000+2000", 4000),
            ("8k+8k", "8000+8000", 16000),
            ("8,000 + 8,000 CP", "8000+8000", 16000),
            ("80 + 80 cp", "80+80", 160),
        ]
        for raw, combo, total in variants:
            res = extract_double_cp_package(raw)
            self.assertIsNotNone(res, f"Failed for variant {raw}")
            self.assertEqual(res["combination"], combo)
            self.assertEqual(res["total_cp"], total)

    def test_unsupported_combinations_and_unrelated_numbers_rejected(self):
        for bad in [
            "3+3",
            "500+500",
            "80+400",
            "12000+12000",
            "12345 CP",
            "user@gmail.com\nYear: 2025",
            "user@gmail.com\nPrice: 5000",
            "user@gmail.com\nUID: 2400",
            "user@gmail.com\nPhone: 123-5000-880",
            "player.5000@example.com",
            "Price is 5000.00 PKR",
        ]:
            self.assertIsNone(extract_valid_cp_package(bad), f"Should reject {bad}")


class TestStrictOrderHandler(unittest.IsolatedAsyncioTestCase):
    """Integration tests verifying strict Email + Normal/Double CP validation in handlers."""

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
        for em in TEST_EMAILS:
            await delete_orders_by_email(em)

    async def asyncTearDown(self):
        for em in TEST_EMAILS:
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

    async def test_invalid_and_incomplete_messages_ignored(self):
        await self._assert_ignored(text="5000 CP", msg_id=6101)
        await self._assert_ignored(text="user@gmail.com", msg_id=6102)
        await self._assert_ignored(text="user@gmail 5000", msg_id=6103)
        await self._assert_ignored(text="user@gmail.com 3+3", msg_id=6104)
        await self._assert_ignored(text="Is 5000 CP available?", msg_id=6105)
        await self._assert_ignored(text="Berna SUY1995 8000+8000??", msg_id=6106)
        await self._assert_ignored(text="user@gmail.com\nPrice: 5000", msg_id=6107)

    async def test_valid_universal_domain_orders_accepted(self):
        cases = [
            ("user@company.pk 5000", "user@company.pk", "5000 CP", 6201),
            ("user@proton.me 5k", "user@proton.me", "5000 CP", 6202),
            ("user@yahoo.com 5000 CP", "user@yahoo.com", "5000 CP", 6203),
            ("user@custom-domain.co.uk 8+8", "user@custom-domain.co.uk", "Double CP: 8000+8000 (Total: 16000 CP)", 6204),
        ]
        for msg_text, exp_email, exp_pkg, mid in cases:
            update, _ = make_client_update(text=msg_text, message_id=mid)
            context = make_bot_context()
            await source_group_handler(update, context)

            order = await get_pending_order_by_email(exp_email)
            self.assertIsNotNone(order, f"Order not created for {msg_text}")
            self.assertEqual(order.package, exp_pkg)
            context.bot.set_message_reaction.assert_awaited_once()
            context.bot.copy_message.assert_awaited_once()

    async def test_photo_caption_and_bot_orders(self):
        update_cap, _ = make_client_update(caption="strict.cust1@example.com 4+4", message_id=6301)
        await source_group_handler(update_cap, make_bot_context())
        order_cap = await get_pending_order_by_email("strict.cust1@example.com")
        self.assertIsNotNone(order_cap)
        self.assertEqual(order_cap.package, "Double CP: 4000+4000 (Total: 8000 CP)")

        update_bot, _ = make_client_update(
            text="Fast Recharge 32\nEmail: strict.cust2@example.com\nPass: fake\n5000cp\nActivision",
            is_bot=True,
            message_id=6302,
        )
        await source_group_handler(update_bot, make_bot_context())
        order_bot = await get_pending_order_by_email("strict.cust2@example.com")
        self.assertIsNotNone(order_bot)
        self.assertEqual(order_bot.package, "5000 CP")

    async def test_duplicate_protection_and_callback_guard(self):
        context = make_bot_context()
        first, _ = make_client_update(text="strict.cust1@example.com 2,400 CP", message_id=6401)
        await source_group_handler(first, context)

        second, second_msg = make_client_update(text="strict.cust1@example.com 2.4k", message_id=6402)
        await source_group_handler(second, context)

        second_msg.reply_text.assert_awaited_once()
        self.assertEqual(context.bot.copy_message.await_count, 1)

        # Ensure dup_confirm callback rejects malformed stored duplicate record
        bad_dup = await create_order(
            email="bad_dup@invalid",
            client_chat_id=CLIENT_CHAT_ID,
            original_message_id=6403,
            package="Standard Package",
            status="Duplicate_Pending",
            category="A",
        )
        query = MagicMock()
        query.data = f"dup_confirm:{bad_dup.id}"
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        cb_update = MagicMock()
        cb_update.callback_query = query

        cb_ctx = make_bot_context()
        await duplicate_order_callback_handler(cb_update, cb_ctx)
        cb_ctx.bot.copy_message.assert_not_awaited()
        self.assertIsNone(await get_pending_order_by_email("bad_dup@invalid"))


if __name__ == "__main__":
    unittest.main()
