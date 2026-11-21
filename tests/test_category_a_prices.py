"""
Unit and integration tests for Category A Automatic Delivery Text Pricing.
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
3. Complete removal of inline Price buttons:
   - NO inline keyboard or '💰 Price' button attached.
   - NO 'Click below to set price:' message sent.
   - Price displayed as plain text message (e.g. '💰 Price: $20.50').
   - Automatic DB saving of matching price into order.price.
4. Unlisted packages receive no price messages or incorrect prices.
5. Duplicate prevention during album delivery or retry handling.
6. Category B routing and delivery behavior remains completely unchanged.
7. Non-button price update capability for authorized admins.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from config import (
    CATEGORY_A_NORMAL_CP_PRICES,
    CATEGORY_A_DOUBLE_CP_PRICES,
)
from email_parser import get_category_a_price
from delivery import deliver_order_by_id
from handlers import is_valid_price_string, price_input_text_handler, PRICE_INPUT_SESSION
from models import Order, Image


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
        Requirement: Normal CP and Double CP must be matched separately.
        Never calculate a Double CP price from its total CP alone.
        """
        self.assertIsNone(get_category_a_price("16000 CP"))
        self.assertIsNone(get_category_a_price("8000 CP"))
        self.assertIsNone(get_category_a_price("4000 CP"))
        self.assertIsNone(get_category_a_price("1600 CP"))
        self.assertIsNone(get_category_a_price("800 CP"))

        self.assertIsNone(get_category_a_price("Double CP: 80+80 (Total: 160 CP)"))
        self.assertIsNone(get_category_a_price("80+80"))

        self.assertIsNone(get_category_a_price("5000 CP"))
        self.assertIsNone(get_category_a_price("12000 CP"))

    def test_is_valid_price_string(self):
        """Tests price string validation for manual entry and edits."""
        self.assertTrue(is_valid_price_string("15"))
        self.assertTrue(is_valid_price_string("15.5"))
        self.assertTrue(is_valid_price_string("2500"))
        self.assertTrue(is_valid_price_string("2999.99"))

        self.assertTrue(is_valid_price_string("$80"))
        self.assertTrue(is_valid_price_string("$41"))
        self.assertTrue(is_valid_price_string("$20.50"))
        self.assertTrue(is_valid_price_string("$4.75"))
        self.assertTrue(is_valid_price_string("$1"))

        self.assertFalse(is_valid_price_string("abc"))
        self.assertFalse(is_valid_price_string("15rs"))
        self.assertFalse(is_valid_price_string("price 20"))
        self.assertFalse(is_valid_price_string("$15.5.5"))
        self.assertFalse(is_valid_price_string("$$20"))


class TestCategoryADeliveryTextPrice(unittest.IsolatedAsyncioTestCase):
    """Integration tests for delivery message plain text price and button removal."""

    def setUp(self):
        PRICE_INPUT_SESSION.clear()

    async def test_delivery_all_normal_cp_prices(self):
        """Verifies all Normal CP packages deliver plain text price, no buttons, and update DB."""
        normal_cases = [
            ("10800 CP", "$80"),
            ("5040 CP", "$41"),
            ("2400 CP", "$20.50"),
            ("880 CP", "$9"),
            ("420 CP", "$4.75"),
            ("80 CP", "$1"),
        ]

        for pkg, expected_price in normal_cases:
            with self.subTest(package=pkg, price=expected_price):
                img = Image(id=1, telegram_file_id="file_norm", file_type="photo")
                order = Order(
                    id=301,
                    email="norm@example.com",
                    package=pkg,
                    category="A",
                    client_chat_id=-100111222,
                    original_message_id=701,
                    status="Pending",
                    price=None,
                    price_msg_id=None,
                    images=[img]
                )

                sent_msg = MagicMock(message_id=888)
                bot = MagicMock()
                bot.send_media_group = AsyncMock(return_value=[MagicMock(message_id=887)])
                bot.send_message = AsyncMock(return_value=sent_msg)
                bot.set_message_reaction = AsyncMock(return_value=True)

                with patch("delivery.get_order_by_id", AsyncMock(return_value=order)), \
                     patch("delivery.mark_order_delivered", AsyncMock()), \
                     patch("delivery.update_order_price", AsyncMock()) as mock_update_price, \
                     patch("delivery.CLIENT_GROUPS_CACHE", {-100111222: "A"}), \
                     patch("delivery.BOT_SETTINGS", {"source_group_id": -100111222, "delivery_group_id": -100333444}):

                    res = await deliver_order_by_id(bot=bot, order_id=301)
                    self.assertTrue(res)

                    # 1. Plain text price message sent in Client Group
                    price_calls = [
                        c for c in bot.send_message.call_args_list
                        if c[1].get("chat_id") == -100111222
                    ]
                    self.assertEqual(len(price_calls), 1)
                    kwargs = price_calls[0][1]
                    self.assertEqual(kwargs["text"], f"💰 Price: {expected_price}")
                    self.assertEqual(kwargs["reply_to_message_id"], 701)

                    # 2. NO inline keyboard / buttons attached
                    self.assertNotIn("reply_markup", kwargs)

                    # 3. NO 'Click below to set price:' message sent
                    all_sent_texts = [c[1].get("text", "") for c in bot.send_message.call_args_list]
                    for t in all_sent_texts:
                        self.assertNotIn("Click below to set price:", t)

                    # 4. DB price updated with matching price and price_msg_id
                    mock_update_price.assert_called_once_with(301, expected_price, price_msg_id=888)

    async def test_delivery_all_double_cp_prices(self):
        """Verifies all Double CP packages deliver plain text price, no buttons, and update DB."""
        double_cases = [
            ("Double CP: 8000+8000 (Total: 16000 CP)", "$80"),
            ("Double CP: 4000+4000 (Total: 8000 CP)", "$41"),
            ("Double CP: 2000+2000 (Total: 4000 CP)", "$20.50"),
            ("Double CP: 800+800 (Total: 1600 CP)", "$9"),
            ("Double CP: 400+400 (Total: 800 CP)", "$4.75"),
        ]

        for pkg, expected_price in double_cases:
            with self.subTest(package=pkg, price=expected_price):
                img = Image(id=2, telegram_file_id="file_double", file_type="photo")
                order = Order(
                    id=302,
                    email="double@example.com",
                    package=pkg,
                    category="A",
                    client_chat_id=-100111222,
                    original_message_id=702,
                    status="Pending",
                    price=None,
                    price_msg_id=None,
                    images=[img]
                )

                sent_msg = MagicMock(message_id=899)
                bot = MagicMock()
                bot.send_media_group = AsyncMock(return_value=[MagicMock(message_id=887)])
                bot.send_message = AsyncMock(return_value=sent_msg)
                bot.set_message_reaction = AsyncMock(return_value=True)

                with patch("delivery.get_order_by_id", AsyncMock(return_value=order)), \
                     patch("delivery.mark_order_delivered", AsyncMock()), \
                     patch("delivery.update_order_price", AsyncMock()) as mock_update_price, \
                     patch("delivery.CLIENT_GROUPS_CACHE", {-100111222: "A"}), \
                     patch("delivery.BOT_SETTINGS", {"source_group_id": -100111222, "delivery_group_id": -100333444}):

                    res = await deliver_order_by_id(bot=bot, order_id=302)
                    self.assertTrue(res)

                    price_calls = [
                        c for c in bot.send_message.call_args_list
                        if c[1].get("chat_id") == -100111222
                    ]
                    self.assertEqual(len(price_calls), 1)
                    kwargs = price_calls[0][1]
                    self.assertEqual(kwargs["text"], f"💰 Price: {expected_price}")
                    self.assertNotIn("reply_markup", kwargs)
                    mock_update_price.assert_called_once_with(302, expected_price, price_msg_id=899)

    async def test_delivery_unlisted_package_no_price_message(self):
        """Unlisted packages (e.g. 5000 CP or Double CP 80+80) must NOT receive a price message or button."""
        unlisted = ["5000 CP", "Double CP: 80+80 (Total: 160 CP)", "Standard Package", "12000 CP"]

        for pkg in unlisted:
            with self.subTest(package=pkg):
                img = Image(id=3, telegram_file_id="file_unlist", file_type="photo")
                order = Order(
                    id=303,
                    email="unlist@example.com",
                    package=pkg,
                    category="A",
                    client_chat_id=-100111222,
                    original_message_id=703,
                    status="Pending",
                    price=None,
                    price_msg_id=None,
                    images=[img]
                )

                bot = MagicMock()
                bot.send_media_group = AsyncMock(return_value=[MagicMock(message_id=887)])
                bot.send_message = AsyncMock()
                bot.set_message_reaction = AsyncMock(return_value=True)

                with patch("delivery.get_order_by_id", AsyncMock(return_value=order)), \
                     patch("delivery.mark_order_delivered", AsyncMock()), \
                     patch("delivery.update_order_price", AsyncMock()) as mock_update_price, \
                     patch("delivery.CLIENT_GROUPS_CACHE", {-100111222: "A"}), \
                     patch("delivery.BOT_SETTINGS", {"source_group_id": -100111222, "delivery_group_id": -100333444}):

                    res = await deliver_order_by_id(bot=bot, order_id=303)
                    self.assertTrue(res)

                    # No message should have been sent to client_chat_id
                    client_calls = [
                        c for c in bot.send_message.call_args_list
                        if c[1].get("chat_id") == -100111222
                    ]
                    self.assertEqual(len(client_calls), 0)
                    mock_update_price.assert_not_called()

    async def test_prevent_duplicate_price_message_on_retry(self):
        """If price_msg_id is already set, delivery retry must NOT send a duplicate price message."""
        img = Image(id=4, telegram_file_id="file_dup", file_type="photo")
        order = Order(
            id=304,
            email="retry@example.com",
            package="10800 CP",
            category="A",
            client_chat_id=-100111222,
            original_message_id=704,
            status="Pending",
            price="$80",
            price_msg_id=777888,  # Price message was ALREADY sent
            images=[img]
        )

        bot = MagicMock()
        bot.send_media_group = AsyncMock(return_value=[MagicMock(message_id=887)])
        bot.send_message = AsyncMock()
        bot.set_message_reaction = AsyncMock(return_value=True)

        with patch("delivery.get_order_by_id", AsyncMock(return_value=order)), \
             patch("delivery.mark_order_delivered", AsyncMock()), \
             patch("delivery.update_order_price", AsyncMock()) as mock_update_price, \
             patch("delivery.CLIENT_GROUPS_CACHE", {-100111222: "A"}), \
             patch("delivery.BOT_SETTINGS", {"source_group_id": -100111222, "delivery_group_id": -100333444}):

            res = await deliver_order_by_id(bot=bot, order_id=304)
            self.assertTrue(res)

            client_calls = [
                c for c in bot.send_message.call_args_list
                if c[1].get("chat_id") == -100111222
            ]
            self.assertEqual(len(client_calls), 0)
            mock_update_price.assert_not_called()

    async def test_category_b_delivery_unaffected(self):
        """Category B delivery must NEVER send a price message or price button."""
        img = Image(id=5, telegram_file_id="file_catb", file_type="photo")
        order = Order(
            id=305,
            email="catb@example.com",
            package="10800 CP",
            category="B",
            client_chat_id=-100111222,
            original_message_id=705,
            status="Pending",
            price=None,
            price_msg_id=None,
            images=[img]
        )

        bot = MagicMock()
        bot.send_media_group = AsyncMock(return_value=[MagicMock(message_id=887)])
        bot.send_message = AsyncMock()
        bot.set_message_reaction = AsyncMock(return_value=True)

        with patch("delivery.get_order_by_id", AsyncMock(return_value=order)), \
             patch("delivery.mark_order_delivered", AsyncMock()), \
             patch("delivery.update_order_price", AsyncMock()) as mock_update_price, \
             patch("delivery.CLIENT_GROUPS_CACHE", {-100111222: "B"}), \
             patch("delivery.BOT_SETTINGS", {"source_group_id": -100111222, "delivery_group_id": -100333444}):

            res = await deliver_order_by_id(bot=bot, order_id=305)
            self.assertTrue(res)

            client_calls = [
                c for c in bot.send_message.call_args_list
                if c[1].get("chat_id") == -100111222
            ]
            self.assertEqual(len(client_calls), 0)
            mock_update_price.assert_not_called()

    async def test_admin_non_button_price_update(self):
        """Authorized admin replying to the price message updates price without buttons."""
        order = Order(
            id=306,
            email="cust306@example.com",
            package="2400 CP",
            category="A",
            client_chat_id=-100111222,
            original_message_id=706,
            price="$20.50",
            price_msg_id=555444  # Bot's delivered price message ID
        )

        reply_to_msg = MagicMock(message_id=555444)
        message = MagicMock(
            text="$25",
            reply_to_message=reply_to_msg
        )
        user = MagicMock(id=999888)
        chat = MagicMock(id=-100111222)
        update = MagicMock(effective_user=user, effective_message=message, effective_chat=chat)

        sent_updated_msg = MagicMock(message_id=555445)
        bot = MagicMock()
        bot.send_message = AsyncMock(return_value=sent_updated_msg)
        context = MagicMock(bot=bot)

        mock_db_res = MagicMock()
        mock_db_res.scalar_one_or_none.return_value = order

        mock_db_session = AsyncMock()
        mock_db_session.execute.return_value = mock_db_res

        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("handlers.is_admin", return_value=True), \
             patch("handlers.AsyncSessionLocal", return_value=mock_session_ctx), \
             patch("handlers.get_order_by_id", AsyncMock(return_value=order)), \
             patch("handlers.update_order_price", AsyncMock()) as mock_update_price:

            await price_input_text_handler(update, context)

            bot.send_message.assert_called_once_with(
                chat_id=-100111222,
                text="💰 Price Updated: $25",
                reply_to_message_id=706
            )
            mock_update_price.assert_called_once_with(306, "$25", price_msg_id=555445)


if __name__ == "__main__":
    unittest.main()
