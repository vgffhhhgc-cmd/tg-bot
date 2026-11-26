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

# Временное хранилище анкет в памяти: {user_id: {gender, name, age, city, looking_for, bio, photo_id, title}}
profiles: dict[int, dict] = {}
# Кого уже просмотрел пользователь: {viewer_id: set_of_target_ids}
seen_profiles: dict[int, set[int]] = {}
# Порядок просмотренных анкет для отката последнего свайпа: {viewer_id: [target_id, ...]}
swipe_history: dict[int, list[int]] = {}
# Кого лайкнул пользователь: {user_id: set_of_liked_ids}
likes_given: dict[int, set[int]] = {}
# Взаимные совпадения: {user_id: set_of_matched_ids}
matches_by_user: dict[int, set[int]] = {}
# Выбранный донатерский титул (показывается только по желанию): {user_id: title}
user_titles: dict[int, str] = {}

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


def format_profile_caption(
    profile: dict, header: str = "🃏 Твой козырь", user_id: int | None = None
) -> str:
    title_line = ""
    if user_id is not None and user_titles.get(user_id):
        title_line = f"\nТитул: {user_titles[user_id]}"
    return (
        f"{header}:\n"
        f"Имя: {profile.get('name')}, {profile.get('age')}\n"
        f"Город: {profile.get('city')}\n"
        f"Пол: {profile.get('gender')} | Ищет: {profile.get('looking_for')}\n"
        f"О себе: {profile.get('bio')}{title_line}"
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
        caption=format_profile_caption(candidate, header="👀 Твой типаж", user_id=target_id),
        reply_markup=keyboard,
    )


def build_donate_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👁️ Подглядеть лайки", callback_data="don_peek_likes")],
            [InlineKeyboardButton(text="🚀 Поднять анкету", callback_data="don_boost")],
            [
                InlineKeyboardButton(text="🎯 Доп. лайки", callback_data="don_extra_likes"),
                InlineKeyboardButton(text="🔄 Отменить дизлайк", callback_data="don_undo_skip"),
            ],
            [InlineKeyboardButton(text="🖤 Купить VIP", callback_data="don_vip")],
            [InlineKeyboardButton(text="🥀 Поддержать проект", callback_data="don_support")],
        ]
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
    data =
