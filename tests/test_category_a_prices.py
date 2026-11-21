"""
Unit and integration tests for Category A CP Price System.
Validates:
1. Normal CP Prices:
   - 10800 CP -> $80
   - 5040 CP -> $41
   - 2400 CP -> $20.50
   - 880 CP -> $9
   - 420 CP -> $4.75
   - 80 CP -> $1
2. Double CP Event Prices:
   - 8000+8000 (16000 CP) -> $80
   - 4000+4000 (8000 CP) -> $41
   - 2000+2000 (4000 CP) -> $20.50
   - 800+800 (1600 CP) -> $9
   - 400+400 (800 CP) -> $4.75
3. Strict separation of Normal and Double CP:
   - Double CP price is NEVER calculated from total CP alone.
   - Normal CP never matches Double CP prices.
   - Unsupported packages/combos return None and fall back to manual entry.
4. Delivery button workflow & callback handler:
   - Uses matching price on delivery button (e.g. '💰 Price: $80').
   - Clicking price button saves price to DB, posts calculator message, and switches button to '✏️ Edit Price'.
   - Fallback to manual entry when no matching price exists.
   - Category B workflow remains unchanged (no price button).
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from config import (
    CATEGORY_A_NORMAL_CP_PRICES,
    CATEGORY_A_DOUBLE_CP_PRICES,
    Config,
)
from email_parser import get_category_a_price, extract_double_cp_package, validate_order_fields
from handlers import is_valid_price_string, price_callback_handler, PRICE_INPUT_SESSION
from models import Order


class TestCategoryACPPrices(unittest.TestCase):
    """Unit tests for every Normal CP and Double CP price mapping."""

    def test_all_normal_cp_prices(self):
        """Tests every package in the Normal CP Price List."""
        expected = {
            "10800 CP": "$80",
            "5040 CP": "$41",
            "2400 CP": "$20.50",
            "880 CP": "$9",
            "420 CP": "$4.75",
            "80 CP": "$1",
        }
        for pkg, expected_price in expected.items():
            with self.subTest(package=pkg):
                self.assertEqual(get_category_a_price(pkg), expected_price)
                # Test with integer strings and order objects
                order = Order(id=1, email="user@gmail.com", package=pkg, category="A")
                self.assertEqual(get_category_a_price(order), expected_price)

    def test_normal_cp_variations(self):
        """Tests normal packages with lower/mixed case and whitespace."""
        self.assertEqual(get_category_a_price("10800cp"), "$80")
        self.assertEqual(get_category_a_price("5040"), "$41")
        self.assertEqual(get_category_a_price("2400 CP"), "$20.50")
        self.assertEqual(get_category_a_price("880 cp"), "$9")
        self.assertEqual(get_category_a_price("420"), "$4.75")
        self.assertEqual(get_category_a_price("80 CP"), "$1")

    def test_all_double_cp_prices(self):
        """Tests every package in the Double CP Event Price List."""
        expected = {
            "Double CP: 8000+8000 (Total: 16000 CP)": "$80",
            "Double CP: 4000+4000 (Total: 8000 CP)": "$41",
            "Double CP: 2000+2000 (Total: 4000 CP)": "$20.50",
            "Double CP: 800+800 (Total: 1600 CP)": "$9",
            "Double CP: 400+400 (Total: 800 CP)": "$4.75",
        }
        for pkg, expected_price in expected.items():
            with self.subTest(package=pkg):
                self.assertEqual(get_category_a_price(pkg), expected_price)
                order = Order(id=2, email="user@gmail.com", package=pkg, category="A")
                self.assertEqual(get_category_a_price(order), expected_price)

    def test_double_cp_shorthands_and_raw_combos(self):
        """Tests double CP combinations in raw and shorthand notations."""
        self.assertEqual(get_category_a_price("8000+8000"), "$80")
        self.assertEqual(get_category_a_price("8+8"), "$80")
        self.assertEqual(get_category_a_price("8k+8k"), "$80")
        self.assertEqual(get_category_a_price("4000+4000"), "$41")
        self.assertEqual(get_category_a_price("4+4"), "$41")
        self.assertEqual(get_category_a_price("4k+4k"), "$41")
        self.assertEqual(get_category_a_price("2000+2000"), "$20.50")
        self.assertEqual(get_category_a_price("2+2"), "$20.50")
        self.assertEqual(get_category_a_price("2k+2k"), "$20.50")
        self.assertEqual(get_category_a_price("800+800"), "$9")
        self.assertEqual(get_category_a_price("400+400"), "$4.75")

    def test_normal_and_double_cp_strict_separation(self):
        """
        Requirement 4: Normal CP and Double CP must be matched separately.
        Never calculate a Double CP price from its total CP alone.
        """
        # Normal CP packages having amounts equal to Double CP totals must NOT match Double CP prices
        self.assertIsNone(get_category_a_price("16000 CP"))
        self.assertIsNone(get_category_a_price("8000 CP"))
        self.assertIsNone(get_category_a_price("4000 CP"))
        self.assertIsNone(get_category_a_price("1600 CP"))
        self.assertIsNone(get_category_a_price("800 CP"))

        # Double CP 80+80 has total 160 CP; neither 80+80 nor 160 are in the Double CP price list.
        # It must NEVER be priced as $1 (the Normal 80 CP price) or anything else.
        self.assertIsNone(get_category_a_price("Double CP: 80+80 (Total: 160 CP)"))
        self.assertIsNone(get_category_a_price("80+80"))

        # Normal 5000 CP is a valid order package but has no Category A preset price -> None (manual fallback)
        self.assertIsNone(get_category_a_price("5000 CP"))
        self.assertIsNone(get_category_a_price("12000 CP"))

    def test_is_valid_price_string(self):
        """Tests price string validation for manual entry and edits."""
        # Standard numbers
        self.assertTrue(is_valid_price_string("15"))
        self.assertTrue(is_valid_price_string("15.5"))
        self.assertTrue(is_valid_price_string("2500"))
        self.assertTrue(is_valid_price_string("2999.99"))

        # Currency formatted numbers
        self.assertTrue(is_valid_price_string("$80"))
        self.assertTrue(is_valid_price_string("$41"))
        self.assertTrue(is_valid_price_string("$20.50"))
        self.assertTrue(is_valid_price_string("$4.75"))
        self.assertTrue(is_valid_price_string("$1"))

        # Invalid formats
        self.assertFalse(is_valid_price_string("abc"))
        self.assertFalse(is_valid_price_string("15rs"))
        self.assertFalse(is_valid_price_string("price 20"))
        self.assertFalse(is_valid_price_string("$15.5.5"))
        self.assertFalse(is_valid_price_string("$$20"))


class TestCategoryAPriceWorkflowHandlers(unittest.IsolatedAsyncioTestCase):
    """Tests Category A Price workflow callback button actions and DB updates."""

    def setUp(self):
        PRICE_INPUT_SESSION.clear()

    async def test_automatic_price_callback_for_normal_cp(self):
        """Clicking price_set on Normal 10800 CP automatically sets $80 and posts calculator message."""
        order = Order(
            id=101,
            email="cust101@example.com",
            package="10800 CP",
            category="A",
            client_chat_id=-100111222,
            original_message_id=501,
            price=None
        )

        query = MagicMock()
        query.data = f"price_set:{order.id}"
        query.message = MagicMock()
        query.message.message_id = 901
        query.message.edit_reply_markup = AsyncMock()
        query.answer = AsyncMock()

        user = MagicMock(id=123456789)
        update = MagicMock(callback_query=query, effective_user=user)

        sent_msg = MagicMock(message_id=999)
        bot = MagicMock()
        bot.send_message = AsyncMock(return_value=sent_msg)
        context = MagicMock(bot=bot)

        with patch("handlers.is_admin", return_value=True), \
             patch("handlers.get_order_by_id", AsyncMock(return_value=order)), \
             patch("handlers.update_order_price", AsyncMock()) as mock_update_price:

            await price_callback_handler(update, context)

            # 1. Message posted in client group
            bot.send_message.assert_called_once_with(
                chat_id=-100111222,
                text="💰 Price: $80",
                reply_to_message_id=501
            )

            # 2. Price saved in database
            mock_update_price.assert_called_once_with(101, "$80", price_msg_id=999)

            # 3. Button switched to Edit Price
            query.message.edit_reply_markup.assert_called_once()
            call_markup = query.message.edit_reply_markup.call_args[1]["reply_markup"]
            self.assertEqual(call_markup.inline_keyboard[0][0].text, "✏️ Edit Price")
            self.assertEqual(call_markup.inline_keyboard[0][0].callback_data, "price_edit:101")

            # 4. Callback query answered
            query.answer.assert_called_once_with("✅ Price set to $80")

    async def test_automatic_price_callback_for_double_cp(self):
        """Clicking price_set on Double CP 4000+4000 automatically sets $41."""
        order = Order(
            id=102,
            email="cust102@example.com",
            package="Double CP: 4000+4000 (Total: 8000 CP)",
            category="A",
            client_chat_id=-100111222,
            original_message_id=502,
            price=None
        )

        query = MagicMock()
        query.data = f"price_set:{order.id}"
        query.message = MagicMock()
        query.message.message_id = 902
        query.message.edit_reply_markup = AsyncMock()
        query.answer = AsyncMock()

        user = MagicMock(id=123456789)
        update = MagicMock(callback_query=query, effective_user=user)

        sent_msg = MagicMock(message_id=998)
        bot = MagicMock()
        bot.send_message = AsyncMock(return_value=sent_msg)
        context = MagicMock(bot=bot)

        with patch("handlers.is_admin", return_value=True), \
             patch("handlers.get_order_by_id", AsyncMock(return_value=order)), \
             patch("handlers.update_order_price", AsyncMock()) as mock_update_price:

            await price_callback_handler(update, context)

            bot.send_message.assert_called_once_with(
                chat_id=-100111222,
                text="💰 Price: $41",
                reply_to_message_id=502
            )
            mock_update_price.assert_called_once_with(102, "$41", price_msg_id=998)
            query.answer.assert_called_once_with("✅ Price set to $41")

    async def test_fallback_to_manual_price_entry_when_unknown_package(self):
        """If package is not in the Category A price list, prompt for manual price."""
        order = Order(
            id=103,
            email="cust103@example.com",
            package="5000 CP",  # 5000 is not in preset price table
            category="A",
            client_chat_id=-100111222,
            original_message_id=503,
            price=None
        )

        query = MagicMock()
        query.data = f"price_set:{order.id}"
        query.message = MagicMock()
        query.message.message_id = 903
        query.answer = AsyncMock()

        user = MagicMock(id=123456789)
        update = MagicMock(callback_query=query, effective_user=user)

        prompt_msg = MagicMock(message_id=777)
        bot = MagicMock()
        bot.send_message = AsyncMock(return_value=prompt_msg)
        context = MagicMock(bot=bot)

        with patch("handlers.is_admin", return_value=True), \
             patch("handlers.get_order_by_id", AsyncMock(return_value=order)), \
             patch("handlers.set_order_price_prompt", AsyncMock()) as mock_set_prompt:

            await price_callback_handler(update, context)

            # Prompts admin for manual price input
            bot.send_message.assert_called_once_with(
                chat_id=-100111222,
                text="Enter order price:",
                reply_to_message_id=903
            )
            mock_set_prompt.assert_called_once_with(103, 777)
            self.assertIn(103, PRICE_INPUT_SESSION)

    async def test_delivery_button_creation_for_category_a_and_b(self):
        """Verifies delivery message inline buttons in Category A and Category B."""
        from delivery import deliver_order_by_id
        from models import Image

        # Mock order with 1 image
        img = Image(id=1, telegram_file_id="file_123", file_type="photo")
        order_cat_a = Order(
            id=201,
            email="cat_a@example.com",
            package="10800 CP",
            category="A",
            client_chat_id=-100111222,
            original_message_id=601,
            status="Pending",
            images=[img]
        )

        bot = MagicMock()
        bot.send_media_group = AsyncMock(return_value=[MagicMock(message_id=888)])
        bot.send_message = AsyncMock(return_value=MagicMock(message_id=889))
        bot.set_message_reaction = AsyncMock(return_value=True)

        with patch("delivery.get_order_by_id", AsyncMock(return_value=order_cat_a)), \
             patch("delivery.mark_order_delivered", AsyncMock()), \
             patch("delivery.CLIENT_GROUPS_CACHE", {-100111222: "A"}), \
             patch("delivery.BOT_SETTINGS", {"source_group_id": -100111222, "delivery_group_id": -100333444}):

            await deliver_order_by_id(bot=bot, order_id=201)

            # Check that send_message was called to attach the price button
            # Find the call with "💰 Click below to set price:"
            price_button_call = None
            for call in bot.send_message.call_args_list:
                if "💰 Click below to set price:" in call[1].get("text", ""):
                    price_button_call = call
                    break

            self.assertIsNotNone(price_button_call)
            markup = price_button_call[1]["reply_markup"]
            self.assertEqual(markup.inline_keyboard[0][0].text, "💰 Price: $80")
            self.assertEqual(markup.inline_keyboard[0][0].callback_data, "price_set:201")

        # Now test Category B order -> MUST NOT attach price button
        order_cat_b = Order(
            id=202,
            email="cat_b@example.com",
            package="10800 CP",
            category="B",
            client_chat_id=-100111222,
            original_message_id=602,
            status="Pending",
            images=[img]
        )
        bot_b = MagicMock()
        bot_b.send_media_group = AsyncMock(return_value=[MagicMock(message_id=890)])
        bot_b.send_message = AsyncMock(return_value=MagicMock(message_id=891))
        bot_b.set_message_reaction = AsyncMock(return_value=True)

        with patch("delivery.get_order_by_id", AsyncMock(return_value=order_cat_b)), \
             patch("delivery.mark_order_delivered", AsyncMock()), \
             patch("delivery.CLIENT_GROUPS_CACHE", {-100111222: "B"}), \
             patch("delivery.BOT_SETTINGS", {"source_group_id": -100111222, "delivery_group_id": -100333444}):

            await deliver_order_by_id(bot=bot_b, order_id=202)

            for call in bot_b.send_message.call_args_list:
                self.assertNotIn("💰 Click below to set price:", call[1].get("text", ""))


if __name__ == "__main__":
    unittest.main()
