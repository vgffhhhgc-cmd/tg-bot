import asyncio
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import threading
import time
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    PreCheckoutQuery,
)

TOKEN = "9153210051:AAHE_03kRXkYpXhhb9oxmkZoa0XcKiW3nEg"
CONTACT_REQUEST_TTL = 24 * 60 * 60
GENERAL_CHAT_URL = "https://t.me/+0zfQwL8xH9diY2My"
EXTRA_LIKES_PACK_SIZE = 10
BOOST_DURATION_SEC = 24 * 60 * 60
VIP_DURATION_SEC = 30 * 24 * 60 * 60
SUPPORT_STARS_AMOUNT = 50
PEEK_LIKES_STARS_AMOUNT = 15
STATE_FILE_PATH = os.environ.get("STATE_FILE_PATH", "bot_state.json")
# Укажи сюда свой Telegram ID (числом) для доступа в /mod
ADMIN_IDS: set[int] = set()

bot = Bot(token=TOKEN)
dp = Dispatcher()

profiles: dict[int, dict] = {}
seen_profiles: dict[int, set[int]] = {}
skipped_history: dict[int, list[int]] = {}
undo_credits: dict[int, int] = {}
extra_likes: dict[int, int] = {}
boosted_until: dict[int, float] = {}
vip_until: dict[int, float] = {}
supporter_donations: dict[int, int] = {}
likes_given: dict[int, set[int]] = {}
matches_by_user: dict[int, set[int]] = {}
match_dates: dict[tuple[int, int], str] = {}
user_titles: dict[int, str] = {}
active_chats: dict[int, int] = {}
blocked_users: dict[int, set[int]] = {}
contact_requests: dict[tuple[int, int], dict] = {}
user_filters: dict[int, dict] = {}

chat_history: dict[tuple[int, int], list[dict]] = {}
reports_by_id: dict[int, dict] = {}
report_counter: int = 1041
user_warnings: dict[int, int] = {}
user_restrictions: dict[int, dict] = {}
sos_requests: list[dict] = []

DONATE_TITLES = {
    "title_sinner": "🥀 Грешник",
    "title_patron": "🖤 Покровитель тьмы",
    "title_sponsor": "💋 Спонсор чужой любви",
}

REPORT_REASONS = {
    "rep_insult": ("💬 Оскорбления и травля", False),
    "rep_spam": ("📨 Спам и навязчивые сообщения", False),
    "rep_nsfw": ("🔞 Запрещённый сексуальный контент", True),
    "rep_fake": ("🎭 Фейковая анкета / выдаёт себя за другого", False),
    "rep_threats": ("⚠️ Угрозы и преследование", True),
    "rep_minor": ("🚫 Несовершеннолетний в анкете / возрастное несоответствие", True),
    "rep_other": ("❓ Другая причина", False),
}


class RegForm(StatesGroup):
    waiting_name = State()
    waiting_age = State()
    waiting_city = State()
    waiting_looking_for = State()
    waiting_bio = State()
    waiting_photo = State()


class FilterForm(StatesGroup):
    waiting_age_range = State()


class ReportForm(StatesGroup):
    waiting_comment = State()


class SosForm(StatesGroup):
    waiting_message = State()


def _pair_to_str(pair: tuple[int, int]) -> str:
    return f"{pair[0]}:{pair[1]}"


def _str_to_pair(key: str) -> tuple[int, int] | None:
    parts = key.split(":", 1)
    if len(parts) != 2 or not parts[0].lstrip("-").isdigit() or not parts[1].lstrip("-").isdigit():
        return None
    return (int(parts[0]), int(parts[1]))


def save_state() -> None:
    try:
        payload = {
            "profiles": {str(k): v for k, v in profiles.items()},
            "seen_profiles": {str(k): list(v) for k, v in seen_profiles.items()},
            "skipped_history": {str(k): list(v) for k, v in skipped_history.items()},
            "undo_credits": {str(k): v for k, v in undo_credits.items()},
            "extra_likes": {str(k): v for k, v in extra_likes.items()},
            "boosted_until": {str(k): v for k, v in boosted_until.items()},
            "vip_until": {str(k): v for k, v in vip_until.items()},
            "supporter_donations": {str(k): v for k, v in supporter_donations.items()},
            "likes_given": {str(k): list(v) for k, v in likes_given.items()},
            "matches_by_user": {str(k): list(v) for k, v in matches_by_user.items()},
            "match_dates": {_pair_to_str(k): v for k, v in match_dates.items()},
            "user_titles": {str(k): v for k, v in user_titles.items()},
            "active_chats": {str(k): v for k, v in active_chats.items()},
            "blocked_users": {str(k): list(v) for k, v in blocked_users.items()},
            "contact_requests": {_pair_to_str(k): v for k, v in contact_requests.items()},
            "user_filters": {str(k): v for k, v in user_filters.items()},
            "chat_history": {_pair_to_str(k): v for k, v in chat_history.items()},
            "reports_by_id": {str(k): v for k, v in reports_by_id.items()},
            "report_counter": report_counter,
            "user_warnings": {str(k): v for k, v in user_warnings.items()},
            "user_restrictions": {str(k): v for k, v in user_restrictions.items()},
            "sos_requests": sos_requests,
        }
        tmp_path = f"{STATE_FILE_PATH}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, STATE_FILE_PATH)
    except Exception:
        pass


def load_state() -> None:
    global report_counter
    if not os.path.exists(STATE_FILE_PATH):
        return
    try:
        with open(STATE_FILE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return

        for k, v in data.get("profiles", {}).items():
            if k.lstrip("-").isdigit() and isinstance(v, dict):
                profiles[int(k)] = v
        for k, v in data.get("seen_profiles", {}).items():
            if k.lstrip("-").isdigit() and isinstance(v, list):
                seen_profiles[int(k)] = {int(x) for x in v}
        for k, v in data.get("skipped_history", {}).items():
            if k.lstrip("-").isdigit() and isinstance(v, list):
                skipped_history[int(k)] = [int(x) for x in v]
        for k, v in data.get("undo_credits", {}).items():
            if k.lstrip("-").isdigit():
                undo_credits[int(k)] = int(v)
        for k, v in data.get("extra_likes", {}).items():
            if k.lstrip("-").isdigit():
                extra_likes[int(k)] = int(v)
        for k, v in data.get("boosted_until", {}).items():
            if k.lstrip("-").isdigit():
                boosted_until[int(k)] = float(v)
        for k, v in data.get("vip_until", {}).items():
            if k.lstrip("-").isdigit():
                vip_until[int(k)] = float(v)
        for k, v in data.get("supporter_donations", {}).items():
            if k.lstrip("-").isdigit():
                supporter_donations[int(k)] = int(v)
        for k, v in data.get("likes_given", {}).items():
            if k.lstrip("-").isdigit() and isinstance(v, list):
                likes_given[int(k)] = {int(x) for x in v}
        for k, v in data.get("matches_by_user", {}).items():
            if k.lstrip("-").isdigit() and isinstance(v, list):
                matches_by_user[int(k)] = {int(x) for x in v}
        for k, v in data.get("match_dates", {}).items():
            pair = _str_to_pair(k)
            if pair and isinstance(v, str):
                match_dates[pair] = v
        for k, v in data.get("user_titles", {}).items():
            if k.lstrip("-").isdigit() and isinstance(v, str):
                user_titles[int(k)] = v
        for k, v in data.get("active_chats", {}).items():
            if k.lstrip("-").isdigit():
                active_chats[int(k)] = int(v)
        for k, v in data.get("blocked_users", {}).items():
            if k.lstrip("-").isdigit() and isinstance(v, list):
                blocked_users[int(k)] = {int(x) for x in v}
        for k, v in data.get("contact_requests", {}).items():
            pair = _str_to_pair(k)
            if pair and isinstance(v, dict):
                contact_requests[pair] = v
        for k, v in data.get("user_filters", {}).items():
            if k.lstrip("-").isdigit() and isinstance(v, dict):
                user_filters[int(k)] = v
        for k, v in data.get("chat_history", {}).items():
            pair = _str_to_pair(k)
            if pair and isinstance(v, list):
                chat_history[pair] = v
        for k, v in data.get("reports_by_id", {}).items():
            if k.isdigit() and isinstance(v, dict):
                reports_by_id[int(k)] = v
        if isinstance(data.get("report_counter"), int):
            report_counter = data["report_counter"]
        for k, v in data.get("user_warnings", {}).items():
            if k.lstrip("-").isdigit():
                user_warnings[int(k)] = int(v)
        for k, v in data.get("user_restrictions", {}).items():
            if k.lstrip("-").isdigit() and isinstance(v, dict):
                user_restrictions[int(k)] = v
        if isinstance(data.get("sos_requests"), list):
            sos_requests.extend(data["sos_requests"])
    except Exception:
        pass


def is_user_boosted(user_id: int) -> bool:
    until = boosted_until.get(user_id, 0)
    if until > time.time():
        return True
    if user_id in boosted_until:
        boosted_until.pop(user_id, None)
        save_state()
    return False


def is_user_vip(user_id: int) -> bool:
    until = vip_until.get(user_id, 0)
    if until > time.time():
        return True
    if user_id in vip_until:
        vip_until.pop(user_id, None)
        save_state()
    return False


def get_pair_key(user_a: int, user_b: int) -> tuple[int, int]:
    return (min(user_a, user_b), max(user_a, user_b))


def record_chat_message(sender_id: int, receiver_id: int, text: str) -> None:
    key = get_pair_key(sender_id, receiver_id)
    bucket = chat_history.setdefault(key, [])
    bucket.append(
        {
            "sender_id": sender_id,
            "text": text,
            "time": datetime.now().strftime("%d.%m %H:%M"),
        }
    )
    if len(bucket) > 30:
        del bucket[:-30]
    save_state()


def get_restriction_status(user_id: int) -> str | None:
    info = user_restrictions.get(user_id)
    if not info:
        return None
    if info.get("banned"):
        return "Аккаунт заблокирован модерацией."
    until = info.get("until", 0)
    if until > time.time():
        dt_str = datetime.fromtimestamp(until).strftime("%d.%m.%Y %H:%M")
        return f"Аккаунт временно ограничен до {dt_str}."
    user_restrictions.pop(user_id, None)
    save_state()
    return None


def get_default_filters() -> dict:
    return {
        "gender_pref": "all",
        "age_min": 18,
        "age_max": 25,
        "city_mode": "any",
        "distance": "any",
    }


def get_user_filter(user_id: int) -> dict:
    if user_id not in user_filters:
        user_filters[user_id] = get_default_filters()
        save_state()
    return user_filters[user_id]


def format_filters_summary(user_id: int) -> str:
    f = get_user_filter(user_id)
    gender_map = {"all": "Всех подряд", "m": "Только парней", "f": "Только девушек"}
    city_map = {"any": "Любой город", "my": "Только мой город"}
    dist_map = {"any": "Без ограничений", "near": "Поблизости"}
    return (
        "⚙️ ТВОИ НАСТРОЙКИ:\n"
        "Давай подберём тебе кого-нибудь, пока ты окончательно не ебанулся от одиночества.\n\n"
        f"💋 Кого ищем: {gender_map.get(f['gender_pref'], 'Всех подряд')}\n"
        f"🎂 Возрастной диапазон: {f['age_min']} — {f['age_max']} лет\n"
        f"📍 Город: {city_map.get(f['city_mode'], 'Любой город')}\n"
        f"🌍 Дистанция: {dist_map.get(f['distance'], 'Без ограничений')}"
    )


def build_settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💋 Кого ищем?", callback_data="flt_gender_menu")],
            [
                InlineKeyboardButton(
                    text="🎂 Возрастной диапазон", callback_data="flt_age_menu"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📍 Город и расстояние", callback_data="flt_geo_menu"
                )
            ],
            [
                InlineKeyboardButton(
                    text="💬 ОБЩИЙ ЧАТ", callback_data="open_general_chat"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Сбросить настройки", callback_data="flt_reset"
                ),
                InlineKeyboardButton(
                    text="🖤 Сохранить изменения", callback_data="flt_save"
                ),
            ],
        ]
    )


def matches_gender_filter(pref: str, candidate_gender: str | None) -> bool:
    if pref == "all":
        return True
    if pref == "m":
        return candidate_gender == "Парень"
    if pref == "f":
        return candidate_gender == "Девушка"
    return True


def is_same_age_cohort(age_a: int, age_b: int) -> bool:
    return (age_a < 18) == (age_b < 18)


def is_mutual_match_criteria(viewer_id: int, candidate_id: int) -> bool:
    viewer = profiles.get(viewer_id)
    candidate = profiles.get(candidate_id)
    if not viewer or not candidate:
        return False
    if get_restriction_status(candidate_id) is not None:
        return False

    vf = get_user_filter(viewer_id)
    cf = get_user_filter(candidate_id)

    v_age = candidate.get("age")
    c_age = viewer.get("age")
    if not isinstance(v_age, int) or not isinstance(c_age, int):
        return False
    if not is_same_age_cohort(c_age, v_age):
        return False

    if not matches_gender_filter(vf["gender_pref"], candidate.get("gender")):
        return False
    if not (vf["age_min"] <= v_age <= vf["age_max"]):
        return False
    if vf["city_mode"] == "my":
        v_city = (viewer.get("city") or "").strip().lower()
        c_city = (candidate.get("city") or "").strip().lower()
        if not v_city or v_city != c_city:
            return False

    if not matches_gender_filter(cf["gender_pref"], viewer.get("gender")):
        return False
    if not (cf["age_min"] <= c_age <= cf["age_max"]):
        return False
    if cf["city_mode"] == "my":
        v_city = (viewer.get("city") or "").strip().lower()
        c_city = (candidate.get("city") or "").strip().lower()
        if not c_city or v_city != c_city:
            return False

    return True


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


def apply_block(blocker_id: int, target_id: int) -> None:
    blocked_users.setdefault(blocker_id, set()).add(target_id)
    matches_by_user.setdefault(blocker_id, set()).discard(target_id)
    matches_by_user.setdefault(target_id, set()).discard(blocker_id)
    if active_chats.get(blocker_id) == target_id:
        active_chats.pop(blocker_id, None)
    if active_chats.get(target_id) == blocker_id:
        active_chats.pop(target_id, None)
    contact_requests.pop((blocker_id, target_id), None)
    contact_requests.pop((target_id, blocker_id), None)
    save_state()


def get_match_date(user_a: int, user_b: int) -> str:
    pair = get_pair_key(user_a, user_b)
    return match_dates.get(pair, datetime.now().strftime("%d.%m.%Y"))


def record_match(user_a: int, user_b: int) -> None:
    matches_by_user.setdefault(user_a, set()).add(user_b)
    matches_by_user.setdefault(user_b, set()).add(user_a)
    pair = get_pair_key(user_a, user_b)
    if pair not in match_dates:
        match_dates[pair] = datetime.now().strftime("%d.%m.%Y")
    save_state()


def get_pending_request(requester_id: int, target_id: int) -> dict | None:
    req = contact_requests.get((requester_id, target_id))
    if not req or req.get("status") != "pending":
        return None
    if time.time() - req.get("created_at", 0) > CONTACT_REQUEST_TTL:
        req["status"] = "expired"
        save_state()
        return None
    return req


def build_safety_keyboard(target_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚨 Пожаловаться", callback_data=f"rep_start:{target_id}"
                ),
                InlineKeyboardButton(
                    text="🖕 Заблокировать", callback_data=f"blk_direct:{target_id}"
                ),
            ]
        ]
    )


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
                    text="🚨 Пожаловаться", callback_data=f"rep_start:{partner_id}"
                ),
                InlineKeyboardButton(
                    text="🖕 Заблокировать", callback_data=f"blk_direct:{partner_id}"
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
                    text="🚨 Пожаловаться", callback_data=f"rep_start:{target_id}"
                ),
                InlineKeyboardButton(
                    text="🖕 Заблокировать", callback_data=f"blk_direct:{target_id}"
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
    include_bonuses: bool = False,
) -> str:
    vip_badge = " 🖤 VIP" if (user_id is not None and is_user_vip(user_id)) else ""
    title_line = ""
    if user_id is not None and user_titles.get(user_id):
        title_line = f"\nТитул: {user_titles[user_id]}"
    vip_line = ""
    if user_id is not None and is_user_vip(user_id):
        vip_until_str = datetime.fromtimestamp(vip_until[user_id]).strftime(
            "%d.%m.%Y"
        )
        vip_line = f"\nVIP активен до: {vip_until_str}"
    date_line = f"\nДата мэтча: {match_date}" if match_date else ""
    bonuses_line = ""
    if include_bonuses and user_id is not None:
        bonuses_line = (
            f"\nБонусы: доп. лайков — {extra_likes.get(user_id, 0)}, "
            f"откатов дизлайка — {undo_credits.get(user_id, 0)}"
        )
        donated_total = supporter_donations.get(user_id, 0)
        if donated_total > 0:
            bonuses_line += f"\nПоддержал проект на: {donated_total} ⭐"
    return (
        f"{header}{vip_badge}:\n"
        f"Имя: {profile.get('name')}, {profile.get('age')}\n"
        f"Город: {profile.get('city')}\n"
        f"Пол: {profile.get('gender')} | Ищет/интересы: {profile.get('looking_for')}\n"
        f"О себе: {profile.get('bio')}{title_line}{vip_line}{bonuses_line}{date_line}"
    )


def get_incoming_likers(user_id: int) -> list[int]:
    already_matched = matches_by_user.get(user_id, set())
    already_liked = likes_given.get(user_id, set())
    likers: list[int] = []
    for sender_id, targets in likes_given.items():
        if sender_id == user_id or sender_id not in profiles:
            continue
        if user_id not in targets:
            continue
        if sender_id in already_matched or sender_id in already_liked:
            continue
        if is_blocked_between(user_id, sender_id):
            continue
        if get_restriction_status(sender_id) is not None:
            continue
        likers.append(sender_id)
    return likers


async def send_incoming_likes_list(message: types.Message, user_id: int) -> None:
    likers = get_incoming_likers(user_id)
    if not likers:
        await message.answer(
            "👁️ Пока новых невзаимных лайков нет — либо всех уже свайпнула, "
            "либо никто ещё не успел зацепить."
        )
        return
    await message.answer(f"👁️ Тебя лайкнули ({len(likers)}):")
    for sender_id in likers[:10]:
        prof = profiles[sender_id]
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="❤️ Лайкнуть в ответ",
                        callback_data=f"peek_like_back:{sender_id}",
                    ),
                    InlineKeyboardButton(
                        text="👀 Анкета",
                        callback_data=f"peek_view:{sender_id}",
                    ),
                ]
            ]
        )
        await message.answer(
            f"• {prof.get('name')}, {prof.get('age')} — {prof.get('city')}\n"
            f"О себе: {prof.get('bio')}",
            reply_markup=kb,
        )


def get_next_candidate_id(viewer_id: int) -> int | None:
    
