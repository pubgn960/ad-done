"""
Fully mocked end-to-end automated tests for Normal CP and Double CP order workflows.
Covers actual handler execution (source_group_handler and duplicate_order_callback_handler)
with all Telegram, database, and external dependencies mocked. Zero real messages or DB writes occur.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import handlers
from handlers import source_group_handler, duplicate_order_callback_handler

CLIENT_CHAT_ID = -100777000111222
LOADER_CHAT_ID = -100777000333444
PAYMENT_CHAT_ID = -100777000555666
USER_ID = 9000000001
BOT_USER_ID = 9000000002


class MockOrderStore:
    """In-memory mocked database store simulating async Order CRUD functions."""

    def __init__(self):
        self.orders = []
        self._next_id = 1
        self.get_pending_order_by_email = AsyncMock(side_effect=self._get_pending_by_email)
        self.create_order = AsyncMock(side_effect=self._create_order)
        self.set_order_loader_message_id = AsyncMock(side_effect=self._set_loader_msg_id)
        self.get_order_by_id = AsyncMock(side_effect=self._get_by_id)
        self.cancel_order = AsyncMock(side_effect=self._cancel_order)

    async def _get_pending_by_email(self, email):
        for o in self.orders:
            if o.email.lower() == email.lower() and o.status in ("Pending", "Pending Approval", "Pending Payment"):
                return o
        return None

    async def _create_order(
        self,
        email,
        client_chat_id=None,
        original_message_id=None,
        package=None,
        status="Pending",
        category="A",
    ):
        order = SimpleNamespace(
            id=self._next_id,
            email=email,
            client_chat_id=client_chat_id,
            original_message_id=original_message_id,
            package=package,
            status=status,
            category=category,
            loader_message_id=None,
            loader_group_id=None,
        )
        self._next_id += 1
        self.orders.append(order)
        return order

    async def _set_loader_msg_id(self, order_id, loader_message_id, loader_group_id=None):
        order = await self._get_by_id(order_id)
        if order:
            order.loader_message_id = loader_message_id
            order.loader_group_id = loader_group_id

    async def _get_by_id(self, order_id):
        for o in self.orders:
            if o.id == order_id:
                return o
        return None

    async def _cancel_order(self, order_id):
        order = await self._get_by_id(order_id)
        if not order:
            return None, False
        order.status = "Cancelled"
        return order, True


def make_update(*, text=None, caption=None, is_bot=False, message_id=1001, chat_id=CLIENT_CHAT_ID):
    user = MagicMock()
    user.id = BOT_USER_ID if is_bot else USER_ID
    user.is_bot = is_bot
    user.username = "MockPartnerBot" if is_bot else "mock_customer"

    chat = MagicMock()
    chat.id = chat_id
    chat.title = "Mock Client Group"

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


def make_callback_update(data):
    query = MagicMock()
    query.data = data
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    update = MagicMock()
    update.callback_query = query
    return update, query


def make_context():
    context = MagicMock()
    copied = MagicMock()
    copied.message_id = 888001
    context.bot.copy_message = AsyncMock(return_value=copied)
    context.bot.send_message = AsyncMock(return_value=copied)
    context.bot.set_message_reaction = AsyncMock(return_value=True)
    return context


class TestCompleteMockedOrderFlow(unittest.IsolatedAsyncioTestCase):
    """Automated mocked E2E tests for Normal CP & Double CP through real handlers."""

    async def asyncSetUp(self):
        self.store = MockOrderStore()
        self._orig_settings = dict(handlers.BOT_SETTINGS)
        self._orig_groups = dict(handlers.CLIENT_GROUPS_CACHE)
        self._orig_loaders = dict(handlers.LOADERS_CACHE)

        handlers.BOT_SETTINGS.update({
            "source_group_id": CLIENT_CHAT_ID,
            "delivery_group_id": LOADER_CHAT_ID,
            "payment_review_group_id": PAYMENT_CHAT_ID,
            "is_active": True,
        })
        handlers.CLIENT_GROUPS_CACHE.clear()
        handlers.CLIENT_GROUPS_CACHE[CLIENT_CHAT_ID] = "A"
        handlers.LOADERS_CACHE.clear()
        handlers.SEEN_MESSAGE_TEXT.clear()

        self._patches = [
            patch.object(handlers, "get_pending_order_by_email", self.store.get_pending_order_by_email),
            patch.object(handlers, "create_order", self.store.create_order),
            patch.object(handlers, "set_order_loader_message_id", self.store.set_order_loader_message_id),
            patch.object(handlers, "get_order_by_id", self.store.get_order_by_id),
            patch.object(handlers, "cancel_order", self.store.cancel_order),
            patch.object(handlers, "is_super_admin", return_value=False),
            patch.object(handlers, "is_delivery_user", return_value=False),
        ]
        for p in self._patches:
            p.start()

    async def asyncTearDown(self):
        for p in reversed(self._patches):
            p.stop()
        handlers.BOT_SETTINGS.clear()
        handlers.BOT_SETTINGS.update(self._orig_settings)
        handlers.CLIENT_GROUPS_CACHE.clear()
        handlers.CLIENT_GROUPS_CACHE.update(self._orig_groups)
        handlers.LOADERS_CACHE.clear()
        handlers.LOADERS_CACHE.update(self._orig_loaders)

    async def test_1_normal_cp_formats_end_to_end(self):
        cases = [
            ("norm1@gmail.com 5000", "norm1@gmail.com", "5000 CP"),
            ("norm2@outlook.com 5k", "norm2@outlook.com", "5000 CP"),
            ("norm3@hotmail.com 5000 CP", "norm3@hotmail.com", "5000 CP"),
            ("norm4@yahoo.com 5000cp", "norm4@yahoo.com", "5000 CP"),
            ("norm5@icloud.com 2400", "norm5@icloud.com", "2400 CP"),
            ("norm6@proton.me 2.4k", "norm6@proton.me", "2400 CP"),
            ("norm7@company.com 2,400 CP", "norm7@company.com", "2400 CP"),
            ("norm8@mybusiness.pk 12k", "norm8@mybusiness.pk", "12000 CP"),
        ]
        for idx, (text, exp_email, exp_pkg) in enumerate(cases, start=101):
            update, _ = make_update(text=text, message_id=idx)
            ctx = make_context()
            await source_group_handler(update, ctx)

            ctx.bot.set_message_reaction.assert_awaited_once()
            ctx.bot.copy_message.assert_awaited_once()
            self.assertEqual(ctx.bot.copy_message.await_args.kwargs["chat_id"], LOADER_CHAT_ID)

        self.assertEqual(len(self.store.orders), len(cases))
        for order, (_, exp_email, exp_pkg) in zip(self.store.orders, cases):
            self.assertEqual(order.email, exp_email)
            self.assertEqual(order.package, exp_pkg)
            self.assertEqual(order.status, "Pending")

    async def test_2_double_cp_all_combinations_and_shorthands_end_to_end(self):
        cases = [
            ("d1@gmail.com 80+80", "Double CP: 80+80 (Total: 160 CP)"),
            ("d2@gmail.com 400 + 400", "Double CP: 400+400 (Total: 800 CP)"),
            ("d3@gmail.com 800+800 CP", "Double CP: 800+800 (Total: 1600 CP)"),
            ("d4@gmail.com 2000+2000", "Double CP: 2000+2000 (Total: 4000 CP)"),
            ("d5@gmail.com 2+2", "Double CP: 2000+2000 (Total: 4000 CP)"),
            ("d6@gmail.com 2k+2k", "Double CP: 2000+2000 (Total: 4000 CP)"),
            ("d7@gmail.com 4000+4000", "Double CP: 4000+4000 (Total: 8000 CP)"),
            ("d8@gmail.com 4 + 4 cp", "Double CP: 4000+4000 (Total: 8000 CP)"),
            ("d9@gmail.com 4k+4k", "Double CP: 4000+4000 (Total: 8000 CP)"),
            ("d10@gmail.com 8,000+8,000 CP", "Double CP: 8000+8000 (Total: 16000 CP)"),
            ("d11@gmail.com 8+8", "Double CP: 8000+8000 (Total: 16000 CP)"),
            ("d12@gmail.com 8k + 8k CP", "Double CP: 8000+8000 (Total: 16000 CP)"),
        ]
        for idx, (text, exp_pkg) in enumerate(cases, start=201):
            update, _ = make_update(text=text, message_id=idx)
            ctx = make_context()
            await source_group_handler(update, ctx)
            ctx.bot.set_message_reaction.assert_awaited_once()
            ctx.bot.copy_message.assert_awaited_once()

        self.assertEqual(len(self.store.orders), len(cases))
        for order, (_, exp_pkg) in zip(self.store.orders, cases):
            self.assertEqual(order.package, exp_pkg)
            self.assertTrue(order.package.startswith("Double CP: "))

    async def test_3_universal_email_domains_accepted_through_handler(self):
        domains = [
            "a@gmail.com",
            "b@outlook.com",
            "c@hotmail.com",
            "d@yahoo.com",
            "e@icloud.com",
            "f@proton.me",
            "g@custom-company.pk",
            "h@regional.co.uk",
            "i@org.com.pk",
            "j@brand.technology",
            "k@shop.digital",
        ]
        for idx, addr in enumerate(domains, start=301):
            update, _ = make_update(text=f"Email: {addr} / 5000 CP", message_id=idx)
            ctx = make_context()
            await source_group_handler(update, ctx)
            ctx.bot.copy_message.assert_awaited_once()

        self.assertEqual([o.email for o in self.store.orders], domains)

    async def test_4_invalid_orders_cause_zero_side_effects(self):
        invalid_messages = [
            # Invalid emails + valid CP
            "user@ 5000 CP",
            "@gmail.com 5000 CP",
            "user@gmail 5000 CP",
            "user@.com 5000 CP",
            "user@gmail..com 5000 CP",
            "user@gmail.c 5000 CP",
            # Valid email + unsupported CP / combinations / unrelated numbers
            "valid@gmail.com 3+3",
            "valid@gmail.com 500+500",
            "valid@gmail.com 12345 CP",
            "valid@gmail.com\nPrice: 5000",
            "valid@gmail.com\nUID: 2400",
            "player.5000@gmail.com",
            # CP-only & questions
            "5000 CP",
            "8+8",
            "Is 5000 CP available?",
            "Berna SUY1995 8000+8000??",
            # Email-only
            "valid@gmail.com",
            "user@custom-domain.co.uk",
        ]
        for idx, text in enumerate(invalid_messages, start=401):
            update, msg = make_update(text=text, message_id=idx)
            ctx = make_context()
            await source_group_handler(update, ctx)

            ctx.bot.set_message_reaction.assert_not_awaited()
            ctx.bot.copy_message.assert_not_awaited()
            ctx.bot.send_message.assert_not_awaited()
            msg.reply_text.assert_not_awaited()

        self.store.get_pending_order_by_email.assert_not_awaited()
        self.store.create_order.assert_not_awaited()
        self.assertEqual(len(self.store.orders), 0)

    async def test_5_text_photo_caption_and_bot_originated_category_a_and_b(self):
        # 1. Text message (Category A, Normal CP)
        u1, _ = make_update(text="u1@company.pk 5000", message_id=501)
        c1 = make_context()
        await source_group_handler(u1, c1)
        self.assertEqual(self.store.orders[-1].package, "5000 CP")
        self.assertEqual(self.store.orders[-1].category, "A")
        c1.bot.copy_message.assert_awaited_once()
        self.assertEqual(c1.bot.copy_message.await_args.kwargs["chat_id"], LOADER_CHAT_ID)

        # 2. Photo caption (Category A, Double CP)
        u2, _ = make_update(caption="u2@proton.me 4+4", message_id=502)
        c2 = make_context()
        await source_group_handler(u2, c2)
        self.assertEqual(self.store.orders[-1].package, "Double CP: 4000+4000 (Total: 8000 CP)")
        c2.bot.set_message_reaction.assert_awaited_once()
        c2.bot.copy_message.assert_awaited_once()

        # 3. Bot-originated order (Category B -> routes to Payment Review Group)
        handlers.CLIENT_GROUPS_CACHE[CLIENT_CHAT_ID] = "B"
        u3, _ = make_update(
            text="Fast Recharge 32\nEmail: u3@example.co.uk\nPass: fake\n5000cp\nActivision",
            is_bot=True,
            message_id=503,
        )
        c3 = make_context()
        await source_group_handler(u3, c3)
        o3 = self.store.orders[-1]
        self.assertEqual(o3.email, "u3@example.co.uk")
        self.assertEqual(o3.package, "5000 CP")
        self.assertEqual(o3.status, "Pending Approval")
        self.assertEqual(o3.category, "B")
        c3.bot.copy_message.assert_awaited_once()
        self.assertEqual(c3.bot.copy_message.await_args.kwargs["chat_id"], PAYMENT_CHAT_ID)
        c3.bot.send_message.assert_awaited_once()

        # 4. Bot-originated invalid message (Category B) -> silently ignored
        u4, msg4 = make_update(text="Fast Recharge 32\n5000cp\nActivision", is_bot=True, message_id=504)
        c4 = make_context()
        await source_group_handler(u4, c4)
        c4.bot.set_message_reaction.assert_not_awaited()
        c4.bot.copy_message.assert_not_awaited()
        c4.bot.send_message.assert_not_awaited()
        msg4.reply_text.assert_not_awaited()

    async def test_6_duplicate_flow_in_both_handlers_for_normal_and_double_cp(self):
        # Place initial Normal CP order
        u_first, _ = make_update(text="dup.norm@gmail.com 2,400 CP", message_id=601)
        await source_group_handler(u_first, make_context())
        self.assertEqual(len(self.store.orders), 1)

        # Duplicate Normal CP order triggers prompt without forwarding
        u_dup_norm, msg_dup_norm = make_update(text="dup.norm@gmail.com 2.4k", message_id=602)
        c_dup_norm = make_context()
        await source_group_handler(u_dup_norm, c_dup_norm)
        msg_dup_norm.reply_text.assert_awaited_once()
        c_dup_norm.bot.set_message_reaction.assert_not_awaited()
        c_dup_norm.bot.copy_message.assert_not_awaited()
        dup_norm_rec = self.store.orders[-1]
        self.assertEqual(dup_norm_rec.status, "Duplicate_Pending")

        # Confirm Normal CP duplicate via duplicate_order_callback_handler
        cb_u1, _ = make_callback_update(f"dup_confirm:{dup_norm_rec.id}")
        cb_c1 = make_context()
        await duplicate_order_callback_handler(cb_u1, cb_c1)
        cb_c1.bot.copy_message.assert_awaited_once()
        cb_c1.bot.set_message_reaction.assert_awaited_once()
        self.assertEqual(self.store.orders[-1].package, "2400 CP")
        self.assertEqual(self.store.orders[-1].status, "Pending")

        # Place initial Double CP order + Duplicate Double CP order
        await source_group_handler(make_update(text="dup.dbl@proton.me 8+8", message_id=603)[0], make_context())
        u_dup_dbl, msg_dup_dbl = make_update(text="dup.dbl@proton.me 8k+8k", message_id=604)
        await source_group_handler(u_dup_dbl, make_context())
        msg_dup_dbl.reply_text.assert_awaited_once()
        dup_dbl_rec = self.store.orders[-1]
        self.assertEqual(dup_dbl_rec.package, "Double CP: 8000+8000 (Total: 16000 CP)")

        # Confirm Double CP duplicate via duplicate_order_callback_handler
        cb_u2, _ = make_callback_update(f"dup_confirm:{dup_dbl_rec.id}")
        cb_c2 = make_context()
        await duplicate_order_callback_handler(cb_u2, cb_c2)
        cb_c2.bot.copy_message.assert_awaited_once()
        self.assertEqual(self.store.orders[-1].package, "Double CP: 8000+8000 (Total: 16000 CP)")

        # Malformed stored duplicate record must be blocked by shared validator
        bad_dup = await self.store._create_order(
            email="bad@invalid",
            client_chat_id=CLIENT_CHAT_ID,
            original_message_id=605,
            package="Standard Package",
            status="Duplicate_Pending",
            category="A",
        )
        cb_u3, _ = make_callback_update(f"dup_confirm:{bad_dup.id}")
        cb_c3 = make_context()
        before_count = len(self.store.orders)
        await duplicate_order_callback_handler(cb_u3, cb_c3)
        cb_c3.bot.copy_message.assert_not_awaited()
        self.assertEqual(len(self.store.orders), before_count)


if __name__ == "__main__":
    unittest.main()
