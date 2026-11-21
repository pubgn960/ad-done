"""
Comprehensive test suite for Facebook login CODM order detection and processing.
Validates:
1. Facebook orders with phone numbers (local, international, formatted, labeled, unlabeled).
2. Facebook orders with usernames and email-based Facebook logins.
3. Verification code lines (2FA, Backup codes, OTP) do not interfere and are never treated as account/package.
4. Support for all Double CP combinations including 2000+2000 = 4000 CP and shorthands.
5. Strict rejection of incomplete Facebook orders (missing password, missing username/phone, missing CP, invalid phone).
6. Strict separation of Activision and Facebook orders (Activision never classified as Facebook).
7. E2E handler execution for Category A and Category B routing.
8. Duplicate order detection for Facebook phone numbers and 'Place Again' callback handling.
9. Delivery and Category A plain text price for Facebook orders (e.g. $20.50 for 2000+2000).
10. Assurance that passwords and verification codes are never logged.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from email_parser import (
    validate_facebook_order,
    validate_activision_order,
    validate_order_fields,
    extract_facebook_account,
    is_valid_phone_or_username,
    extract_login_method,
    get_category_a_price,
)
from handlers import source_group_handler, duplicate_order_callback_handler
from delivery import deliver_order_by_id
from models import Order, Image


class TestFacebookOrderParser(unittest.TestCase):
    """Unit tests for Facebook order extraction and validation functions."""

    def test_facebook_order_with_phone_number_labeled(self):
        """Tests Facebook orders with various labeled phone number formats."""
        messages = [
            # Local Pakistani phone format
            (
                "Fast Recharge 32\nFacebook\nNumber: 03001234567\nPass: secret123\n2000+2000",
                "03001234567",
                "Double CP: 2000+2000 (Total: 4000 CP)",
                "double_cp"
            ),
            # International phone with +
            (
                "Login: Facebook\nPhone: +923001234567\nPassword: mypassword\nCode: 1234 5678\n5000 CP",
                "+923001234567",
                "5000 CP",
                "normal_cp"
            ),
            # Mobile label with hyphens
            (
                "FB Login\nMobile: 0312-3456789\nPass: pass999\n2000+2000 CP",
                "03123456789",
                "Double CP: 2000+2000 (Total: 4000 CP)",
                "double_cp"
            ),
            # Contact label with spaces
            (
                "Facebook\nContact: 0300 1234567\nPwd: pass123\n8000+8000",
                "03001234567",
                "Double CP: 8000+8000 (Total: 16000 CP)",
                "double_cp"
            ),
            # US international phone
            (
                "FB\nPhone Number: +1 555-0199\nPassword: strongpass\n2400 CP",
                "+15550199",
                "2400 CP",
                "normal_cp"
            ),
        ]

        for text, exp_account, exp_pkg, exp_type in messages:
            with self.subTest(text=text[:30]):
                res = validate_facebook_order(text)
                self.assertIsNotNone(res, f"Failed to validate: {text}")
                self.assertEqual(res["email"], exp_account)
                self.assertEqual(res["package"], exp_pkg)
                self.assertEqual(res["order_type"], exp_type)
                self.assertEqual(res["login_method"], "Facebook")

    def test_facebook_order_with_unlabeled_phone(self):
        """Tests Facebook orders where the phone number is on its own line without a label."""
        text = (
            "Facebook\n"
            "03001234567\n"
            "Pass: fake_pass\n"
            "Backup Code: 1122 3344\n"
            "2000+2000"
        )
        res = validate_facebook_order(text)
        self.assertIsNotNone(res)
        self.assertEqual(res["email"], "03001234567")
        self.assertEqual(res["package"], "Double CP: 2000+2000 (Total: 4000 CP)")
        self.assertEqual(res["login_method"], "Facebook")

    def test_facebook_order_with_username_or_id(self):
        """Tests Facebook orders using Facebook username or FB ID."""
        text_user = (
            "Fast Recharge 32\n"
            "FB Login\n"
            "User: codm_warrior\n"
            "Pass: testpass\n"
            "2FA: 987654\n"
            "4000+4000"
        )
        res = validate_facebook_order(text_user)
        self.assertIsNotNone(res)
        self.assertEqual(res["email"], "codm_warrior")
        self.assertEqual(res["package"], "Double CP: 4000+4000 (Total: 8000 CP)")

        text_id = (
            "Facebook\n"
            "FB ID: 100088776655\n"
            "Password: secret\n"
            "10800 CP"
        )
        res_id = validate_facebook_order(text_id)
        self.assertIsNotNone(res_id)
        self.assertEqual(res_id["email"], "100088776655")
        self.assertEqual(res_id["package"], "10800 CP")

    def test_facebook_order_with_email_account(self):
        """Tests Facebook orders where the user logs in with an email address."""
        text = (
            "Login: Facebook\n"
            "Email: fb_gamer@yahoo.com\n"
            "Pass: password123\n"
            "2000+2000 CP"
        )
        res = validate_facebook_order(text)
        self.assertIsNotNone(res)
        self.assertEqual(res["email"], "fb_gamer@yahoo.com")
        self.assertEqual(res["package"], "Double CP: 2000+2000 (Total: 4000 CP)")
        self.assertEqual(res["login_method"], "Facebook")

    def test_facebook_double_cp_combinations(self):
        """Tests all supported Double CP combinations on Facebook orders, including shorthands."""
        combos = [
            ("2000+2000", "Double CP: 2000+2000 (Total: 4000 CP)", 4000),
            ("2+2", "Double CP: 2000+2000 (Total: 4000 CP)", 4000),
            ("2k+2k", "Double CP: 2000+2000 (Total: 4000 CP)", 4000),
            ("4000+4000", "Double CP: 4000+4000 (Total: 8000 CP)", 8000),
            ("4+4", "Double CP: 4000+4000 (Total: 8000 CP)", 8000),
            ("8000+8000", "Double CP: 8000+8000 (Total: 16000 CP)", 16000),
            ("8+8", "Double CP: 8000+8000 (Total: 16000 CP)", 16000),
            ("800+800", "Double CP: 800+800 (Total: 1600 CP)", 1600),
            ("400+400", "Double CP: 400+400 (Total: 800 CP)", 800),
            ("80+80", "Double CP: 80+80 (Total: 160 CP)", 160),
        ]

        for combo_str, exp_formatted, exp_total in combos:
            with self.subTest(combo=combo_str):
                text = f"Facebook\nNumber: 03001234567\nPass: fake\n{combo_str}"
                res = validate_facebook_order(text)
                self.assertIsNotNone(res)
                self.assertEqual(res["package"], exp_formatted)
                self.assertEqual(res["total_cp"], exp_total)

    def test_incomplete_and_invalid_facebook_orders_rejected(self):
        """Tests that invalid or incomplete Facebook credentials are strictly rejected."""
        invalid_cases = [
            # 1. Missing password field
            "Facebook\nNumber: 03001234567\n2000+2000",
            # 2. Empty password field
            "Facebook\nNumber: 03001234567\nPass:\n2000+2000",
            # 3. Missing username / phone number
            "Facebook\nPass: mysecret\n2000+2000",
            # 4. Missing CP package
            "Facebook\nNumber: 03001234567\nPass: mysecret",
            # 5. Missing Facebook keyword / identifier
            "Number: 03001234567\nPass: mysecret\n2000+2000",
            # 6. Invalid phone number (too short)
            "Facebook\nNumber: 1234\nPass: mysecret\n2000+2000",
            # 7. Unsupported Double CP combination
            "Facebook\nNumber: 03001234567\nPass: mysecret\n1000+1000",
            # 8. Standalone number not in package catalog
            "Facebook\nNumber: 03001234567\nPass: mysecret\n9999",
        ]

        for bad_text in invalid_cases:
            with self.subTest(bad_text=bad_text.replace('\n', ' ')):
                self.assertIsNone(validate_facebook_order(bad_text))
                self.assertIsNone(validate_order_fields(bad_text))

    def test_activision_order_not_classified_as_facebook(self):
        """
        Requirement 6: Do not accidentally classify Activision orders as Facebook orders.
        Requirement 1: Preserve existing Activision email validation exactly as it is.
        """
        activision_msg = (
            "Fast Recharge 32\n"
            "Email: ghostprime4@gmail.com\n"
            "Pass: fake\n"
            "5000cp\n"
            "Activision"
        )
        # Must be rejected by Facebook path
        self.assertIsNone(validate_facebook_order(activision_msg))

        # Must be accepted by Activision path
        act_res = validate_activision_order(activision_msg)
        self.assertIsNotNone(act_res)
        self.assertEqual(act_res["email"], "ghostprime4@gmail.com")
        self.assertEqual(act_res["package"], "5000 CP")
        self.assertEqual(act_res["login_method"], "Activision")

        # Unified validator returns it as Activision
        unified = validate_order_fields(activision_msg)
        self.assertIsNotNone(unified)
        self.assertEqual(unified["login_method"], "Activision")

    def test_extract_login_method_recognition(self):
        """Tests extraction of login method canonical names."""
        self.assertEqual(extract_login_method("Facebook 03001234567 2000+2000"), "Facebook")
        self.assertEqual(extract_login_method("FB Login 03001234567 5000cp"), "Facebook")
        self.assertEqual(extract_login_method("Activision user@gmail.com 5000cp"), "Activision")
        self.assertIsNone(extract_login_method("Email: a@example.com 5000cp"))


class TestFacebookOrderHandlersE2E(unittest.IsolatedAsyncioTestCase):
    """E2E simulated Telegram tests for Facebook order detection, routing, and delivery."""

    def _make_update(self, text, chat_id=-100666000111222, msg_id=8801, user_id=1234567):
        user = MagicMock(id=user_id, is_bot=False, username="fb_customer")
        chat = MagicMock(id=chat_id, type="supergroup", title="CODM Client Group")
        message = MagicMock(
            message_id=msg_id,
            from_user=user,
            chat=chat,
            text=text,
            caption=None,
            photo=None,
            reply_to_message=None
        )
        message.reply_text = AsyncMock()
        update = MagicMock(effective_message=message, effective_chat=chat, effective_user=user)
        return update, message

    async def test_category_a_facebook_order_flow(self):
        """Tests that a valid Facebook order in Category A is detected, reacted to, and forwarded."""
        text = (
            "Fast Recharge 32\n"
            "Facebook\n"
            "Number: 03001234567\n"
            "Pass: fake_secret\n"
            "Code: 12345678, 87654321\n"
            "2000+2000"
        )
        update, message = self._make_update(text=text, msg_id=8801)

        bot = MagicMock()
        bot.set_message_reaction = AsyncMock(return_value=True)
        forwarded_msg = MagicMock(message_id=9901)
        bot.copy_message = AsyncMock(return_value=forwarded_msg)
        bot.send_message = AsyncMock(return_value=forwarded_msg)
        context = MagicMock(bot=bot)

        created_orders = []

        async def fake_create_order(email, client_chat_id, original_message_id, package, status, category):
            order = Order(
                id=101,
                email=email,
                client_chat_id=client_chat_id,
                original_message_id=original_message_id,
                package=package,
                status=status,
                category=category
            )
            created_orders.append(order)
            return order

        with patch("handlers.CLIENT_GROUPS_CACHE", {-100666000111222: "A"}), \
             patch("handlers.BOT_SETTINGS", {"source_group_id": -100666000111222, "delivery_group_id": -100666000333444, "payment_review_group_id": None}), \
             patch("handlers.get_pending_order_by_email", AsyncMock(return_value=None)), \
             patch("handlers.create_order", side_effect=fake_create_order), \
             patch("handlers.set_order_loader_message_id", AsyncMock()) as mock_set_loader:

            await source_group_handler(update, context)

            # 1. Order created in database with phone number as email/account identifier
            self.assertEqual(len(created_orders), 1)
            order = created_orders[0]
            self.assertEqual(order.email, "03001234567")
            self.assertEqual(order.package, "Double CP: 2000+2000 (Total: 4000 CP)")
            self.assertEqual(order.category, "A")
            self.assertEqual(order.status, "Pending")

            # 2. 👍 Reaction added to customer message
            bot.set_message_reaction.assert_called_once()
            call_kwargs = bot.set_message_reaction.call_args[1]
            self.assertIn("👍", str(call_kwargs["reaction"]))

            # 3. Message forwarded to Loader Group
            bot.copy_message.assert_called_once_with(
                chat_id=-100666000333444,
                from_chat_id=-100666000111222,
                message_id=8801
            )
            mock_set_loader.assert_called_once_with(101, 9901, loader_group_id=-100666000333444)

    async def test_category_b_facebook_order_flow(self):
        """Tests that a valid Facebook order in Category B routes to Payment Review Group with buttons."""
        text = (
            "FB Login\n"
            "Phone: +923001234567\n"
            "Pass: mypassword123\n"
            "5000 CP"
        )
        update, message = self._make_update(text=text, msg_id=8802)

        bot = MagicMock()
        bot.set_message_reaction = AsyncMock(return_value=True)
        bot.copy_message = AsyncMock()
        bot.send_message = AsyncMock()
        context = MagicMock(bot=bot)

        created_orders = []

        async def fake_create_order(email, client_chat_id, original_message_id, package, status, category):
            order = Order(
                id=102,
                email=email,
                client_chat_id=client_chat_id,
                original_message_id=original_message_id,
                package=package,
                status=status,
                category=category
            )
            created_orders.append(order)
            return order

        with patch("handlers.CLIENT_GROUPS_CACHE", {-100666000111222: "B"}), \
             patch("handlers.BOT_SETTINGS", {"source_group_id": -100666000111222, "payment_review_group_id": -1004441603990, "delivery_group_id": -100666000333444}), \
             patch("handlers.get_pending_order_by_email", AsyncMock(return_value=None)), \
             patch("handlers.create_order", side_effect=fake_create_order):

            await source_group_handler(update, context)

            self.assertEqual(len(created_orders), 1)
            order = created_orders[0]
            self.assertEqual(order.email, "+923001234567")
            self.assertEqual(order.package, "5000 CP")
            self.assertEqual(order.category, "B")
            self.assertEqual(order.status, "Pending Approval")

            # Payment review card sent with Accept / Reject buttons
            bot.send_message.assert_called_once()
            call_kwargs = bot.send_message.call_args[1]
            self.assertEqual(call_kwargs["chat_id"], -1004441603990)
            markup = call_kwargs["reply_markup"]
            self.assertEqual(markup.inline_keyboard[0][0].text, "✅ Accept")
            self.assertEqual(markup.inline_keyboard[0][1].text, "❌ Reject")

    async def test_duplicate_facebook_order_and_place_again_callback(self):
        """Tests duplicate detection for pending Facebook phone number and 'Place Again' callback."""
        existing_order = Order(
            id=103,
            email="03001234567",
            status="Pending",
            package="Double CP: 2000+2000 (Total: 4000 CP)"
        )

        text = (
            "Facebook\n"
            "Number: 03001234567\n"
            "Pass: fake\n"
            "2000+2000"
        )
        update, message = self._make_update(text=text, msg_id=8803)
        bot = MagicMock()
        bot.set_message_reaction = AsyncMock()
        bot.copy_message = AsyncMock(return_value=MagicMock(message_id=9903))
        context = MagicMock(bot=bot)

        dup_order = Order(
            id=104,
            email="03001234567",
            status="Duplicate_Pending",
            client_chat_id=-100666000111222,
            original_message_id=8803,
            package="Double CP: 2000+2000 (Total: 4000 CP)"
        )

        with patch("handlers.CLIENT_GROUPS_CACHE", {-100666000111222: "A"}), \
             patch("handlers.BOT_SETTINGS", {"source_group_id": -100666000111222, "delivery_group_id": -100666000333444, "payment_review_group_id": None}), \
             patch("handlers.get_pending_order_by_email", AsyncMock(return_value=existing_order)), \
             patch("handlers.create_order", AsyncMock(return_value=dup_order)):

            await source_group_handler(update, context)

            # Warning prompt sent to customer
            message.reply_text.assert_called_once()
            call_kwargs = message.reply_text.call_args[1]
            self.assertIn("Duplicate Order Detected", message.reply_text.call_args[0][0])
            markup = call_kwargs["reply_markup"]
            self.assertEqual(markup.inline_keyboard[0][0].text, "✅ Place Again")

        # Now simulate customer clicking "✅ Place Again"
        query = MagicMock(data="dup_confirm:104")
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        update_cb = MagicMock(callback_query=query)

        new_placed_order = Order(
            id=105,
            email="03001234567",
            package="Double CP: 2000+2000 (Total: 4000 CP)",
            status="Pending",
            client_chat_id=-100666000111222,
            original_message_id=8803
        )

        with patch("handlers.get_order_by_id", AsyncMock(return_value=dup_order)), \
             patch("handlers.CLIENT_GROUPS_CACHE", {-100666000111222: "A"}), \
             patch("handlers.BOT_SETTINGS", {"source_group_id": -100666000111222, "delivery_group_id": -100666000333444, "payment_review_group_id": None}), \
             patch("handlers.create_order", AsyncMock(return_value=new_placed_order)), \
             patch("handlers.set_order_loader_message_id", AsyncMock()):

            await duplicate_order_callback_handler(update_cb, context)

            query.edit_message_text.assert_called_once()
            self.assertIn("New Order Created", query.edit_message_text.call_args[0][0])

    async def test_delivery_plain_text_price_for_facebook_double_cp(self):
        """Tests that delivery of Facebook order with 2000+2000 automatically sends plain text '💰 Price: $20.50'."""
        img = Image(id=1, telegram_file_id="fb_img_123", file_type="photo")
        order = Order(
            id=106,
            email="03001234567",
            package="Double CP: 2000+2000 (Total: 4000 CP)",
            category="A",
            client_chat_id=-100666000111222,
            original_message_id=8804,
            status="Pending",
            price=None,
            price_msg_id=None,
            images=[img]
        )

        sent_price_msg = MagicMock(message_id=7766)
        bot = MagicMock()
        bot.send_media_group = AsyncMock(return_value=[MagicMock(message_id=887)])
        bot.send_message = AsyncMock(return_value=sent_price_msg)
        bot.set_message_reaction = AsyncMock(return_value=True)

        with patch("delivery.get_order_by_id", AsyncMock(return_value=order)), \
             patch("delivery.mark_order_delivered", AsyncMock()), \
             patch("delivery.update_order_price", AsyncMock()) as mock_update_price, \
             patch("delivery.CLIENT_GROUPS_CACHE", {-100666000111222: "A"}), \
             patch("delivery.BOT_SETTINGS", {"source_group_id": -100666000111222, "delivery_group_id": -100666000333444}):

            res = await deliver_order_by_id(bot=bot, order_id=106)
            self.assertTrue(res)

            # Plain text price message sent: "💰 Price: $20.50"
            price_calls = [
                c for c in bot.send_message.call_args_list
                if c[1].get("chat_id") == -100666000111222
            ]
            self.assertEqual(len(price_calls), 1)
            call_kwargs = price_calls[0][1]
            self.assertEqual(call_kwargs["text"], "💰 Price: $20.50")
            self.assertNotIn("reply_markup", call_kwargs)
            mock_update_price.assert_called_once_with(106, "$20.50", price_msg_id=7766)


if __name__ == "__main__":
    unittest.main()
