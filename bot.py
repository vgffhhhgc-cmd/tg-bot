import asyncio
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

TOKEN = "9153210051:AAHE_03kRXkYpXhhb9oxmkZoa0XcKiW3nEg"

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Временное хранилище анкет в памяти: {user_id: {gender, name, age, city, looking_for, bio, photo_id}}
profiles: dict[int, dict] = {}
# Кого уже просмотрел пользователь: {viewer_id: set_of_target_ids}
seen_profiles: dict[int, set[int]] = {}
# Кого лайкнул пользователь: {user_id: set_of_liked_ids}
likes_given: dict[int, set[int]] = {}
# Взаимные совпадения: {user_id: set_of_matched_ids}
matches_by_user: dict[int, set[int]] = {}


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


def format_profile_caption(profile: dict, header: str = "🃏 Твой козырь") -> str:
    return (
        f"{header}:\n"
        f"Имя: {profile.get('name')}, {profile.get('age')}\n"
        f"Город: {profile.get('city')}\n"
        f"Пол: {profile.get('gender')} | Ищет: {profile.get('looking_for')}\n"
        f"О себе: {profile.get('bio')}"
    )


def get_next_candidate_id(viewer_id: int) -> int | None:
    viewed = seen_profiles.setdefault(viewer_id, set())
    for uid in profiles:
        if uid != viewer_id and uid not in viewed:
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
        caption=format_profile_caption(candidate, header="👀 Твой типаж"),
        reply_markup=keyboard,
    )


@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
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
    await message.answer("Кого ищешь?", reply_markup=keyboard)


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

    if message.from_user:
        profiles[message.from_user.id] = {
            "gender": data.get("gender"),
            "name": data.get("name"),
            "age": data.get("age"),
            "city": data.get("city"),
            "looking_for": data.get("looking_for"),
            "bio": data.get("bio"),
            "photo_id": photo_id,
        }

    await message.answer_photo(
        photo=photo_id,
        caption=format_profile_caption(data),
    )


@dp.message(RegForm.waiting_photo)
async def on_photo_invalid(message: types.Message):
    await message.answer("Нужно отправить именно картинку/фото, а не текст.")


@dp.message(Command("me"))
async def cmd_me(message: types.Message):
    user_id = message.from_user.id if message.from_user else None
    profile = profiles.get(user_id) if user_id is not None else None
    if not profile:
        await message.answer("🃏 Твой козырь пока пуст — сначала заполни анкету через /start.")
        return
    await message.answer_photo(
        photo=profile["photo_id"],
        caption=format_profile_caption(profile),
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
        if viewer_id in likes_given.get(target_id, set()):
            matches_by_user.setdefault(viewer_id, set()).add(target_id)
            matches_by_user.setdefault(target_id, set()).add(viewer_id)
            target_profile = profiles.get(target_id, {})
            await callback.message.answer(
                f"🍒 Взаимка с {target_profile.get('name', 'пользователем')}!"
            )
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
    user_id = message.from_user.id
    matched_ids = matches_by_user.get(user_id, set())
    if not matched_ids:
        await message.answer("🍒 Взаимок пока нет.")
        return

    lines = ["🍒 Твои взаимки:"]
    for mid in matched_ids:
        p = profiles.get(mid)
        if p:
            lines.append(f"• {p.get('name')}, {p.get('age')} — {p.get('city')}")
    await message.answer("\n".join(lines))


@dp.message(Command("donate"))
async def cmd_donate(message: types.Message):
    await
