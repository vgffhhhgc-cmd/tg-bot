import asyncio
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
import threading
import time
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

TOKEN = "9153210051:AAHE_03kRXkYpXhhb9oxmkZoa0XcKiW3nEg"
CONTACT_REQUEST_TTL = 24 * 60 * 60

bot = Bot(token=TOKEN)
dp = Dispatcher()

profiles: dict[int, dict] = {}
seen_profiles: dict[int, set[int]] = {}
likes_given: dict[int, set[int]] = {}
matches_by_user: dict[int, set[int]] = {}
# Дата мэтча для пары: {(user_a, user_b): "ДД.ММ.ГГГГ"}
match_dates: dict[tuple[int, int], str] = {}
user_titles: dict[int, str] = {}
# Активные анонимные чаты: {user_id: partner_id}
active_chats: dict[int, int] = {}
blocked_users: dict[int, set[int]] = {}
reports_log: list[dict] = []
contact_requests: dict[tuple[int, int], dict] = {}

DONATE_TITLES = {
    "title_sinner": "🥀 Грешник",
    "title_patron": "🖤 Покровитель тьмы",
    "title_sponsor": "💋 Спонсор чужой любви",
}


class RegForm(StatesGroup):
    waiting_name = State()
    waiting_age = State()
    waiting_city = State()
    waiting_looking_for = State()
    waiting_bio = State()
    waiting_photo = State()


def keepalive() -> None:
    port = int(os.environ.get("PORT", 10000))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, format: str, *args) -> None:
            return

    HTTPServer(("0.0.0.0", port), Handler).serve_forever()


def format_contact_link(user_id: int, tg_user: types.User | None = None) -> str:
    username = None
    if tg_user and tg_user.username:
        username = tg_user.username
    elif user_id in profiles:
        username = profiles[user_id].get("username")
    if username:
        return f"@{username}"
    return f"tg://user?id={user_id}"


def is_blocked_between(user_a: int, user_b: int) -> bool:
    return (user_b in blocked_users.get(user_a, set())) or (
        user_a in blocked_users.get(user_b, set())
    )


def get_match_date(user_a: int, user_b: int) -> str:
    pair = (min(user_a, user_b), max(user_a, user_b))
    return match_dates.get(pair, datetime.now().strftime("%d.%m.%Y"))


def record_match(user_a: int, user_b: int) -> None:
    matches_by_user.setdefault(user_a, set()).add(user_b)
    matches_by_user.setdefault(user_b, set()).add(user_a)
    pair = (min(user_a, user_b), max(user_a, user_b))
    if pair not in match_dates:
        match_dates[pair] = datetime.now().strftime("%d.%m.%Y")


def get_pending_request(requester_id: int, target_id: int) -> dict | None:
    req = contact_requests.get((requester_id, target_id))
    if not req or req.get("status") != "pending":
        return None
    if time.time() - req.get("created_at", 0) > CONTACT_REQUEST_TTL:
        req["status"] = "expired"
        return None
    return req


def build_anon_chat_keyboard(partner_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💌 Обменяться контактами", callback_data="contact_req_send"
                )
            ],
            [
                InlineKeyboardButton(
                    text="✖️ Отозвать запрос контактов",
                    callback_data="contact_req_cancel",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🚫 Заблокировать", callback_data=f"block_user:{partner_id}"
                ),
                InlineKeyboardButton(
                    text="⚠️ Пожаловаться", callback_data=f"report_user:{partner_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="↩️ К взаимкам", callback_data="matches_back"
                )
            ],
        ]
    )


def build_match_card_keyboard(target_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💌 Написать этому чуду",
                    callback_data=f"match_chat:{target_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="👀 Посмотреть анкету",
                    callback_data=f"match_view:{target_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🖕 Удалить из взаимок",
                    callback_data=f"match_del_ask:{target_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🚫 Заблокировать", callback_data=f"block_user:{target_id}"
                ),
                InlineKeyboardButton(
                    text="⚠️ Пожаловаться", callback_data=f"report_user:{target_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="↩️ Вернуться назад", callback_data="matches_back"
                )
            ],
        ]
    )


def format_profile_caption(
    profile: dict,
    header: str = "🃏 Твой козырь",
    user_id: int | None = None,
    match_date: str | None = None,
) -> str:
    title_line = ""
    if user_id is not None and user_titles.get(user_id):
        title_line = f"\nТитул: {user_titles[user_id]}"
    date_line = f"\nДата мэтча: {match_date}" if match_date else ""
    return (
        f"{header}:\n"
        f"Имя: {profile.get('name')}, {profile.get('age')}\n"
        f"Город: {profile.get('city')}\n"
        f"Пол: {profile.get('gender')} | Ищет/интересы: {profile.get('looking_for')}\n"
        f"О себе: {profile.get('bio')}{title_line}{date_line}"
    )


def get_next_candidate_id(viewer_id: int) -> int | None:
    viewed = seen_profiles.setdefault(viewer_id, set())
    for uid in profiles:
        if uid != viewer_id and uid not in viewed and not is_blocked_between(viewer_id, uid):
            return uid
    return None


async def send_candidate(message: types.Message, viewer_id: int, target_id: int) -> None:
    candidate = profiles[target_id]
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="❤️", callback_data=f"swipe_like:{target_id}"),
                InlineKeyboardButton(text="👎", callback_data=f"swipe_skip:{target_id}"),
            ]
        ]
    )
    await message.answer_photo(
        photo=candidate["photo_id"],
        caption=format_profile_caption(candidate, header="👀 Твой типаж", user_id=target_id),
        reply_markup=keyboard,
    )


async def send_match_card(message: types.Message, viewer_id: int, target_id: int) -> None:
    candidate = profiles.get(target_id)
    if not candidate:
        await message.answer("Анкета больше недоступна.")
        return
    caption = format_profile_caption(
        candidate,
        header="💌 Открыть переписку",
        user_id=target_id,
        match_date=get_match_date(viewer_id, target_id),
    )
    await message.answer_photo(
        photo=candidate["photo_id"],
        caption=caption,
        reply_markup=build_match_card_keyboard(target_id),
    )


async def open_matches_section(message: types.Message, user_id: int) -> None:
    intro = (
        "💋 ТВОИ ЛЮБОВНЫЕ ПРОЁБЫ:\n"
        "Люди, которым ты зачем-то понравился. Соболезную. 🖤\n\n"
        "💋 Ну что, полез смотреть, кому ты успел вскружить голову?\n"
        "Вот твои взаимки — коллекция людей, которые добровольно согласились "
        "связать свою судьбу с твоей сомнительной персоной.\n"
        "Выбирай, кого сегодня будешь сводить с ума. 🖤"
    )
    matched_ids = [
        mid
        for mid in matches_by_user.get(user_id, set())
        if mid in profiles and not is_blocked_between(user_id, mid)
    ]
    await message.answer(intro)
    if not matched_ids:
        await message.answer("Взаимок пока нет. Иди крути анкеты через /find.")
        return
    for mid in matched_ids:
        await send_match_card(message, user_id, mid)


async def enter_anon_chat(message: types.Message, user_id: int, partner_id: int) -> None:
    if is_blocked_between(user_id, partner_id):
        await message.answer("Переписка недоступна из-за блокировки.")
        return
    active_chats[user_id] = partner_id
    active_chats[partner_id] = user_id
    partner_name = profiles.get(partner_id, {}).get("name", "собеседником")
    text = (
        f"Комната с {partner_name}:\n\n"
        "🖤 Добро пожаловать в вашу маленькую комнату греха.\n"
        "Здесь вы можете переписываться, флиртовать и нести друг другу романтическую хуйню.\n"
        "Ваши личные аккаунты останутся скрытыми. Захотите раскрыть друг другу личности — "
        "решите это вместе.\n"
        "Любовь любовью, а безопасность никто не отменял, ебанько. 💋\n\n"
        "Просто напиши сообщение — бот анонимно передаст его."
    )
    await message.answer(text, reply_markup=build_anon_chat_keyboard())


def build_donate_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👁️ Подглядеть лайки", callback_data="don_peek_likes"
                )
            ],
            [InlineKeyboardButton(text="🚀 Поднять анкету", callback_data="don_boost")],
            [
                InlineKeyboardButton(
                    text="🎯 Доп. лайки", callback_data="don_extra_likes"
                ),
                InlineKeyboardButton(
                    text="🔄 Отменить дизлайк", callback_data="don_undo_skip"
                ),
            ],
            [InlineKeyboardButton(text="🖤 Купить VIP", callback_data="don_vip")],
            [
                InlineKeyboardButton(
                    text="🥀 Поддержать проект", callback_data="don_support"
                )
            ],
        ]
    )


@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    if message.from_user and message.from_user.id in profiles and message.from_user.username:
        profiles[message.from_user.id]["username"] = message.from_user.username
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="😎 Погнали, я в деле", callback_data="reg_start")]
        ]
    )
    await message.answer("Привет! Готова начать?", reply_markup=keyboard)


@dp.callback_query(F.data == "reg_start")
async def on_reg_start(callback: types.CallbackQuery):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Девушка", callback_data="gender_f"),
                InlineKeyboardButton(text="Парень", callback_data="gender_m"),
            ]
        ]
    )
    await callback.message.answer("Выбери свой пол:", reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(F.data.in_({"gender_f", "gender_m"}))
async def on_gender(callback: types.CallbackQuery, state: FSMContext):
    gender_label = "Девушка" if callback.data == "gender_f" else "Парень"
    await state.update_data(gender=gender_label)
    await state.set_state(RegForm.waiting_name)
    await callback.message.answer(f"Пол сохранён: {gender_label}. Как тебя зовут?")
    await callback.answer()


@dp.message(RegForm.waiting_name)
async def on_name(message: types.Message, state: FSMContext):
    name = (message.text or "").strip()
    if not name:
        await message.answer("Напиши имя текстом.")
        return
    await state.update_data(name=name)
    await state.set_state(RegForm.waiting_age)
    await message.answer("Сколько тебе лет? (только число, от 16)")


@dp.message(RegForm.waiting_age)
async def on_age(message: types.Message, state: FSMContext):
    raw_age = (message.text or "").strip()
    if not raw_age.isdigit():
        await message.answer("Напиши возраст числом, например: 21.")
        return
    age = int(raw_age)
    if age < 16 or age > 99:
        await message.answer("Доступно только от 16 лет. Введи корректный возраст.")
        return
    await state.update_data(age=age)
    await state.set_state(RegForm.waiting_city)
    await message.answer("Из какого ты города?")


@dp.message(RegForm.waiting_city)
async def on_city(message: types.Message, state: FSMContext):
    city = (message.text or "").strip()
    if not city:
        await message.answer("Напиши название города текстом.")
        return
    await state.update_data(city=city)
    await state.set_state(RegForm.waiting_looking_for)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Девушку", callback_data="seek_f"),
                InlineKeyboardButton(text="Парня", callback_data="seek_m"),
            ],
            [InlineKeyboardButton(text="Без разницы", callback_data="seek_any")],
        ]
    )
    await message.answer("Кого ищешь / какие интересы?", reply_markup=keyboard)


@dp.callback_query(
    RegForm.waiting_looking_for,
    F.data.in_({"seek_f", "seek_m", "seek_any"}),
)
async def on_looking_for(callback: types.CallbackQuery, state: FSMContext):
    seek_map = {
        "seek_f": "Девушку",
        "seek_m": "Парня",
        "seek_any": "Без разницы",
    }
    looking_for = seek_map[callback.data]
    await state.update_data(looking_for=looking_for)
    await state.set_state(RegForm.waiting_bio)
    await callback.message.answer("Напиши пару слов о себе:")
    await callback.answer()


@dp.message(RegForm.waiting_bio)
async def on_bio(message: types.Message, state: FSMContext):
    bio = (message.text or "").strip()
    if not bio:
        await message.answer("Напиши описание текстом.")
        return
    await state.update_data(bio=bio)
    await state.set_state(RegForm.waiting_photo)
    await message.answer("Скинь своё фото для анкеты:")


@dp.message(RegForm.waiting_photo, F.photo)
async def on_photo(message: types.Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    await state.update_data(photo_id=photo_id)
    data = await state.get_data()
    await state.clear()

    uid = message.from_user.id if message.from_user else None
    username = message.from_user.username if message.from_user else None
    if uid is not None:
        profiles[uid] = {
            "gender": data.get("gender"),
            "name": data.get("name"),
            "age": data.get("age"),
            "city": data.get("city"),
            "looking_for": data.get("looking_for"),
            "bio": data.get("bio"),
            "photo_id": photo_id,
            "username": username,
        }

    await message.answer_photo(
        photo=photo_id,
        caption=format_profile_caption(data, user_id=uid),
    )


@dp.message(RegForm.waiting_photo)
async def on_photo_invalid(message: types.Message):
    await message.answer("Нужно отправить именно картинку/фото, а не текст.")


@dp.message(Command("me"))
async def cmd_me(message: types.Message):
    user_id = message.from_user.id if message.from_user else None
    profile = profiles.get(user_id) if user_id is not None else None
    if not profile:
        await message.answer(
            "🃏 Твой козырь пока пуст — сначала заполни анкету через /start."
        )
        return
    await message.answer_photo(
        photo=profile["photo_id"],
        caption=format_profile_caption(profile, user_id=user_id),
    )


@dp.message(Command("find"))
async def cmd_find(message: types.Message):
    if not message.from_user:
        return
    viewer_id = message.from_user.id
    if viewer_id not in profiles:
        await message.answer("Сначала заполни свою анкету через /start.")
        return
    candidate_id = get_next_candidate_id(viewer_id)
    if candidate_id is None:
        await message.answer("👀 Твой типаж: пока новых анкет нет.")
        return
    await send_candidate(message, viewer_id, candidate_id)


@dp.callback_query(F.data.startswith(("swipe_like:", "swipe_skip:")))
async def on_swipe(callback: types.CallbackQuery):
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    viewer_id = callback.from_user.id
    action, raw_target_id = callback.data.split(":", 1)
    target_id = int(raw_target_id)

    seen_profiles.setdefault(viewer_id, set()).add(target_id)

    if action == "swipe_like":
        likes_given.setdefault(viewer_id, set()).add(target_id)
        if viewer_id in likes_given.get(target_id, set()) and not is_blocked_between(
            viewer_id, target_id
        ):
            record_match(viewer_id, target_id)
            active_chats[viewer_id] = target_id
            active_chats[target_id] = viewer_id
            target_profile = profiles.get(target_id, {})
            await callback.message.answer(
                f"🍒 Взаимка с {target_profile.get('name', 'пользователем')}!"
            )
            await enter_anon_chat(callback.message, viewer_id, target_id)
        else:
            await callback.message.answer("❤️ Лайк отправлен")
    else:
        await callback.message.answer("👎 Пропущено")

    next_id = get_next_candidate_id(viewer_id)
    if next_id is None:
        await callback.message.answer("Анкеты на сегодня закончились.")
    else:
        await send_candidate(callback.message, viewer_id, next_id)

    await callback.answer()


@dp.message(Command("matches"))
async def cmd_matches(message: types.Message):
    if not message.from_user:
        return
    await open_matches_section(message, message.from_user.id)


@dp.callback_query(F.data == "matches_back")
async def on_matches_back(callback: types.CallbackQuery):
    if callback.from_user and callback.message:
        await open_matches_section(callback.message, callback.from_user.id)
    await callback.answer()


@dp.callback_query(F.data.startswith("match_view:"))
async def on_match_view(callback: types.CallbackQuery):
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    target_id = int(callback.data.split(":", 1)[1])
    await send_match_card(callback.message, callback.from_user.id, target_id)
    await callback.answer()


@dp.callback_query(F.data.startswith("match_chat:"))
async def on_match_chat(callback: types.CallbackQuery):
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    target_id = int(callback.data.split(":", 1)[1])
    await enter_anon_chat(callback.message, callback.from_user.id, target_id)
    await callback.answer()


@dp.callback_query(F.data.startswith("match_del_ask:"))
async def on_match_delete_ask(callback: types.CallbackQuery):
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    target_id = int(callback.data.split(":", 1)[1])
    target_name = profiles.get(target_id, {}).get("name", "этого человека")
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Да, удалить взаимку",
                    callback_data=f"match_del_yes:{target_id}",
                ),
                InlineKeyboardButton(
                    text="Отмена", callback_data=f"match_view:{target_id}"
                ),
            ]
        ]
    )
    await callback.message.answer(
        f"Точно удалить {target_name} из взаимок? Действие необратимо.",
        reply_markup=keyboard,
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("match_del_yes:"))
async def on_match_delete_yes(callback: types.CallbackQuery):
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    user_id = callback.from_user.id
    target_id = int(callback.data.split(":", 1)[1])
    matches_by_user.setdefault(user_id, set()).discard(target_id)
    matches_by_user.setdefault(target_id, set()).discard(user_id)
    if active_chats.get(user_id) == target_id:
        active_chats.pop(user_id, None)
    if active_chats.get(target_id) == user_id:
        active_chats.pop(target_id, None)
    await callback.message.answer("Удалено из взаимок.")
    await callback.answer()


@dp.callback_query(F.data.startswith("block_user:"))
async def on_block_user(callback: types.CallbackQuery):
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    user_id = callback.from_user.id
    target_id = int(callback.data.split(":", 1)[1])
    blocked_users.setdefault(user_id, set()).add(target_id)
    matches_by_user.setdefault(user_id, set()).discard(target_id)
    matches_by_user.setdefault(target_id, set()).discard(user_id)
    if active_chats.get(user_id) == target_id:
        active_chats.pop(user_id, None)
    if active_chats.get(target_id) == user_id:
        active_chats.pop(target_id, None)
    contact_requests.pop((user_id, target_id), None)
    contact_requests.pop((target_id, user_id), None)
    await callback.message.answer(
        "Пользователь заблокирован. Переписка и обмен контактами закрыты."
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("report_user:"))
async def on_report_user(callback: types.CallbackQuery):
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    target_id = int(callback.data.split(":", 1)[1])
    reports_log.append(
        {
            "reporter_id": callback.from_user.id,
            "target_id": target_id,
            "timestamp": time.time(),
        }
    )
    await callback.message.answer("Жалоба зафиксирована.")
    await callback.answer()


@dp.callback_query(F.data == "contact_req_send")
async def on_contact_request_send(callback: types.CallbackQuery):
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    requester_id = callback.from_user.id
    target_id = active_chats.get(requester_id)

    if not target_id:
        await callback.message.answer("Сейчас нет активного анонимного чата.")
        await callback.answer()
        return

    if is_blocked_between(requester_id, target_id):
        await callback.message.answer("Обмен контактами запрещён из-за блокировки.")
        await callback.answer()
        return

    if get_pending_request(requester_id, target_id) is not None:
        await callback.message.answer("Запрос уже отправлен и ждёт ответа.")
        await callback.answer()
        return

    if requester_id in profiles and callback.from_user.username:
        profiles[requester_id]["username"] = callback.from_user.username

    contact_requests[(requester_id, target_id)] = {
        "created_at": time.time(),
        "status": "pending",
    }

    await callback.message.answer(
        "💋 Ну всё, романтик хренов, решил раскрыть карты?\n"
        "Твой запрос отправлен. Теперь ждём, согласится ли это чудо узнать тебя поближе.\n"
        "Не нервничай, ёбаный Купидон. 🖤"
    )

    target_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💋 Да, чёрт возьми",
                    callback_data=f"contact_resp_yes:{requester_id}",
                ),
                InlineKeyboardButton(
                    text="🖕 Нет, иди нахуй",
                    callback_data=f"contact_resp_no:{requester_id}",
                ),
            ]
        ]
    )

    try:
        await bot.send_message(
            chat_id=target_id,
            text=(
                "💌 ТУТ КТО-ТО ВЛЮБИЛСЯ?\n"
                "Твой собеседник хочет обменяться с тобой Telegram-контактами.\n"
                "Кажется, анонимности ему уже недостаточно, чёртов романтик.\n"
                "Раскрываем карты?"
            ),
            reply_markup=target_keyboard,
        )
    except Exception:
        pass

    await callback.answer()


@dp.callback_query(F.data == "contact_req_cancel")
async def on_contact_request_cancel(callback: types.CallbackQuery):
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    requester_id = callback.from_user.id
    target_id = active_chats.get(requester_id)
    if not target_id:
        await callback.message.answer("Сейчас нет активного анонимного чата.")
        await callback.answer()
        return

    req = get_pending_request(requester_id, target_id)
    if not req:
        await callback.message.answer("Активного запроса на обмен контактами нет.")
        await callback.answer()
        return

    req["status"] = "canceled"
    await callback.message.answer("Запрос на обмен контактами аннулирован.")
    await callback.answer()


@dp.callback_query(F.data.startswith(("contact_resp_yes:", "contact_resp_no:")))
async def on_contact_response(callback: types.CallbackQuery):
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    target_id = callback.from_user.id
    action, raw_requester_id = callback.data.split(":", 1)
    requester_id = int(raw_requester_id)

    req = contact_requests.get((requester_id, target_id))
    if not req or req.get("status") != "pending":
        await callback.message.answer("Этот запрос уже закрыт, отменён или устарел.")
        await callback.answer()
        return

    if is_blocked_between(requester_id, target_id):
        req["status"] = "blocked"
        await callback.message.answer("Обмен контактами запрещён.")
        await callback.answer()
        return

    if action == "contact_resp_no":
        req["status"] = "declined"
        await callback.message.answer("Запрос закрыт.")
        try:
            await bot.send_message(
                chat_id=requester_id,
                text=(
                    "🥀 Упс, романтик.\n"
                    "Твой собеседник пока не готов раскрывать карты.\n"
                    "Не расстраивайся, маленький ебанько. Продолжайте свою анонимную любовную хуйню. "
                    "Возможно, ещё передумает. 🖤"
                ),
            )
        except Exception:
            pass
        await callback.answer()
        return

    req["status"] = "accepted"
    if target_id in profiles and callback.from_user.username:
        profiles[target_id]["username"] = callback.from_user.username

    requester_contact = format_contact_link(requester_id)
    target_contact = format_contact_link(target_id, callback.from_user)

    for uid, partner_contact in (
        (target_id, requester_contact),
        (requester_id, target_contact),
    ):
        text = (
            "🖤 НУ ВСЁ, ВЫ ДВА БЕЗНАДЁЖНЫХ.\n"
            "Кажется, анонимность закончилась, а ваша любовная катастрофа выходит на новый уровень.\n"
            f"Держите контакты друг друга: {partner_contact}.\n"
            "Только не проебите такую прекрасную возможность испортить друг другу жизнь. 💋\n"
            "(Анонимный чат остаётся открытым.)"
        )
        if uid == target_id:
            await callback.message.answer(text)
        else:
            try:
                await bot.send_message(chat_id=uid, text=text)
            except Exception:
                pass

    await callback.answer()


@dp.message(Command("donate"))
async def cmd_donate(message: types.Message):
    await message.answer(
        "Выбирай, за что сегодня отдаёшь свои кровные:",
        reply_markup=build_donate_keyboard(),
    )


@dp.callback_query(F.data == "don_peek_likes")
async def on_don_peek_likes(callback: types.CallbackQuery):
    if callback.message:
        await callback.message.answer(
            "👁️ Подглядеть лайки — узнать, кому ты успел понравиться."
        )
    await callback.answer()


@dp.callback_query(F.data == "don_boost")
async def on_don_boost(callback: types.CallbackQuery):
    if callback.message:
        await callback.message.answer("🚀 Поднять анкету — пусть тебя заметят.")
    await callback.answer()


@dp.callback_query(F.data == "don_extra_likes")
async def on_don_extra_likes(callback: types.CallbackQuery):
    if callback.message:
        await callback.message.answer(
            "🎯 Дополнительные лайки — расширить дневной лимит."
        )
    await callback.answer()


@dp.callback_query(F.data == "don_undo_skip")
async def on_don_undo_skip(callback: types.CallbackQuery):
    if callback.message:
        await callback.message.answer(
            "🔄 Отменить дизлайк — вернуть случайно пропущенную анкету."
        )
    await callback.answer()


@dp.callback_query(F.data == "don_vip")
async def on_don_vip(callback: types.CallbackQuery):
    if callback.message:
        await callback.message.answer(
            "🖤 Купить VIP — расширенные возможности без гарантии взаимности."
        )
    await callback.answer()


@dp.callback_query(F.data == "don_support")
async def on_don_support(callback: types.CallbackQuery):
    if callback.message:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🥀 Грешник", callback_data="title_sinner")],
                [
                    InlineKeyboardButton(
                        text="🖤 Покровитель тьмы", callback_data="title_patron"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="💋 Спонсор чужой любви", callback_data="title_sponsor"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="Без титула в профиле", callback_data="title_clear"
                    )
                ],
            ]
        )
        await callback.message.answer(
            "🥀 Поддержать проект — просто потому что можешь, чёртов меценат. Выбери титул по желанию:",
            reply_markup=keyboard,
        )
    await callback.answer()


@dp.callback_query(F.data.in_(set(DONATE_TITLES.keys()) | {"title_clear"}))
async def on_title_select(callback: types.CallbackQuery):
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    uid = callback.from_user.id
    if callback.data == "title_clear":
        user_titles.pop(uid, None)
        await callback.message.answer("Титул скрыт из профиля.")
    else:
        chosen = DONATE_TITLES[callback.data]
        user_titles[uid] = chosen
        await callback.message.answer(f"Выбран титул: {chosen}.")
    await callback.answer()


@dp.message(Command("settings"))
async def cmd_settings(message: types.Message):
    await message.answer("⚙️ Подкрутить")


@dp.message(F.text & ~F.text.startswith("/"))
async def on_anon_message(message: types.Message, state: FSMContext):
    if await state.get_state() is not None or not message.from_user:
        return
    sender_id = message.from_user.id
    partner_id = active_chats.get(sender_id)
    if not partner_id:
        return
    if is_blocked_between(sender_id, partner_id):
        await message.answer("Сообщение не отправлено: чат заблокирован.")
        return
    try:
        await bot.send_message(
            chat_id=partner_id,
            text=f"💌 Анонимно:\n{message.text}",
        )
    except Exception:
        await message.answer("Не удалось доставить сообщение собеседнику.")


async def main() -> None:
    threading.Thread(target=keepalive, daemon=True).start()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
