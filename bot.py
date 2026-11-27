import asyncio
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import math
import os
import threading
import time
import urllib.request
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    LabeledPrice,
    PreCheckoutQuery,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)


TOKEN = os.environ.get("BOT_TOKEN", "9153210051:AAHE_03kRXkYpXhhb9oxmkZoa0XcKiW3nEg")
CONTACT_REQUEST_TTL = 24 * 60 * 60
GENERAL_CHAT_URL = "https://t.me/+0zfQwL8xH9diY2My"
EXTRA_LIKES_PACK_SIZE = 10
BOOST_DURATION_SEC = 24 * 60 * 60
VIP_DURATION_SEC = 30 * 24 * 60 * 60
SUPPORT_STARS_AMOUNT = 50
PEEK_LIKES_STARS_AMOUNT = 15
KRK_SITE_TITLE = "slon6.at"
KRK_SITE_URL = "https://slon6.at"
NEARBY_RADIUS_KM = 15.0
STATE_FILE_PATH = os.environ.get("STATE_FILE_PATH", "bot_state.json")
STORAGE_CHANNEL_ID = os.environ.get("STORAGE_CHANNEL_ID", "").strip()
# Твой Telegram ID для доступа в /mod и админку магазина «💸 Слив»
ADMIN_IDS: set[int] = {5220461940}


SHOP_REQUISITES = "2201 9604 2731 7498"
SHOP_DELIVERY_NOTICE = (
    "⚠️ По поводу доставки\n"
    "Доставка и передача заказов преимущественно по Самарской области. "
    "Возможность отправки в другие регионы обсуждается индивидуально.\n"
    "Заказы из других регионов не блокируются автоматически. "
    "Их возможность рассматривается индивидуально."
)
SHOP_ORDER_TERMS = (
    "📋 Условия оформления заказа:\n"
    f"• Оплата: перевод по реквизитам {SHOP_REQUISITES} с отправкой PDF-файла подтверждения оплаты.\n"
    "• Получение и доставка: преимущественно по Самарской области (остальные регионы — по индивидуальному согласованию).\n"
    "• Сроки обработки: заказ проверяется и обрабатывается после поступления подтверждения оплаты."
)


SHOP_STATUS_PENDING = "🟡 Ожидает проверки"
SHOP_STATUS_PAID = "🟢 Оплачен"
SHOP_STATUS_REJECTED = "🔴 Отклонён"
SHOP_STATUS_CANCELED = "⚪ Отменён"


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
user_locations: dict[int, dict] = {}
chat_history: dict[tuple[int, int], list[dict]] = {}
reports_by_id: dict[int, dict] = {}
report_counter: int = 1041
user_warnings: dict[int, int] = {}
user_restrictions: dict[int, dict] = {}
sos_requests: list[dict] = []


# Состояние модуля магазина «💸 Слив»
shop_products: dict[int, dict] = {}
shop_product_counter: int = 0
shop_orders: dict[int, dict] = {}
shop_order_counter: int = 5000


DONATE_TITLES = {
    "title_sinner": "😈 Грешник",
    "title_patron": "🖤 Покровитель тьмы",
    "title_sponsor": "💸 Спонсор чужой любви",
}


REPORT_REASONS = {
    "rep_insult": ("🤬 Оскорбления и травля", False),
    "rep_spam": ("📢 Спам и навязчивые сообщения", False),
    "rep_fake": ("🎭 Фейковая анкета / выдаёт себя за другого", False),
    "rep_nsfw": ("🔞 Запрещённый сексуальный контент", True),
    "rep_threats": ("🚨 Угрозы и преследование", True),
    "rep_minor": ("🔞 Несовершеннолетний в анкете / возрастное несоответствие", True),
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


class ShopBuyerForm(StatesGroup):
    waiting_city = State()
    waiting_payment_pdf = State()


class ShopAdminForm(StatesGroup):
    adding_title = State()
    adding_price = State()
    adding_description = State()
    adding_photo = State()
    adding_availability = State()
    editing_title = State()
    editing_price = State()
    editing_description = State()
    editing_photo = State()


def _pair_to_str(pair: tuple[int, int]) -> str:
    return f"{pair[0]}:{pair[1]}"


def _str_to_pair(key: str) -> tuple[int, int] | None:
    parts = key.split(":", 1)
    if (
        len(parts) != 2
        or not parts[0].lstrip("-").isdigit()
        or not parts[1].lstrip("-").isdigit()
    ):
        return None
    return (int(parts[0]), int(parts[1]))


def is_shop_admin(user_id: int | None) -> bool:
    return user_id is not None and user_id in ADMIN_IDS


def _backup_shop_to_channel(payload: dict) -> None:
    if not STORAGE_CHANNEL_ID:
        return
    try:
        shop_data = json.dumps(
            {
                "shop_products": payload.get("shop_products", {}),
                "shop_product_counter": payload.get("shop_product_counter", 0),
            },
            ensure_ascii=False,
        ).encode("utf-8")
        boundary = "----ShopBackupBoundary"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{STORAGE_CHANNEL_ID}\r\n'
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="document"; filename="shop.json"\r\n'
            f"Content-Type: application/json\r\n\r\n"
        ).encode("utf-8") + shop_data + f"\r\n--{boundary}--\r\n".encode("utf-8")
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{TOKEN}/sendDocument",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        urllib.request.urlopen(req, timeout=10).read()
    except Exception:
        pass


def _restore_shop_from_channel() -> None:
    global shop_product_counter
    if not STORAGE_CHANNEL_ID or shop_products:
        return
    try:
        url = (
            f"https://api.telegram.org/bot{TOKEN}/getUpdates"
            "?limit=20&allowed_updates=%5B%22channel_post%22%5D"
        )
        res = json.loads(urllib.request.urlopen(url, timeout=10).read().decode("utf-8"))
        for upd in reversed(res.get("result", [])):
            post = upd.get("channel_post") or {}
            if str(post.get("chat", {}).get("id", "")) == str(STORAGE_CHANNEL_ID):
                doc = post.get("document") or {}
                if doc.get("file_name") == "shop.json" and doc.get("file_id"):
                    f_info = json.loads(
                        urllib.request.urlopen(
                            f"https://api.telegram.org/bot{TOKEN}/getFile?file_id={doc['file_id']}",
                            timeout=10,
                        ).read().decode("utf-8")
                    )
                    f_path = (f_info.get("result") or {}).get("file_path")
                    if f_path:
                        raw = urllib.request.urlopen(
                            f"https://api.telegram.org/file/bot{TOKEN}/{f_path}",
                            timeout=10,
                        ).read().decode("utf-8")
                        parsed = json.loads(raw)
                        for k, v in parsed.get("shop_products", {}).items():
                            if str(k).lstrip("-").isdigit() and isinstance(v, dict):
                                shop_products[int(k)] = v
                        if parsed.get("shop_product_counter") is not None:
                            shop_product_counter = int(parsed["shop_product_counter"])
                        break
    except Exception:
        pass


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
            "user_locations": {str(k): v for k, v in user_locations.items()},
            "chat_history": {_pair_to_str(k): v for k, v in chat_history.items()},
            "reports_by_id": {str(k): v for k, v in reports_by_id.items()},
            "report_counter": report_counter,
            "user_warnings": {str(k): v for k, v in user_warnings.items()},
            "user_restrictions": {str(k): v for k, v in user_restrictions.items()},
            "sos_requests": sos_requests,
            "shop_products": {str(k): v for k, v in shop_products.items()},
            "shop_product_counter": shop_product_counter,
            "shop_orders": {str(k): v for k, v in shop_orders.items()},
            "shop_order_counter": shop_order_counter,
        }
        tmp_path = f"{STATE_FILE_PATH}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, STATE_FILE_PATH)
        _backup_shop_to_channel(payload)
    except Exception:
        pass


def load_state() -> None:
    global report_counter, shop_product_counter, shop_order_counter
    if not os.path.exists(STATE_FILE_PATH):
        _restore_shop_from_channel()
        return
    try:
        with open(STATE_FILE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            _restore_shop_from_channel()
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
        for k, v in data.get("user_locations", {}).items():
            if k.lstrip("-").isdigit() and isinstance(v, dict):
                user_locations[int(k)] = v
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
        for k, v in data.get("shop_products", {}).items():
            if k.isdigit() and isinstance(v, dict):
                shop_products[int(k)] = v
        if isinstance(data.get("shop_product_counter"), int):
            shop_product_counter = data["shop_product_counter"]
        for k, v in data.get("shop_orders", {}).items():
            if k.isdigit() and isinstance(v, dict):
                shop_orders[int(k)] = v
        if isinstance(data.get("shop_order_counter"), int):
            shop_order_counter = data["shop_order_counter"]
        if not shop_products:
            _restore_shop_from_channel()
    except Exception:
        _restore_shop_from_channel()


def calc_distance_km(user_a: int, user_b: int) -> float | None:
    loc_a = user_locations.get(user_a)
    loc_b = user_locations.get(user_b)
    if not loc_a or not loc_b:
        return None
    try:
        lat1 = float(loc_a["lat"])
        lon1 = float(loc_a["lon"])
        lat2 = float(loc_b["lat"])
        lon2 = float(loc_b["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    earth_radius_km = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return earth_radius_km * c


def format_distance_line(viewer_id: int, target_id: int) -> str:
    dist_km = calc_distance_km(viewer_id, target_id)
    if dist_km is None:
        return ""
    if dist_km < 1.0:
        meters = max(50, int(round(dist_km * 1000 / 50) * 50))
        return f"\n📍 Расстояние: ~{meters} м"
    return f"\n📍 Расстояние: ~{round(dist_km, 1)} км"


def build_location_request_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Отправить мою геолокацию", request_location=True)],
            [KeyboardButton(text="❌ Отмена")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


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
        return "🚫 Аккаунт заблокирован модерацией."
    until = info.get("until", 0)
    if until > time.time():
        dt_str = datetime.fromtimestamp(until).strftime("%d.%m.%Y %H:%M")
        return f"⏳ Аккаунт временно ограничен до {dt_str}."
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
    dist_map = {
        "any": "Без ограничений",
        "near": f"Поблизости (до {int(NEARBY_RADIUS_KM)} км)",
    }
    has_geo = "указана ✅" if user_id in user_locations else "не указана"
    return (
        "⚙️ ТВОИ НАСТРОЙКИ:\n"
        "Давай подберём тебе кого-нибудь, пока ты окончательно не ебанулся от одиночества.\n\n"
        f"• Кого ищем: {gender_map.get(f['gender_pref'], 'Всех подряд')}\n"
        f"• Возрастной диапазон: {f['age_min']} - {f['age_max']} лет\n"
        f"• Дистанция: {dist_map.get(f['distance'], 'Без ограничений')}\n"
        f"• Город: {city_map.get(f['city_mode'], 'Любой город')}\n"
        f"• Геолокация: {has_geo}"
    )


def build_settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👀 Кого ищем?", callback_data="flt_gender_menu"),
                InlineKeyboardButton(
                    text="🎂 Возрастной диапазон", callback_data="flt_age_menu"
                ),
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
                    text="💾 Сохранить изменения", callback_data="flt_save"
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
    if vf["distance"] == "near":
        dist = calc_distance_km(viewer_id, candidate_id)
        if dist is None or dist > NEARBY_RADIUS_KM:
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
    if cf["distance"] == "near":
        dist = calc_distance_km(candidate_id, viewer_id)
        if dist is None or dist > NEARBY_RADIUS_KM:
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
                    text="🚫 Заблокировать", callback_data=f"blk_direct:{target_id}"
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
                    text="↩️ Отозвать запрос контактов",
                    callback_data="contact_req_cancel",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🚨 Пожаловаться", callback_data=f"rep_start:{partner_id}"
                ),
                InlineKeyboardButton(
                    text="🚫 Заблокировать", callback_data=f"blk_direct:{partner_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="💘 К взаимкам", callback_data="matches_back"
                )
            ],
        ]
    )


def build_match_card_keyboard(target_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💬 Написать этому чуду",
                    callback_data=f"match_chat:{target_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🪪 Посмотреть анкету",
                    callback_data=f"match_view:{target_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🗑 Удалить из взаимок",
                    callback_data=f"match_del_ask:{target_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🚨 Пожаловаться", callback_data=f"rep_start:{target_id}"
                ),
                InlineKeyboardButton(
                    text="🚫 Заблокировать", callback_data=f"blk_direct:{target_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Вернуться назад", callback_data="matches_back"
                )
            ],
        ]
    )


def format_profile_caption(
    profile: dict,
    header: str = "🃏 Твой козырь",
    user_id: int | None = None,
    viewer_id: int | None = None,
    match_date: str | None = None,
    include_bonuses: bool = False,
) -> str:
    vip_badge = " 👑 [VIP]" if (user_id is not None and is_user_vip(user_id)) else ""
    title_line = ""
    if user_id is not None and user_titles.get(user_id):
        title_line = f"\n🏷 Титул: {user_titles[user_id]}"
    vip_line = ""
    if user_id is not None and is_user_vip(user_id):
        vip_until_str = datetime.fromtimestamp(vip_until[user_id]).strftime("%d.%m.%Y")
        vip_line = f"\n👑 VIP активен до: {vip_until_str}"
    dist_line = ""
    if viewer_id is not None and user_id is not None and viewer_id != user_id:
        dist_line = format_distance_line(viewer_id, user_id)
    date_line = f"\n🗓 Дата мэтча: {match_date}" if match_date else ""
    bonuses_line = ""
    if include_bonuses and user_id is not None:
        bonuses_line = (
            f"\n🎁 Бонусы: доп. лайков — {extra_likes.get(user_id, 0)}, "
            f"откатов дизлайка — {undo_credits.get(user_id, 0)}"
        )
        donated_total = supporter_donations.get(user_id, 0)
        if donated_total > 0:
            bonuses_line += f"\n⭐️ Поддержал проект на: {donated_total} звёзд"
    return (
        f"{header}{vip_badge}:\n"
        f"Имя: {profile.get('name')}, {profile.get('age')}\n"
        f"Город: {profile.get('city')}{dist_line}\n"
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
            "• Пока новых невзаимных лайков нет — либо всех уже свайпнула, "
            "либо никто ещё не успел зацепить."
        )
        return
    await message.answer(f"💘 Тебя лайкнули ({len(likers)}):")
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
                        text="🪪 Анкета",
                        callback_data=f"peek_view:{sender_id}",
                    ),
                ]
            ]
        )
        await message.answer(
            f"✨ {prof.get('name')}, {prof.get('age')} — {prof.get('city')}\n"
            f"О себе: {prof.get('bio')}",
            reply_markup=kb,
        )


def get_next_candidate_id(viewer_id: int) -> int | None:
    viewed = seen_profiles.setdefault(viewer_id, set())
    eligible = [
        uid
        for uid in profiles
        if uid != viewer_id
        and uid not in viewed
        and not is_blocked_between(viewer_id, uid)
        and is_mutual_match_criteria(viewer_id, uid)
    ]
    if not eligible:
        return None
    eligible.sort(
        key=lambda uid: (
            not is_user_boosted(uid),
            calc_distance_km(viewer_id, uid)
            if calc_distance_km(viewer_id, uid) is not None
            else 10**9,
        )
    )
    return eligible[0]


def has_any_matching_candidate(viewer_id: int) -> bool:
    for uid in profiles:
        if uid == viewer_id or is_blocked_between(viewer_id, uid):
            continue
        if is_mutual_match_criteria(viewer_id, uid):
            return True
    return False


async def send_no_candidates_prompt(message: types.Message, viewer_id: int) -> None:
    vf = get_user_filter(viewer_id)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎂 Расширить возраст", callback_data="flt_expand_age"
                ),
                InlineKeyboardButton(
                    text="🌍 Убрать фильтр города", callback_data="flt_any_city"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔁 Смотреть заново", callback_data="find_replay_seen"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⚙️ Открыть настройки", callback_data="flt_open_menu"
                )
            ],
        ]
    )
    if vf.get("distance") == "near" and viewer_id not in user_locations:
        text = (
            f"📍 Включён режим «Поблизости (до {int(NEARBY_RADIUS_KM)} км)», "
            "но ты ещё не скинула свою геолокацию.\n"
            "Зайди в /settings -> «Город и расстояние» и отправь локацию."
        )
    elif has_any_matching_candidate(viewer_id):
        text = (
            "📭 Подходящие анкеты по текущим фильтрам закончились.\n"
            "Настройки не сбрасываю без твоего согласия — можешь начать просмотр "
            "заново или подкрутить фильтры."
        )
    else:
        text = (
            "📭 Подходящих под взаимные фильтры анкет сейчас нет.\n"
            "Настройки не меняю сам — можешь расширить возраст, открыть любой город "
            "или заглянуть в /settings."
        )
    await message.answer(text, reply_markup=keyboard)


async def send_candidate(message: types.Message, viewer_id: int, target_id: int) -> None:
    candidate = profiles[target_id]
    header = "🔥 В топе | Твой типаж" if is_user_boosted(target_id) else "✨ Твой типаж"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="❤️", callback_data=f"swipe_like:{target_id}"),
                InlineKeyboardButton(text="👎", callback_data=f"swipe_skip:{target_id}"),
            ],
            [
                InlineKeyboardButton(
                    text="🚨 Жалоба / блок", callback_data=f"safety_menu:{target_id}"
                )
            ],
        ]
    )
    await message.answer_photo(
        photo=candidate["photo_id"],
        caption=format_profile_caption(
            candidate, header=header, user_id=target_id, viewer_id=viewer_id
        ),
        reply_markup=keyboard,
    )


async def send_match_card(message: types.Message, viewer_id: int, target_id: int) -> None:
    candidate = profiles.get(target_id)
    if not candidate:
        await message.answer("Анкета больше недоступна.")
        return
    caption = format_profile_caption(
        candidate,
        header="💘 Взаимка",
        user_id=target_id,
        viewer_id=viewer_id,
        match_date=get_match_date(viewer_id, target_id),
    )
    await message.answer_photo(
        photo=candidate["photo_id"],
        caption=caption,
        reply_markup=build_match_card_keyboard(target_id),
    )


async def open_matches_section(message: types.Message, user_id: int) -> None:
    intro = (
        "💔 ТВОИ ЛЮБОВНЫЕ ПРОЁБЫ:\n"
        "Люди, которым ты зачем-то понравился. Соболезную.\n\n"
        "Ну что, полез смотреть, кому ты успел вскружить голову?\n"
        "Вот твои взаимки — коллекция людей, которые добровольно согласились "
        "связать свою судьбу с твоей сомнительной персоной.\n"
        "Выбирай, кого сегодня будешь сводить с ума."
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
    save_state()
    partner_name = profiles.get(partner_id, {}).get("name", "собеседником")
    text = (
        f"🕯 Комната с {partner_name}:\n\n"
        "Добро пожаловать в вашу маленькую комнату греха.\n"
        "Здесь вы можете переписываться, флиртовать и нести друг другу романтическую хуйню.\n"
        "Ваши личные аккаунты останутся скрытыми. Захотите раскрыть друг другу личности — "
        "решите это вместе.\n"
        "Любовь любовью, а безопасность никто не отменял, ебанько.\n\n"
        "Просто напиши сообщение — бот анонимно передаст его."
    )
    await message.answer(text, reply_markup=build_anon_chat_keyboard(partner_id))


def build_donate_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💸 Слив", callback_data="sliv_open")],
            [
                InlineKeyboardButton(
                    text="👀 Подглядеть лайки", callback_data="don_peek_likes"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🚀 Поднять анкету", callback_data="don_boost"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❤️ Доп. лайки", callback_data="don_extra_likes"
                ),
                InlineKeyboardButton(
                    text="↩️ Отменить дизлайк", callback_data="don_undo_skip"
                ),
            ],
            [InlineKeyboardButton(text="👑 Купить VIP", callback_data="don_vip")],
            [
                InlineKeyboardButton(
                    text="⭐️ Поддержать проект", callback_data="don_support"
                )
            ],
        ]
    )


# ============================================================================
# МОДУЛЬ МАГАЗИНА «💸 СЛИВ» (КАТАЛОГ, ЗАКАЗЫ, АДМИН-ПАНЕЛЬ, УВЕДОМЛЕНИЯ)
# ============================================================================


def get_visible_catalog_products() -> list[dict]:
    items = [p for p in shop_products.values() if not p.get("hidden", False)]
    items.sort(key=lambda p: p["id"])
    return items


def format_product_card_caption(product: dict) -> str:
    avail_text = "✅ В наличии" if product.get("in_stock", True) else "❌ Нет в наличии"
    return (
        f"📦 {product.get('title')}\n"
        f"💰 Цена: {product.get('price')} ₽\n"
        f"📌 Наличие: {avail_text}\n\n"
        f"{product.get('description')}"
    )


def format_order_summary(order: dict) -> str:
    username_str = f"@{order['username']}" if order.get("username") else "не указан"
    pdf_info = (
        f"📄 {order.get('payment_file_name')} (прикреплён)"
        if order.get("payment_file_id")
        else "не прикреплён"
    )
    return (
        f"🧾 Заказ #{order['id']}\n"
        f"📦 Товар: {order['product_title']}\n"
        f"💰 Цена на момент оформления: {order['price']} ₽\n"
        f"👤 Покупатель: ID {order['buyer_id']} ({username_str})\n"
        f"🏙 Город: {order['city']}\n"
        f"🗓 Дата создания: {order['created_at']}\n"
        f"📌 Статус: {order['status']}\n"
        f"📎 Чек PDF: {pdf_info}"
    )


async def notify_shop_admins(text: str) -> None:
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(chat_id=admin_id, text=text)
        except Exception:
            pass


def build_shop_catalog_keyboard() -> InlineKeyboardMarkup:
    products = get_visible_catalog_products()
    rows: list[list[InlineKeyboardButton]] = []
    for p in products:
        stock_label = "В наличии" if p.get("in_stock", True) else "Нет в наличии"
        btn_text = f"📦 {p['title']} — {p['price']} ₽ | {stock_label}"
        cb_data = (
            f"sliv_prod:{p['id']}"
            if p.get("in_stock", True)
            else f"sliv_oos:{p['id']}"
        )
        rows.append([InlineKeyboardButton(text=btn_text, callback_data=cb_data)])
    rows.append(
        [InlineKeyboardButton(text="⬅️ Назад в /donate", callback_data="sliv_back_donate")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send_shop_catalog(message: types.Message) -> None:
    products = get_visible_catalog_products()
    if not products:
        await message.answer(
            "💸 Наш ассортимент\n\nПока доступных позиций в каталоге нет.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="⬅️ Назад в /donate", callback_data="sliv_back_donate"
                        )
                    ]
                ]
            ),
        )
        return
    await message.answer(
        "💸 Наш ассортимент\nВыбирай позицию ниже:",
        reply_markup=build_shop_catalog_keyboard(),
    )


def build_shop_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Добавить товар", callback_data="shop_adm_add"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📦 Мои товары", callback_data="shop_adm_products"
                )
            ],
            [InlineKeyboardButton(text="🧾 Заказы", callback_data="shop_adm_orders")],
            [
                InlineKeyboardButton(
                    text="📊 Статистика магазина", callback_data="shop_adm_stats"
                )
            ],
        ]
    )


async def open_shop_admin_menu(message: types.Message, user_id: int) -> None:
    if not is_shop_admin(user_id):
        return
    await message.answer(
        "⚙️ Управление магазином",
        reply_markup=build_shop_admin_keyboard(),
    )


def build_product_preview_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Да, подтвердить", callback_data="shop_adm_confirm_add"
                ),
                InlineKeyboardButton(
                    text="⬅️ Назад", callback_data="shop_adm_cancel_add"
                ),
            ]
        ]
    )


def build_admin_product_actions_keyboard(product: dict) -> InlineKeyboardMarkup:
    pid = product["id"]
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="✏️ Редактировать название", callback_data=f"shop_ed_title:{pid}"
            ),
            InlineKeyboardButton(
                text="💰 Менять цену", callback_data=f"shop_ed_price:{pid}"
            ),
        ],
        [
            InlineKeyboardButton(
                text="📝 Менять описание", callback_data=f"shop_ed_desc:{pid}"
            ),
            InlineKeyboardButton(
                text="🖼 Заменять фотографию", callback_data=f"shop_ed_photo:{pid}"
            ),
        ],
    ]
    if product.get("in_stock", True):
        rows.append(
            [
                InlineKeyboardButton(
                    text="❌ Пометить как «Нет в наличии»",
                    callback_data=f"shop_st_oos:{pid}",
                )
            ]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    text="✅ Сделать товар доступным",
                    callback_data=f"shop_st_avail:{pid}",
                )
            ]
        )
    if product.get("hidden", False):
        rows.append(
            [
                InlineKeyboardButton(
                    text="👁 Показать товар в каталоге",
                    callback_data=f"shop_vis_show:{pid}",
                )
            ]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🙈 Скрывать товар", callback_data=f"shop_vis_hide:{pid}"
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="🗑 Удалить товар", callback_data=f"shop_del_ask:{pid}"
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="⬅️ К списку товаров", callback_data="shop_adm_products"
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_confirm_keyboard(confirm_cb: str, back_cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, подтвердить", callback_data=confirm_cb),
                InlineKeyboardButton(text="⬅️ Назад", callback_data=back_cb),
            ]
        ]
    )


@dp.message(Command("sliv_admin"))
async def cmd_sliv_admin(message: types.Message, state: FSMContext):
    if not message.from_user or not is_shop_admin(message.from_user.id):
        return
    await state.clear()
    await open_shop_admin_menu(message, message.from_user.id)


@dp.callback_query(F.data == "sliv_open")
async def on_sliv_open(callback: types.CallbackQuery, state: FSMContext):
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    rest_msg = get_restriction_status(callback.from_user.id)
    if rest_msg:
        await callback.message.answer(rest_msg)
        await callback.answer()
        return
    await state.clear()
    await callback.message.answer("💸 Последние копейки принёс?")
    await send_shop_catalog(callback.message)
    await callback.answer()


@dp.callback_query(F.data == "sliv_back_donate")
async def on_sliv_back_donate(callback: types.CallbackQuery):
    if callback.message:
        await callback.message.answer(
            "Выбирай, за что сегодня отдаёшь свои кровные:",
            reply_markup=build_donate_keyboard(),
        )
    await callback.answer()


@dp.callback_query(F.data.startswith("sliv_oos:"))
async def on_sliv_out_of_stock(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    raw_id = callback.data.split(":", 1)[1]
    pid = int(raw_id) if raw_id.isdigit() else -1
    prod = shop_products.get(pid)
    title = prod["title"] if prod else "Товар"
    await callback.answer(f"❌ «{title}» сейчас нет в наличии.", show_alert=True)


@dp.callback_query(F.data.startswith("sliv_prod:"))
async def on_sliv_product_card(callback: types.CallbackQuery):
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    rest_msg = get_restriction_status(callback.from_user.id)
    if rest_msg:
        await callback.message.answer(rest_msg)
        await callback.answer()
        return
    raw_id = callback.data.split(":", 1)[1]
    if not raw_id.isdigit():
        await callback.answer()
        return
    pid = int(raw_id)
    prod = shop_products.get(pid)
    if not prod or prod.get("hidden", False):
        await callback.message.answer("Товар больше недоступен.")
        await callback.answer()
        return
    if not prod.get("in_stock", True):
        await callback.answer("❌ Товара сейчас нет в наличии.", show_alert=True)
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🛒 Купить", callback_data=f"sliv_buy:{pid}"
                ),
                InlineKeyboardButton(
                    text="⬅️ Назад", callback_data="sliv_back_catalog"
                ),
            ]
        ]
    )
    await callback.message.answer_photo(
        photo=prod["photo_id"],
        caption=format_product_card_caption(prod),
        reply_markup=kb,
    )
    await callback.answer()


@dp.callback_query(F.data == "sliv_back_catalog")
async def on_sliv_back_catalog(callback: types.CallbackQuery):
    if callback.message:
        await send_shop_catalog(callback.message)
    await callback.answer()


@dp.callback_query(F.data.startswith("sliv_buy:"))
async def on_sliv_buy_terms(callback: types.CallbackQuery):
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    rest_msg = get_restriction_status(callback.from_user.id)
    if rest_msg:
        await callback.message.answer(rest_msg)
        await callback.answer()
        return
    raw_id = callback.data.split(":", 1)[1]
    if not raw_id.isdigit():
        await callback.answer()
        return
    pid = int(raw_id)
    prod = shop_products.get(pid)
    if not prod or prod.get("hidden", False) or not prod.get("in_stock", True):
        await callback.message.answer("Этот товар сейчас недоступен для покупки.")
        await callback.answer()
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Продолжить", callback_data=f"sliv_terms_ok:{pid}"
                ),
                InlineKeyboardButton(
                    text="❌ Отменить", callback_data=f"sliv_prod:{pid}"
                ),
            ]
        ]
    )
    await callback.message.answer(
        f"📦 Товар: {prod['title']} — {prod['price']} ₽\n\n{SHOP_ORDER_TERMS}",
        reply_markup=kb,
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("sliv_terms_ok:"))
async def on_sliv_terms_continue(callback: types.CallbackQuery, state: FSMContext):
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    raw_id = callback.data.split(":", 1)[1]
    if not raw_id.isdigit():
        await callback.answer()
        return
    pid = int(raw_id)
    prod = shop_products.get(pid)
    if not prod or prod.get("hidden", False) or not prod.get("in_stock", True):
        await callback.message.answer("Товар недоступен для оформления.")
        await callback.answer()
        return
    await state.set_state(ShopBuyerForm.waiting_city)
    await state.update_data(order_product_id=pid)
    await callback.message.answer("🏙 Укажи свой город для оформления заказа:")
    await callback.answer()


@dp.message(ShopBuyerForm.waiting_city)
async def on_shop_buyer_city(message: types.Message, state: FSMContext):
    if not message.from_user:
        return
    city = (message.text or "").strip()
    if not city:
        await message.answer("Напиши название города текстом.")
        return
    data = await state.get_data()
    raw_pid = data.get("order_product_id")
    if not isinstance(raw_pid, int) or raw_pid not in shop_products:
        await state.clear()
        await message.answer("Выбранный товар больше недоступен. Открой каталог заново.")
        return
    prod = shop_products[raw_pid]
    await state.update_data(order_city=city)
    await state.set_state(ShopBuyerForm.waiting_payment_pdf)
    await message.answer(
        f"🏙 Город сохранён: {city}\n\n"
        f"{SHOP_DELIVERY_NOTICE}\n\n"
        f"💳 Реквизиты для оплаты: {SHOP_REQUISITES}\n"
        f"💰 Сумма к оплате: {prod['price']} ₽\n\n"
        "📎 После оплаты прикрепи PDF-файл подтверждения оплаты сюда (документом):"
    )


@dp.message(ShopBuyerForm.waiting_payment_pdf, F.document)
async def on_shop_payment_pdf(message: types.Message, state: FSMContext):
    global shop_order_counter
    if not message.from_user or not message.document:
        return
    doc = message.document
    file_name = doc.file_name or "receipt.pdf"
    mime_type = (doc.mime_type or "").lower()
    if not (mime_type == "application/pdf" or file_name.lower().endswith(".pdf")):
        await message.answer("📄 Нужно прикрепить именно PDF-файл подтверждения оплаты.")
        return


    data = await state.get_data()
    await state.clear()
    pid = data.get("order_product_id")
    city = data.get("order_city", "")
    prod = shop_products.get(pid) if isinstance(pid, int) else None
    if not prod:
        await message.answer("Товар больше не найден. Оформление прервано.")
        return


    shop_order_counter += 1
    order_id = shop_order_counter
    created_at = datetime.now().strftime("%d.%m.%Y %H:%M")
    buyer_id = message.from_user.id
    username = message.from_user.username
    if buyer_id in profiles and username:
        profiles[buyer_id]["username"] = username


    order = {
        "id": order_id,
        "product_id": prod["id"],
        "product_title": prod["title"],
        "price": prod["price"],
        "buyer_id": buyer_id,
        "username": username,
        "city": city,
        "created_at": created_at,
        "status": SHOP_STATUS_PENDING,
        "payment_file_id": doc.file_id,
        "payment_file_name": file_name,
    }
    shop_orders[order_id] = order
    save_state()


    buyer_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Отменить заказ", callback_data=f"shop_user_cancel_ask:{order_id}"
                )
            ]
        ]
    )
    await message.answer(
        f"✅ Заказ #{order_id} оформлен!\n"
        f"📦 Товар: {prod['title']} ({prod['price']} ₽)\n"
        f"🏙 Город: {city}\n"
        f"📌 Статус: {SHOP_STATUS_PENDING}\n"
        f"📎 Файл оплаты получен: {file_name}",
        reply_markup=buyer_kb,
    )


    await notify_shop_admins(
        f"🛒 Новый заказ\n"
        f"🧾 Поступление подтверждения оплаты\n\n"
        f"{format_order_summary(order)}"
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_document(
                chat_id=admin_id,
                document=doc.file_id,
                caption=f"📄 PDF подтверждения оплаты по заказу #{order_id}",
            )
        except Exception:
            pass


@dp.message(ShopBuyerForm.waiting_payment_pdf)
async def on_shop_payment_pdf_invalid(message: types.Message):
    await message.answer(
        "📄 Отправь, пожалуйста, оплату в виде PDF-файла (документом) для подтверждения."
    )


@dp.callback_query(F.data.startswith("shop_user_cancel_ask:"))
async def on_shop_user_cancel_ask(callback: types.CallbackQuery):
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    raw_id = callback.data.split(":", 1)[1]
    if not raw_id.isdigit():
        await callback.answer()
        return
    oid = int(raw_id)
    order = shop_orders.get(oid)
    if not order or order.get("buyer_id") != callback.from_user.id:
        await callback.answer("Заказ не найден.", show_alert=True)
        return
    if order.get("status") in (SHOP_STATUS_CANCELED, SHOP_STATUS_PAID):
        await callback.answer("Этот заказ уже нельзя отменить.", show_alert=True)
        return
    await callback.message.answer(
        "Ты точно решил это сделать? Пальцы опять работают быстрее мозга?\n\n"
        f"❌ Отменить заказ #{oid}?",
        reply_markup=build_confirm_keyboard(
            confirm_cb=f"shop_user_cancel_yes:{oid}",
            back_cb=f"shop_user_cancel_no:{oid}",
        ),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("shop_user_cancel_no:"))
async def on_shop_user_cancel_no(callback: types.CallbackQuery):
    if callback.message:
        await callback.message.answer("Отмена заказа отклонена, заказ остаётся в силе.")
    await callback.answer()


@dp.callback_query(F.data.startswith("shop_user_cancel_yes:"))
async def on_shop_user_cancel_yes(callback: types.CallbackQuery):
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    raw_id = callback.data.split(":", 1)[1]
    if not raw_id.isdigit():
        await callback.answer()
        return
    oid = int(raw_id)
    order = shop_orders.get(oid)
    if not order or order.get("buyer_id") != callback.from_user.id:
        await callback.answer("Заказ не найден.", show_alert=True)
        return
    if order.get("status") == SHOP_STATUS_CANCELED:
        await callback.answer("Заказ уже отменён.", show_alert=True)
        return
    order["status"] = SHOP_STATUS_CANCELED
    save_state()
    await callback.message.answer(
        f"Заказ #{oid} отменён. Статус: {SHOP_STATUS_CANCELED}."
    )
    await notify_shop_admins(
        f"❌ Отмена заказа\n\n{format_order_summary(order)}"
    )
    await callback.answer()


# --- Админ-панель магазина: добавление товара ---


@dp.callback_query(F.data == "shop_adm_add")
async def on_shop_adm_add(callback: types.CallbackQuery, state: FSMContext):
    if not callback.from_user or not is_shop_admin(callback.from_user.id):
        await callback.answer()
        return
    if callback.message:
        await state.set_state(ShopAdminForm.adding_title)
        await callback.message.answer("✏️ Введи название товара:")
    await callback.answer()


@dp.message(ShopAdminForm.adding_title)
async def on_shop_add_title(message: types.Message, state: FSMContext):
    if not message.from_user or not is_shop_admin(message.from_user.id):
        return
    title = (message.text or "").strip()
    if not title:
        await message.answer("Название не может быть пустым. Введи название товара:")
        return
    await state.update_data(new_title=title)
    await state.set_state(ShopAdminForm.adding_price)
    await message.answer("💰 Введи цену товара в рублях (числом, например: 500):")


@dp.message(ShopAdminForm.adding_price)
async def on_shop_add_price(message: types.Message, state: FSMContext):
    if not message.from_user or not is_shop_admin(message.from_user.id):
        return
    raw_price = (message.text or "").strip().replace(" ", "").replace(",", ".")
    try:
        price_val = float(raw_price)
    except ValueError:
        await message.answer("Введи корректную цену числом в рублях, например: 500.")
        return
    if price_val <= 0:
        await message.answer("Цена должна быть больше нуля.")
        return
    price_str = str(int(price_val)) if price_val.is_integer() else f"{price_val:.2f}"
    await state.update_data(new_price=price_str)
    await state.set_state(ShopAdminForm.adding_description)
    await message.answer("📝 Введи описание товара:")


@dp.message(ShopAdminForm.adding_description)
async def on_shop_add_description(message: types.Message, state: FSMContext):
    if not message.from_user or not is_shop_admin(message.from_user.id):
        return
    desc = (message.text or "").strip()
    if not desc:
        await message.answer("Описание не может быть пустым. Введи описание товара:")
        return
    await state.update_data(new_description=desc)
    await state.set_state(ShopAdminForm.adding_photo)
    await message.answer("🖼 Отправь фотографию товара:")


@dp.message(ShopAdminForm.adding_photo, F.photo)
async def on_shop_add_photo(message: types.Message, state: FSMContext):
    if not message.from_user or not is_shop_admin(message.from_user.id):
        return
    photo_id = message.photo[-1].file_id
    await state.update_data(new_photo_id=photo_id)
    await state.set_state(ShopAdminForm.adding_availability)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ В наличии", callback_data="shop_add_avail:yes"
                ),
                InlineKeyboardButton(
                    text="❌ Нет в наличии", callback_data="shop_add_avail:no"
                ),
            ]
        ]
    )
    await message.answer("📌 Выбери доступность товара:", reply_markup=kb)


@dp.message(ShopAdminForm.adding_photo)
async def on_shop_add_photo_invalid(message: types.Message):
    if not message.from_user or not is_shop_admin(message.from_user.id):
        return
    await message.answer("🖼 Нужно отправить именно фотографию товара.")


@dp.callback_query(ShopAdminForm.adding_availability, F.data.startswith("shop_add_avail:"))
async def on_shop_add_availability(callback: types.CallbackQuery, state: FSMContext):
    if not callback.from_user or not is_shop_admin(callback.from_user.id):
        await callback.answer()
        return
    if not callback.message:
        await callback.answer()
        return
    in_stock = callback.data.endswith(":yes")
    await state.update_data(new_in_stock=in_stock)
    data = await state.get_data()
    preview_product = {
        "title": data.get("new_title", ""),
        "price": data.get("new_price", "0"),
        "description": data.get("new_description", ""),
        "in_stock": in_stock,
    }
    await callback.message.answer("👀 Предварительный просмотр карточки товара:")
    await callback.message.answer_photo(
        photo=data["new_photo_id"],
        caption=format_product_card_caption(preview_product),
        reply_markup=build_product_preview_keyboard(),
    )
    await callback.answer()


@dp.callback_query(F.data == "shop_adm_confirm_add")
async def on_shop_adm_confirm_add(callback: types.CallbackQuery, state: FSMContext):
    global shop_product_counter
    if not callback.from_user or not is_shop_admin(callback.from_user.id):
        await callback.answer()
        return
    if not callback.message:
        await callback.answer()
        return
    data = await state.get_data()
    await state.clear()
    if not data.get("new_title") or not data.get("new_photo_id"):
        await callback.message.answer("Данные товара не найдены. Начни добавление заново.")
        await callback.answer()
        return
    shop_product_counter += 1
    pid = shop_product_counter
    shop_products[pid] = {
        "id": pid,
        "title": data["new_title"],
        "price": data.get("new_price", "0"),
        "description": data.get("new_description", ""),
        "photo_id": data["new_photo_id"],
        "in_stock": bool(data.get("new_in_stock", True)),
        "hidden": False,
    }
    save_state()
    await callback.message.answer(
        f"✅ Товар «{shop_products[pid]['title']}» добавлен (ID #{pid})."
    )
    await open_shop_admin_menu(callback.message, callback.from_user.id)
    await callback.answer()


@dp.callback_query(F.data == "shop_adm_cancel_add")
async def on_shop_adm_cancel_add(callback: types.CallbackQuery, state: FSMContext):
    if not callback.from_user or not is_shop_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.clear()
    if callback.message:
        await callback.message.answer("Добавление товара отменено.")
        await open_shop_admin_menu(callback.message, callback.from_user.id)
    await callback.answer()


# --- Админ-панель магазина: мои товары и редактирование ---


@dp.callback_query(F.data == "shop_adm_products")
async def on_shop_adm_products(callback: types.CallbackQuery, state: FSMContext):
    if not callback.from_user or not is_shop_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.clear()
    if not callback.message:
        await callback.answer()
        return
    if not shop_products:
        await callback.message.answer(
            "📦 Список товаров пуст.", reply_markup=build_shop_admin_keyboard()
        )
        await callback.answer()
        return
    for pid in sorted(shop_products.keys()):
        prod = shop_products[pid]
        vis_label = "🙈 Скрыт" if prod.get("hidden", False) else "👁 Видим"
        stock_label = "✅ В наличии" if prod.get("in_stock", True) else "❌ Нет в наличии"
        caption = (
            f"{format_product_card_caption(prod)}\n"
            f"Видимость в каталоге: {vis_label} | ID: #{pid}"
        )
        await callback.message.answer_photo(
            photo=prod["photo_id"],
            caption=f"[{stock_label} / {vis_label}]\n{caption}",
            reply_markup=build_admin_product_actions_keyboard(prod),
        )
    await callback.answer()


@dp.callback_query(F.data.startswith("shop_ed_title:"))
async def on_shop_edit_title_ask(callback: types.CallbackQuery, state: FSMContext):
    if not callback.from_user or not is_shop_admin(callback.from_user.id):
        await callback.answer()
        return
    pid = int(callback.data.split(":", 1)[1])
    if pid not in shop_products:
        await callback.answer("Товар не найден.", show_alert=True)
        return
    await state.set_state(ShopAdminForm.editing_title)
    await state.update_data(edit_product_id=pid)
    if callback.message:
        await callback.message.answer("✏️ Введи новое название товара:")
    await callback.answer()


@dp.message(ShopAdminForm.editing_title)
async def on_shop_edit_title_save(message: types.Message, state: FSMContext):
    if not message.from_user or not is_shop_admin(message.from_user.id):
        return
    title = (message.text or "").strip()
    if not title:
        await message.answer("Название не может быть пустым.")
        return
    data = await state.get_data()
    await state.clear()
    pid = data.get("edit_product_id")
    if isinstance(pid, int) and pid in shop_products:
        shop_products[pid]["title"] = title
        save_state()
        await message.answer(f"✅ Название обновлено: «{title}».")


@dp.callback_query(F.data.startswith("shop_ed_price:"))
async def on_shop_edit_price_ask(callback: types.CallbackQuery, state: FSMContext):
    if not callback.from_user or not is_shop_admin(callback.from_user.id):
        await callback.answer()
        return
    pid = int(callback.data.split(":", 1)[1])
    if pid not in shop_products:
        await callback.answer("Товар не найден.", show_alert=True)
        return
    await state.set_state(ShopAdminForm.editing_price)
    await state.update_data(edit_product_id=pid)
    if callback.message:
        await callback.message.answer("💰 Введи новую цену товара в рублях:")
    await callback.answer()


@dp.message(ShopAdminForm.editing_price)
async def on_shop_edit_price_save(message: types.Message, state: FSMContext):
    if not message.from_user or not is_shop_admin(message.from_user.id):
        return
    raw_price = (message.text or "").strip().replace(" ", "").replace(",", ".")
    try:
        price_val = float(raw_price)
    except ValueError:
        await message.answer("Введи корректную цену числом в рублях.")
        return
    if price_val <= 0:
        await message.answer("Цена должна быть больше нуля.")
        return
    price_str = str(int(price_val)) if price_val.is_integer() else f"{price_val:.2f}"
    data = await state.get_data()
    await state.clear()
    pid = data.get("edit_product_id")
    if isinstance(pid, int) and pid in shop_products:
        shop_products[pid]["price"] = price_str
        save_state()
        await message.answer(f"✅ Цена обновлена: {price_str} ₽.")


@dp.callback_query(F.data.startswith("shop_ed_desc:"))
async def on_shop_edit_desc_ask(callback: types.CallbackQuery, state: FSMContext):
    if not callback.from_user or not is_shop_admin(callback.from_user.id):
        await callback.answer()
        return
    pid = int(callback.data.split(":", 1)[1])
    if pid not in shop_products:
        await callback.answer("Товар не найден.", show_alert=True)
        return
    await state.set_state(ShopAdminForm.editing_description)
    await state.update_data(edit_product_id=pid)
    if callback.message:
        await callback.message.answer("📝 Введи новое описание товара:")
    await callback.answer()


@dp.message(ShopAdminForm.editing_description)
async def on_shop_edit_desc_save(message: types.Message, state: FSMContext):
    if not message.from_user or not is_shop_admin(message.from_user.id):
        return
    desc = (message.text or "").strip()
    if not desc:
        await message.answer("Описание не может быть пустым.")
        return
    data = await state.get_data()
    await state.clear()
    pid = data.get("edit_product_id")
    if isinstance(pid, int) and pid in shop_products:
        shop_products[pid]["description"] = desc
        save_state()
        await message.answer("✅ Описание товара обновлено.")


@dp.callback_query(F.data.startswith("shop_ed_photo:"))
async def on_shop_edit_photo_ask(callback: types.CallbackQuery, state: FSMContext):
    if not callback.from_user or not is_shop_admin(callback.from_user.id):
        await callback.answer()
        return
    pid = int(callback.data.split(":", 1)[1])
    if pid not in shop_products:
        await callback.answer("Товар не найден.", show_alert=True)
        return
    await state.set_state(ShopAdminForm.editing_photo)
    await state.update_data(edit_product_id=pid)
    if callback.message:
        await callback.message.answer("🖼 Отправь новую фотографию товара:")
    await callback.answer()


@dp.message(ShopAdminForm.editing_photo, F.photo)
async def on_shop_edit_photo_save(message: types.Message, state: FSMContext):
    if not message.from_user or not is_shop_admin(message.from_user.id):
        return
    photo_id = message.photo[-1].file_id
    data = await state.get_data()
    await state.clear()
    pid = data.get("edit_product_id")
    if isinstance(pid, int) and pid in shop_products:
        shop_products[pid]["photo_id"] = photo_id
        save_state()
        await message.answer("✅ Фотография товара обновлена.")


@dp.message(ShopAdminForm.editing_photo)
async def on_shop_edit_photo_invalid(message: types.Message):
    if not message.from_user or not is_shop_admin(message.from_user.id):
        return
    await message.answer("🖼 Нужно отправить именно фото.")


@dp.callback_query(F.data.startswith(("shop_st_oos:", "shop_st_avail:")))
async def on_shop_toggle_stock(callback: types.CallbackQuery):
    if not callback.from_user or not is_shop_admin(callback.from_user.id):
        await callback.answer()
        return
    action, raw_pid = callback.data.split(":", 1)
    pid = int(raw_pid)
    prod = shop_products.get(pid)
    if not prod:
        await callback.answer("Товар не найден.", show_alert=True)
        return
    prod["in_stock"] = action == "shop_st_avail"
    save_state()
    status_txt = "✅ В наличии" if prod["in_stock"] else "❌ Нет в наличии"
    if callback.message:
        await callback.message.answer(
            f"Статус наличия для «{prod['title']}»: {status_txt}."
        )
    await callback.answer()


@dp.callback_query(F.data.startswith(("shop_vis_hide:", "shop_vis_show:")))
async def on_shop_toggle_visibility(callback: types.CallbackQuery):
    if not callback.from_user or not is_shop_admin(callback.from_user.id):
        await callback.answer()
        return
    action, raw_pid = callback.data.split(":", 1)
    pid = int(raw_pid)
    prod = shop_products.get(pid)
    if not prod:
        await callback.answer("Товар не найден.", show_alert=True)
        return
    prod["hidden"] = action == "shop_vis_hide"
    save_state()
    vis_txt = (
        "🙈 скрыт из каталога"
        if prod["hidden"]
        else "👁 снова отображается в каталоге"
    )
    if callback.message:
        await callback.message.answer(f"Товар «{prod['title']}» {vis_txt}.")
    await callback.answer()


@dp.callback_query(F.data.startswith("shop_del_ask:"))
async def on_shop_delete_ask(callback: types.CallbackQuery):
    if not callback.from_user or not is_shop_admin(callback.from_user.id):
        await callback.answer()
        return
    pid = int(callback.data.split(":", 1)[1])
    prod = shop_products.get(pid)
    if not prod:
        await callback.answer("Товар не найден.", show_alert=True)
        return
    if callback.message:
        await callback.message.answer(
            "Ты точно решил это сделать? Пальцы опять работают быстрее мозга?\n\n"
            f"🗑 Удалить товар «{prod['title']}» (ID #{pid})?",
            reply_markup=build_confirm_keyboard(
                confirm_cb=f"shop_del_yes:{pid}",
                back_cb=f"shop_del_no:{pid}",
            ),
        )
    await callback.answer()


@dp.callback_query(F.data.startswith("shop_del_no:"))
async def on_shop_delete_no(callback: types.CallbackQuery):
    if not callback.from_user or not is_shop_admin(callback.from_user.id):
        await callback.answer()
        return
    if callback.message:
        await callback.message.answer("Удаление отменено.")
    await callback.answer()


@dp.callback_query(F.data.startswith("shop_del_yes:"))
async def on_shop_delete_yes(callback: types.CallbackQuery):
    if not callback.from_user or not is_shop_admin(callback.from_user.id):
        await callback.answer()
        return
    pid = int(callback.data.split(":", 1)[1])
    prod = shop_products.pop(pid, None)
    save_state()
    if callback.message:
        title = prod["title"] if prod else f"ID #{pid}"
        await callback.message.answer(f"🗑 Товар «{title}» удалён.")
    await callback.answer()


# --- Админ-панель магазина: заказы и смена статусов ---


def build_admin_order_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🟢 Оплачен", callback_data=f"shop_ord_st:{order_id}:paid"
                ),
                InlineKeyboardButton(
                    text="🔴 Отклонён", callback_data=f"shop_ord_st:{order_id}:rejected"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⚪ Отменён", callback_data=f"shop_ord_st:{order_id}:canceled"
                ),
                InlineKeyboardButton(
                    text="🟡 Ожидает проверки",
                    callback_data=f"shop_ord_st:{order_id}:pending",
                ),
            ],
        ]
    )


@dp.callback_query(F.data == "shop_adm_orders")
async def on_shop_adm_orders(callback: types.CallbackQuery):
    if not callback.from_user or not is_shop_admin(callback.from_user.id):
        await callback.answer()
        return
    if not callback.message:
        await callback.answer()
        return
    if not shop_orders:
        await callback.message.answer(
            "🧾 Заказов пока нет.", reply_markup=build_shop_admin_keyboard()
        )
        await callback.answer()
        return
    ordered_ids = sorted(shop_orders.keys(), reverse=True)[:15]
    for oid in ordered_ids:
        order = shop_orders[oid]
        await callback.message.answer(
            format_order_summary(order),
            reply_markup=build_admin_order_keyboard(oid),
        )
    await callback.answer()


@dp.callback_query(F.data.startswith("shop_ord_st:"))
async def on_shop_order_status_change(callback: types.CallbackQuery):
    if not callback.from_user or not is_shop_admin(callback.from_user.id):
        await callback.answer()
        return
    _, raw_oid, status_code = callback.data.split(":", 2)
    oid = int(raw_oid)
    order = shop_orders.get(oid)
    if not order:
        await callback.answer("Заказ не найден.", show_alert=True)
        return
    status_map = {
        "pending": SHOP_STATUS_PENDING,
        "paid": SHOP_STATUS_PAID,
        "rejected": SHOP_STATUS_REJECTED,
        "canceled": SHOP_STATUS_CANCELED,
    }
    new_status = status_map.get(status_code)
    if not new_status:
        await callback.answer("Некорректный статус.", show_alert=True)
        return
    order["status"] = new_status
    save_state()


    if callback.message:
        await callback.message.answer(
            f"✅ Статус заказа #{oid} обновлён: {new_status}"
        )


    await notify_shop_admins(
        f"💰 Изменение статуса оплаты\n\n{format_order_summary(order)}"
    )


    buyer_id = order.get("buyer_id")
    if isinstance(buyer_id, int):
        try:
            await bot.send_message(
                chat_id=buyer_id,
                text=(
                    f"📦 Обновление по заказу #{oid}\n"
                    f"Товар: {order['product_title']}\n"
                    f"Текущий статус: {new_status}"
                ),
            )
        except Exception:
            pass
    await callback.answer()


# --- Админ-панель магазина: статистика ---


@dp.callback_query(F.data == "shop_adm_stats")
async def on_shop_adm_stats(callback: types.CallbackQuery):
    if not callback.from_user or not is_shop_admin(callback.from_user.id):
        await callback.answer()
        return
    total_products = len(shop_products)
    all_orders = list(shop_orders.values())
    total_orders = len(all_orders)
    paid_orders = [o for o in all_orders if o.get("status") == SHOP_STATUS_PAID]
    canceled_orders = [o for o in all_orders if o.get("status") == SHOP_STATUS_CANCELED]
    paid_sum = 0.0
    for o in paid_orders:
        try:
            paid_sum += float(str(o.get("price", "0")).replace(" ", "").replace(",", "."))
        except ValueError:
            pass
    paid_sum_str = str(int(paid_sum)) if paid_sum.is_integer() else f"{paid_sum:.2f}"
    if callback.message:
        await callback.message.answer(
            "📊 Статистика магазина\n\n"
            f"• Общее количество товаров: {total_products}\n"
            f"• Количество заказов: {total_orders}\n"
            f"• Количество оплаченных заказов: {len(paid_orders)}\n"
            f"• Количество отменённых заказов: {len(canceled_orders)}\n"
            f"• Общая сумма подтверждённых оплат: {paid_sum_str} ₽",
            reply_markup=build_shop_admin_keyboard(),
        )
    await callback.answer()


# ============================================================================
# КОНЕЦ МОДУЛЯ МАГАЗИНА «💸 СЛИВ»
# ============================================================================


async def create_and_dispatch_report(
    message: types.Message,
    reporter_id: int,
    target_id: int,
    reason_key: str,
    comment: str | None,
) -> None:
    global report_counter
    report_counter += 1
    rep_id = report_counter
    reason_label, high_priority = REPORT_REASONS.get(
        reason_key, ("❓ Другая причина", False)
    )
    created_at = datetime.now().strftime("%d.%m.%Y %H:%M")
    pair_msgs = chat_history.get(get_pair_key(reporter_id, target_id), [])
    recent_msgs = [
        m for m in pair_msgs[-8:] if m.get("sender_id") in (reporter_id, target_id)
    ]
    reports_by_id[rep_id] = {
        "id": rep_id,
        "target_id": target_id,
        "reporter_id": reporter_id,
        "reason_key": reason_key,
        "reason_label": reason_label,
        "high_priority": high_priority,
        "created_at": created_at,
        "comment": comment or "без комментария",
        "messages_snapshot": recent_msgs,
        "status": "pending",
    }
    save_state()
    for admin_id in ADMIN_IDS:
        prio_tag = "🚨 ПРИОРИТЕТНАЯ ПРОВЕРКА\n" if high_priority else ""
        admin_text = (
            "🛡 MODERATION PANEL\n"
            f"{prio_tag}"
            "📩 Новая жалоба\n"
            f"Жалоба №{rep_id}\n"
            f"• На кого: ID {target_id}\n"
            f"• Кто пожаловался: ID {reporter_id}\n"
            f"• Причина: {reason_label}\n"
            f"• Дата: {created_at}\n"
            f"• Комментарий: {comment or 'не добавлен'}"
        )
        mod_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔎 Проверить материалы",
                        callback_data=f"mod_inspect:{rep_id}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⚠️ Выдать предупреждение",
                        callback_data=f"mod_warn:{rep_id}",
                    ),
                    InlineKeyboardButton(
                        text="⏳ Временно ограничить аккаунт",
                        callback_data=f"mod_limit:{rep_id}",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="🚫 Заблокировать аккаунт",
                        callback_data=f"mod_ban:{rep_id}",
                    ),
                    InlineKeyboardButton(
                        text="🗑 Отклонить жалобу",
                        callback_data=f"mod_reject:{rep_id}",
                    ),
                ],
            ]
        )
        try:
            await bot.send_message(
                chat_id=admin_id, text=admin_text, reply_markup=mod_kb
            )
        except Exception:
            pass
    block_prompt_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚫 Заблокировать тоже",
                    callback_data=f"blk_after_rep:{target_id}",
                ),
                InlineKeyboardButton(
                    text="👌 Нет, пока оставим",
                    callback_data="blk_skip_after_rep",
                ),
            ]
        ]
    )
    await message.answer(
        f"✅ Жалоба №{rep_id} принята и передана модерации.\n\n"
        "⚡️ ЕЩЁ ОДИН МОМЕНТ\n"
        "Хочешь, чтобы этот персонаж больше не появлялся в твоей жизни?",
        reply_markup=block_prompt_kb,
    )


@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    if message.from_user:
        uid = message.from_user.id
        rest_msg = get_restriction_status(uid)
        if rest_msg:
            await message.answer(rest_msg)
            return
        get_user_filter(uid)
        if uid in profiles and message.from_user.username:
            profiles[uid]["username"] = message.from_user.username
            save_state()
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔥 Погнали, я в деле", callback_data="reg_start")]
        ]
    )
    await message.answer("Дарова, начнешь?)", reply_markup=keyboard)


@dp.message(Command("krk"))
async def cmd_krk(message: types.Message):
    if message.from_user:
        rest_msg = get_restriction_status(message.from_user.id)
        if rest_msg:
            await message.answer(rest_msg)
            return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🔗 {KRK_SITE_TITLE}",
                    url=KRK_SITE_URL,
                )
            ]
        ]
    )
    await message.answer(
        "📂 Дополнительный материал\n"
        "🔓 Открыто\n\n"
        f"{KRK_SITE_TITLE}\n"
        "Дополнительный ресурс",
        reply_markup=keyboard,
    )


@dp.callback_query(F.data == "reg_start")
async def on_reg_start(callback: types.CallbackQuery):
    if callback.from_user:
        rest_msg = get_restriction_status(callback.from_user.id)
        if rest_msg:
            await callback.message.answer(rest_msg)
            await callback.answer()
            return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💃 Девушка", callback_data="gender_f"),
                InlineKeyboardButton(text="🕺 Парень", callback_data="gender_m"),
            ]
        ]
    )
    if callback.message:
        await callback.message.answer("Выбери свой пол:", reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(F.data.in_({"gender_f", "gender_m"}))
async def on_gender(callback: types.CallbackQuery, state: FSMContext):
    gender_label = "Девушка" if callback.data == "gender_f" else "Парень"
    await state.update_data(gender=gender_label)
    await state.set_state(RegForm.waiting_name)
    if callback.message:
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
        await message.answer("Напиши возраст числом, например: 19.")
        return
    age = int(raw_age)
    if age < 16 or age > 99:
        await message.answer("Доступно с 16 лет. Введи корректный возраст.")
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
                InlineKeyboardButton(text="💃 Девушку", callback_data="seek_f"),
                InlineKeyboardButton(text="🕺 Парня", callback_data="seek_m"),
            ],
            [
                InlineKeyboardButton(
                    text="🎲 Без разницы", callback_data="seek_any"
                )
            ],
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
    if callback.message:
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
    await message.answer("📸 Скинь своё фото для анкеты:")


@dp.message(RegForm.waiting_photo, F.photo)
async def on_photo(message: types.Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    await state.update_data(photo_id=photo_id)
    data = await state.get_data()
    await state.clear()
    uid = message.from_user.id if message.from_user else None
    username = message.from_user.username if message.from_user else None
    if uid is not None:
        get_user_filter(uid)
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
        save_state()
    await message.answer_photo(
        photo=photo_id,
        caption=format_profile_caption(data, user_id=uid, include_bonuses=True),
    )


@dp.message(RegForm.waiting_photo)
async def on_photo_invalid(message: types.Message):
    await message.answer("📸 Нужно отправить именно картинку/фото, а не текст.")


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
        caption=format_profile_caption(
            profile, user_id=user_id, include_bonuses=True
        ),
    )


@dp.message(Command("find"))
async def cmd_find(message: types.Message):
    if not message.from_user:
        return
    viewer_id = message.from_user.id
    rest_msg = get_restriction_status(viewer_id)
    if rest_msg:
        await message.answer(rest_msg)
        return
    if viewer_id not in profiles:
        await message.answer("Сначала заполни свою анкету через /start.")
        return
    get_user_filter(viewer_id)
    candidate_id = get_next_candidate_id(viewer_id)
    if candidate_id is None:
        await send_no_candidates_prompt(message, viewer_id)
        return
    await send_candidate(message, viewer_id, candidate_id)


@dp.callback_query(F.data == "find_replay_seen")
async def on_find_replay_seen(callback: types.CallbackQuery):
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    uid = callback.from_user.id
    seen_profiles[uid] = set()
    save_state()
    candidate_id = get_next_candidate_id(uid)
    if candidate_id is None:
        await send_no_candidates_prompt(callback.message, uid)
    else:
        await send_candidate(callback.message, uid, candidate_id)
    await callback.answer()


@dp.callback_query(F.data.startswith(("swipe_like:", "swipe_skip:")))
async def on_swipe(callback: types.CallbackQuery):
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    viewer_id = callback.from_user.id
    rest_msg = get_restriction_status(viewer_id)
    if rest_msg:
        await callback.message.answer(rest_msg)
        await callback.answer()
        return
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
            save_state()
            target_profile = profiles.get(target_id, {})
            await callback.message.answer(
                f"💘 Взаимка с {target_profile.get('name', 'пользователем')}!"
            )
            await enter_anon_chat(callback.message, viewer_id, target_id)
        else:
            bonus_left = extra_likes.get(viewer_id, 0)
            if bonus_left > 0:
                extra_likes[viewer_id] = bonus_left - 1
                save_state()
                await callback.message.answer(
                    f"❤️ Лайк отправлен (доп. лайков осталось: {extra_likes[viewer_id]})"
                )
            else:
                save_state()
                await callback.message.answer("❤️ Лайк отправлен")
    else:
        skipped_history.setdefault(viewer_id, []).append(target_id)
        save_state()
        await callback.message.answer("👎 Пропущено")
    next_id = get_next_candidate_id(viewer_id)
    if next_id is None:
        await send_no_candidates_prompt(callback.message, viewer_id)
    else:
        await send_candidate(callback.message, viewer_id, next_id)
    await callback.answer()


@dp.callback_query(F.data == "use_undo_skip")
async def on_use_undo_skip(callback: types.CallbackQuery):
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    uid = callback.from_user.id
    credits = undo_credits.get(uid, 0)
    if credits <= 0:
        await callback.message.answer(
            "Нет доступных откатов дизлайка. Оформить можно в /donate."
        )
        await callback.answer()
        return
    history = skipped_history.get(uid, [])
    restored_id: int | None = None
    while history:
        cand_id = history.pop()
        if cand_id in profiles and not is_blocked_between(uid, cand_id):
            restored_id = cand_id
            break
    if restored_id is None:
        save_state()
        await callback.message.answer(
            "Не нашлось подходящей пропущенной анкеты для возврата."
        )
        await callback.answer()
        return
    undo_credits[uid] = credits - 1
    seen_profiles.setdefault(uid, set()).discard(restored_id)
    save_state()
    await callback.message.answer(
        f"↩️ Возвращаю последнюю пропущенную анкету. Осталось откатов: {undo_credits[uid]}."
    )
    await send_candidate(callback.message, uid, restored_id)
    await callback.answer()


@dp.callback_query(F.data.startswith("peek_view:"))
async def on_peek_view(callback: types.CallbackQuery):
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    target_id = int(callback.data.split(":", 1)[1])
    prof = profiles.get(target_id)
    if not prof:
        await callback.message.answer("Анкета больше недоступна.")
        await callback.answer()
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❤️ Лайкнуть в ответ",
                    callback_data=f"peek_like_back:{target_id}",
                )
            ]
        ]
    )
    await callback.message.answer_photo(
        photo=prof["photo_id"],
        caption=format_profile_caption(
            prof,
            header="💘 Лайкнул(а)",
            user_id=target_id,
            viewer_id=callback.from_user.id,
        ),
        reply_markup=kb,
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("peek_like_back:"))
async def on_peek_like_back(callback: types.CallbackQuery):
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    viewer_id = callback.from_user.id
    target_id = int(callback.data.split(":", 1)[1])
    if target_id not in profiles or is_blocked_between(viewer_id, target_id):
        await callback.message.answer("Анкета недоступна.")
        await callback.answer()
        return
    likes_given.setdefault(viewer_id, set()).add(target_id)
    seen_profiles.setdefault(viewer_id, set()).add(target_id)
    if viewer_id in likes_given.get(target_id, set()):
        record_match(viewer_id, target_id)
        active_chats[viewer_id] = target_id
        active_chats[target_id] = viewer_id
        save_state()
        target_name = profiles[target_id].get("name", "пользователем")
        await callback.message.answer(f"💘 Взаимка с {target_name}!")
        await enter_anon_chat(callback.message, viewer_id, target_id)
    else:
        save_state()
        await callback.message.answer("❤️ Лайк отправлен.")
    await callback.answer()


@dp.callback_query(F.data.startswith("safety_menu:"))
async def on_safety_menu(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    target_id = int(callback.data.split(":", 1)[1])
    await callback.message.answer(
        "🚨 ЧТО-ТО ПОШЛО НЕ ТАК?\n"
        "Если этот человек ведёт себя как последнее недоразумение — сообщи нам.",
        reply_markup=build_safety_keyboard(target_id),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("rep_start:"))
async def on_report_start(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    target_id = int(callback.data.split(":", 1)[1])
    rows = [
        [
            InlineKeyboardButton(
                text=label, callback_data=f"rep_reason:{target_id}:{key}"
            )
        ]
        for key, (label, _) in REPORT_REASONS.items()
    ]
    await callback.message.answer(
        "🚨 НА ЧТО ЖАЛУЕМСЯ?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("rep_reason:"))
async def on_report_reason(callback: types.CallbackQuery, state: FSMContext):
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    _, raw_target, reason_key = callback.data.split(":", 2)
    target_id = int(raw_target)
    await state.set_state(ReportForm.waiting_comment)
    await state.update_data(rep_target_id=target_id, rep_reason_key=reason_key)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⏭ Отправить без комментария", callback_data="rep_skip_comment"
                )
            ]
        ]
    )
    await callback.message.answer(
        "💬 Хочешь добавить комментарий к жалобе? Напиши текст или нажми кнопку ниже.",
        reply_markup=kb,
    )
    await callback.answer()


@dp.callback_query(ReportForm.waiting_comment, F.data == "rep_skip_comment")
async def on_report_skip_comment(callback: types.CallbackQuery, state: FSMContext):
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    data = await state.get_data()
    await state.clear()
    await create_and_dispatch_report(
        message=callback.message,
        reporter_id=callback.from_user.id,
        target_id=int(data["rep_target_id"]),
        reason_key=str(data["rep_reason_key"]),
        comment=None,
    )
    await callback.answer()


@dp.message(ReportForm.waiting_comment)
async def on_report_comment_text(message: types.Message, state: FSMContext):
    if not message.from_user:
        return
    comment = (message.text or "").strip()
    data = await state.get_data()
    await state.clear()
    await create_and_dispatch_report(
        message=message,
        reporter_id=message.from_user.id,
        target_id=int(data["rep_target_id"]),
        reason_key=str(data["rep_reason_key"]),
        comment=comment or None,
    )


@dp.callback_query(F.data.startswith("blk_direct:"))
async def on_block_direct(callback: types.CallbackQuery):
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    target_id = int(callback.data.split(":", 1)[1])
    apply_block(callback.from_user.id, target_id)
    await callback.message.answer(
        "🚫 Пользователь заблокирован. Анкеты скрыты, переписка и обмен контактами закрыты."
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("blk_after_rep:"))
async def on_block_after_report(callback: types.CallbackQuery):
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    target_id = int(callback.data.split(":", 1)[1])
    apply_block(callback.from_user.id, target_id)
    await callback.message.answer(
        "🚫 Персонаж заблокирован. В твоей ленте и переписках он больше не появится."
    )
    await callback.answer()


@dp.callback_query(F.data == "blk_skip_after_rep")
async def on_skip_block_after_report(callback: types.CallbackQuery):
    if callback.message:
        await callback.message.answer("👌 Хорошо, блокировать пока не будем.")
    await callback.answer()


@dp.message(Command("sos"))
async def cmd_sos(message: types.Message, state: FSMContext):
    if not message.from_user:
        return
    await state.set_state(SosForm.waiting_message)
    await message.answer(
        "🆘 ЭКСТРЕННАЯ СВЯЗЬ С МОДЕРАЦИЕЙ\n"
        "Опиши ситуацию, требующую немедленного вмешательства (угрозы, шантаж, "
        "безопасность), и я передам её модераторам."
    )


@dp.message(SosForm.waiting_message)
async def on_sos_text(message: types.Message, state: FSMContext):
    if not message.from_user:
        return
    text = (message.text or "").strip()
    await state.clear()
    if not text:
        await message.answer("Экстренное обращение отменено — текст пуст.")
        return
    entry = {
        "user_id": message.from_user.id,
        "text": text,
        "time": datetime.now().strftime("%d.%m.%Y %H:%M"),
    }
    sos_requests.append(entry)
    save_state()
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=(
                    "🆘 ЭКСТРЕННЫЙ СИГНАЛ (/sos)\n"
                    f"• От пользователя: ID {message.from_user.id}\n"
                    f"• Время: {entry['time']}\n"
                    f"• Сообщение: {text}"
                ),
            )
        except Exception:
            pass
    await message.answer("✅ Экстренное обращение отправлено модерации.")


@dp.message(Command("mod"))
async def cmd_mod_panel(message: types.Message):
    if not message.from_user or message.from_user.id not in ADMIN_IDS:
        return
    pending = [r for r in reports_by_id.values() if r.get("status") == "pending"]
    pending.sort(key=lambda r: (not r.get("high_priority"), r["id"]))
    if not pending:
        await message.answer("🛡 MODERATION PANEL\nОткрытых жалоб в очереди нет.")
        return
    await message.answer(f"🛡 MODERATION PANEL\nЖалоб в очереди: {len(pending)}")
    for r in pending[:5]:
        prio = "🚨 ПРИОРИТЕТ\n" if r.get("high_priority") else ""
        text = (
            f"{prio}"
            f"📩 Жалоба №{r['id']}\n"
            f"• На кого: ID {r['target_id']}\n"
            f"• Кто пожаловался: ID {r['reporter_id']}\n"
            f"• Причина: {r['reason_label']}\n"
            f"• Дата: {r['created_at']}\n"
            f"• Комментарий: {r['comment']}"
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔎 Проверить материалы",
                        callback_data=f"mod_inspect:{r['id']}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="⚠️ Выдать предупреждение",
                        callback_data=f"mod_warn:{r['id']}",
                    ),
                    InlineKeyboardButton(
                        text="⏳ Временно ограничить аккаунт",
                        callback_data=f"mod_limit:{r['id']}",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="🚫 Заблокировать аккаунт",
                        callback_data=f"mod_ban:{r['id']}",
                    ),
                    InlineKeyboardButton(
                        text="🗑 Отклонить жалобу",
                        callback_data=f"mod_reject:{r['id']}",
                    ),
                ],
            ]
        )
        await message.answer(text, reply_markup=kb)


@dp.callback_query(F.data.startswith("mod_inspect:"))
async def on_mod_inspect(callback: types.CallbackQuery):
    if (
        not callback.from_user
        or callback.from_user.id not in ADMIN_IDS
        or not callback.message
    ):
        await callback.answer()
        return
    rep_id = int(callback.data.split(":", 1)[1])
    rep = reports_by_id.get(rep_id)
    if not rep:
        await callback.answer("Жалоба не найдена.", show_alert=True)
        return
    target_id = rep["target_id"]
    prof = profiles.get(target_id)
    prof_text = (
        format_profile_caption(prof, header=f"🪪 Анкета ID {target_id}", user_id=target_id)
        if prof
        else f"Анкета ID {target_id} отсутствует в памяти."
    )
    warns = user_warnings.get(target_id, 0)
    msgs = rep.get("messages_snapshot", [])
    msgs_lines = [
        f"[{m.get('time')}] ID {m.get('sender_id')}: {m.get('text')}" for m in msgs
    ]
    msgs_block = "\n".join(msgs_lines) if msgs_lines else "Сообщений в буфере нет."
    await callback.message.answer(
        f"🔎 Материалы по жалобе №{rep_id}\n"
        f"⚠️ Предупреждений у ID {target_id}: {warns}\n\n"
        f"{prof_text}\n\n"
        f"💬 Последние сообщения:\n{msgs_block}"
    )
    await callback.answer()


@dp.callback_query(
    F.data.startswith(("mod_warn:", "mod_limit:", "mod_ban:", "mod_reject:"))
)
async def on_mod_decision(callback: types.CallbackQuery):
    if (
        not callback.from_user
        or callback.from_user.id not in ADMIN_IDS
        or not callback.message
    ):
        await callback.answer()
        return
    action, raw_id = callback.data.split(":", 1)
    rep_id = int(raw_id)
    rep = reports_by_id.get(rep_id)
    if not rep:
        await callback.answer("Жалоба не найдена.", show_alert=True)
        return
    target_id = rep["target_id"]
    reporter_id = rep["reporter_id"]
    if action == "mod_warn":
        user_warnings[target_id] = user_warnings.get(target_id, 0) + 1
        rep["status"] = "warned"
        verdict_label = (
            f"⚠️ Выдано предупреждение (всего: {user_warnings[target_id]})."
        )
    elif action == "mod_limit":
        user_restrictions[target_id] = {
            "until": time.time() + 24 * 60 * 60,
            "banned": False,
        }
        rep["status"] = "limited"
        verdict_label = "⏳ Аккаунт временно ограничен на 24 часа."
    elif action == "mod_ban":
        user_restrictions[target_id] = {
            "until": time.time() + 10 * 365 * 24 * 60 * 60,
            "banned": True,
        }
        rep["status"] = "banned"
        verdict_label = "🚫 Аккаунт заблокирован."
    else:
        rep["status"] = "rejected"
        verdict_label = "🗑 Жалоба отклонена."
    save_state()
    await callback.message.answer(f"Жалоба №{rep_id}: {verdict_label}")
    try:
        await bot.send_message(
            chat_id=reporter_id,
            text=(
                "🛡 ТВОЯ ЖАЛОБА РАССМОТРЕНА.\n"
                "Модерация проверила обращение. Спасибо, что помог нам сделать это "
                "место безопаснее.\n"
                "Мы не раскрываем личность заявителя и подробности дисциплинарных мер.\n"
                "Береги себя, маленький вредитель."
            ),
        )
    except Exception:
        pass
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
                    text="🗑 Да, удалить взаимку",
                    callback_data=f"match_del_yes:{target_id}",
                ),
                InlineKeyboardButton(
                    text="⬅️ Отмена", callback_data=f"match_view:{target_id}"
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
    save_state()
    await callback.message.answer("Удалено из взаимок.")
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
    save_state()
    await callback.message.answer(
        "💌 Ну всё, романтик хренов, решил раскрыть карты?\n"
        "Твой запрос отправлен. Теперь ждём, согласится ли это чудо узнать тебя "
        "поближе.\n"
        "Не нервничай, ёбаный Купидон."
    )
    target_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💘 Да, чёрт возьми",
                    callback_data=f"contact_resp_yes:{requester_id}",
                ),
                InlineKeyboardButton(
                    text="🙅‍♂️ Нет, иди нахуй",
                    callback_data=f"contact_resp_no:{requester_id}",
                ),
            ]
        ]
    )
    try:
        await bot.send_message(
            chat_id=target_id,
            text=(
                "💘 ТУТ КТО-ТО ВЛЮБИЛСЯ?\n"
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
    save_state()
    await callback.message.answer("↩️ Запрос на обмен контактами аннулирован.")
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
        save_state()
        await callback.message.answer("Обмен контактами запрещён.")
        await callback.answer()
        return
    if action == "contact_resp_no":
        req["status"] = "declined"
        save_state()
        await callback.message.answer("Запрос закрыт.")
        try:
            await bot.send_message(
                chat_id=requester_id,
                text=(
                    "💔 Упс, романтик.\n"
                    "Твой собеседник пока не готов раскрывать карты.\n"
                    "Не расстраивайся, маленький ебанько. Продолжайте свою анонимную "
                    "любовную хуйню.\n"
                    "Возможно, ещё передумает."
                ),
            )
        except Exception:
            pass
        await callback.answer()
        return
    req["status"] = "accepted"
    if target_id in profiles and callback.from_user.username:
        profiles[target_id]["username"] = callback.from_user.username
    save_state()
    requester_contact = format_contact_link(requester_id)
    target_contact = format_contact_link(target_id, callback.from_user)
    for uid, partner_contact in (
        (target_id, requester_contact),
        (requester_id, target_contact),
    ):
        text = (
            "🥂 НУ ВСЁ, ВЫ ДВА БЕЗНАДЁЖНЫХ.\n"
            "Кажется, анонимность закончилась, а ваша любовная катастрофа выходит на "
            "новый уровень.\n"
            f"Держите контакты друг друга: {partner_contact}.\n"
            "Только не проебите такую прекрасную возможность испортить друг другу "
            "жизнь.\n"
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
        "⭐️ Выбирай, за что сегодня отдаёшь свои кровные:",
        reply_markup=build_donate_keyboard(),
    )


@dp.callback_query(F.data == "don_peek_likes")
async def on_don_peek_likes(callback: types.CallbackQuery):
    if callback.message:
        await callback.message.answer_invoice(
            title="Подглядеть лайки",
            description="Посмотреть список тех, кто уже поставил тебе лайк.",
            payload="buy_peek_likes",
            provider_token="",
            currency="XTR",
            prices=[
                LabeledPrice(
                    label="Список входящих лайков", amount=PEEK_LIKES_STARS_AMOUNT
                )
            ],
        )
    await callback.answer()


@dp.callback_query(F.data == "don_boost")
async def on_don_boost(callback: types.CallbackQuery):
    if callback.message:
        await callback.message.answer_invoice(
            title="Поднять анкету",
            description="Поставить анкету в топ выдачи на 24 часа.",
            payload="buy_boost",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="Поднятие анкеты на 24ч", amount=30)],
        )
    await callback.answer()


@dp.callback_query(F.data == "don_extra_likes")
async def on_don_extra_likes(callback: types.CallbackQuery):
    if callback.message:
        await callback.message.answer_invoice(
            title=f"+{EXTRA_LIKES_PACK_SIZE} доп. лайков",
            description="Добавить 10 дополнительных лайков для свайпов.",
            payload="buy_extra_likes",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="Пакет доп. лайков", amount=20)],
        )
    await callback.answer()


@dp.callback_query(F.data == "don_undo_skip")
async def on_don_undo_skip(callback: types.CallbackQuery):
    if callback.message:
        await callback.message.answer_invoice(
            title="Отменить дизлайк",
            description="Вернуть последнюю пропущенную анкету.",
            payload="buy_undo_skip",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="Отмена дизлайка", amount=10)],
        )
    await callback.answer()


@dp.pre_checkout_query()
async def on_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)


@dp.message(F.successful_payment)
async def on_successful_payment(message: types.Message):
    payment = message.successful_payment
    if not payment or not message.from_user:
        return
    uid = message.from_user.id
    if payment.invoice_payload == "buy_undo_skip":
        undo_credits[uid] = undo_credits.get(uid, 0) + 1
        save_state()
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="↩️ Вернуть последнюю пропущенную анкету",
                        callback_data="use_undo_skip",
                    )
                ]
            ]
        )
        await message.answer(
            f"✅ Оплата прошла! Начислен откат дизлайка (доступно: {undo_credits[uid]}).",
            reply_markup=kb,
        )
    elif payment.invoice_payload == "buy_extra_likes":
        extra_likes[uid] = extra_likes.get(uid, 0) + EXTRA_LIKES_PACK_SIZE
        save_state()
        await message.answer(
            f"✅ Оплата прошла! Начислено +{EXTRA_LIKES_PACK_SIZE} доп. лайков "
            f"(всего доступно: {extra_likes[uid]}). Запускай /find!"
        )
    elif payment.invoice_payload == "buy_boost":
        boosted_until[uid] = time.time() + BOOST_DURATION_SEC
        save_state()
        await message.answer(
            "✅ Оплата прошла! Твоя анкета поднята в топ выдачи на 24 часа."
        )
    elif payment.invoice_payload == "buy_vip_30d":
        vip_until[uid] = time.time() + VIP_DURATION_SEC
        save_state()
        await message.answer("✅ Оплата прошла! VIP активирован на 30 дней.")
    elif payment.invoice_payload == "buy_support_donation":
        supporter_donations[uid] = (
            supporter_donations.get(uid, 0) + payment.total_amount
        )
        save_state()
        await message.answer(
            f"✅ Оплата прошла! Спасибо за поддержку ({payment.total_amount} звёзд). "
            "Можешь выбрать титул в анкете через /donate."
        )
    elif payment.invoice_payload == "buy_peek_likes":
        await message.answer(
            "✅ Оплата прошла! Открываю список тех, кто тебя лайкнул:"
        )
        await send_incoming_likes_list(message, uid)


@dp.callback_query(F.data == "don_vip")
async def on_don_vip(callback: types.CallbackQuery):
    if callback.message:
        await callback.message.answer_invoice(
            title="VIP на 30 дней",
            description="Статус VIP в анкете и расширенные привилегии на 30 дней.",
            payload="buy_vip_30d",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="VIP на 30 дней", amount=120)],
        )
    await callback.answer()


@dp.callback_query(F.data == "don_support")
async def on_don_support(callback: types.CallbackQuery):
    if callback.message:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"⭐️ Задонатить {SUPPORT_STARS_AMOUNT} звёзд",
                        callback_data="pay_support_50",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="😈 Грешник", callback_data="title_sinner"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🖤 Покровитель тьмы", callback_data="title_patron"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="💸 Спонсор чужой любви", callback_data="title_sponsor"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🚫 Без титула в профиле", callback_data="title_clear"
                    )
                ],
            ]
        )
        await callback.message.answer(
            "⭐️ Поддержать проект просто потому что можешь, чёртов меценат. "
            "Можно закинуть звёзд или выбрать титул по желанию:",
            reply_markup=keyboard,
        )
    await callback.answer()


@dp.callback_query(F.data == "pay_support_50")
async def on_pay_support_50(callback: types.CallbackQuery):
    if callback.message:
        await callback.message.answer_invoice(
            title="Поддержка проекта",
            description="Добровольный донат на развитие бота.",
            payload="buy_support_donation",
            provider_token="",
            currency="XTR",
            prices=[
                LabeledPrice(
                    label="Поддержка проекта", amount=SUPPORT_STARS_AMOUNT
                )
            ],
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
        save_state()
        await callback.message.answer("Титул скрыт из профиля.")
    else:
        chosen = DONATE_TITLES[callback.data]
        user_titles[uid] = chosen
        save_state()
        await callback.message.answer(f"🏷 Выбран титул: {chosen}.")
    await callback.answer()


@dp.message(Command("settings"))
async def cmd_settings(message: types.Message, state: FSMContext):
    await state.clear()
    if not message.from_user:
        return
    await message.answer(
        format_filters_summary(message.from_user.id),
        reply_markup=build_settings_keyboard(),
    )


@dp.callback_query(F.data == "open_general_chat")
async def on_open_general_chat(callback: types.CallbackQuery):
    if callback.message:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="💬 Зайти в «место сбора странных»",
                        url=GENERAL_CHAT_URL,
                    )
                ]
            ]
        )
        await callback.message.answer(
            "💬 ОБЩИЙ ЧАТ\n"
            "Хочешь пообщаться? Заходи к нам. Здесь можно познакомиться с новыми "
            "людьми, обсудить всё на свете и просто провести время.",
            reply_markup=kb,
        )
    await callback.answer()


@dp.callback_query(F.data == "flt_open_menu")
async def on_flt_open_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    if callback.from_user and callback.message:
        await callback.message.answer(
            format_filters_summary(callback.from_user.id),
            reply_markup=build_settings_keyboard(),
        )
    await callback.answer()


@dp.callback_query(F.data == "flt_gender_menu")
async def on_flt_gender_menu(callback: types.CallbackQuery):
    if callback.message:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🕺 Только парней", callback_data="set_g_m"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="💃 Только девушек", callback_data="set_g_f"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🎲 Всех подряд", callback_data="set_g_all"
                    )
                ],
            ]
        )
        await callback.message.answer("Кого будем искать?", reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(F.data.in_({"set_g_m", "set_g_f", "set_g_all"}))
async def on_set_gender_pref(callback: types.CallbackQuery):
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    f = get_user_filter(callback.from_user.id)
    mapping = {"set_g_m": "m", "set_g_f": "f", "set_g_all": "all"}
    f["gender_pref"] = mapping[callback.data]
    save_state()
    await callback.message.answer(
        format_filters_summary(callback.from_user.id),
        reply_markup=build_settings_keyboard(),
    )
    await callback.answer()


@dp.callback_query(F.data == "flt_age_menu")
async def on_flt_age_menu(callback: types.CallbackQuery, state: FSMContext):
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    await state.set_state(FilterForm.waiting_age_range)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="16 - 17 лет", callback_data="set_age:16:17"),
                InlineKeyboardButton(text="18 - 25 лет", callback_data="set_age:18:25"),
            ],
            [
                InlineKeyboardButton(text="18 - 30 лет", callback_data="set_age:18:30"),
                InlineKeyboardButton(text="21 - 35 лет", callback_data="set_age:21:35"),
            ],
            [InlineKeyboardButton(text="18 - 99 лет", callback_data="set_age:18:99")],
        ]
    )
    await callback.message.answer(
        "🎂 Выбери диапазон или напиши свой текстом, например: 18-24",
        reply_markup=keyboard,
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("set_age:"))
async def on_set_age_preset(callback: types.CallbackQuery, state: FSMContext):
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    await state.clear()
    _, min_s, max_s = callback.data.split(":", 2)
    f = get_user_filter(callback.from_user.id)
    f["age_min"] = max(16, int(min_s))
    f["age_max"] = max(f["age_min"], min(99, int(max_s)))
    save_state()
    await callback.message.answer(
        format_filters_summary(callback.from_user.id),
        reply_markup=build_settings_keyboard(),
    )
    await callback.answer()


@dp.message(FilterForm.waiting_age_range)
async def on_custom_age_range(message: types.Message, state: FSMContext):
    if not message.from_user:
        return
    raw = (message.text or "").replace(" ", "-").replace("–", "-").replace("—", "-").strip()
    parts = [p.strip() for p in raw.split("-") if p.strip()]
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        await message.answer("Напиши диапазон от 16, например: 18-25.")
        return
    age_min = int(parts[0])
    age_max = int(parts[1])
    if age_min < 16 or age_max > 99 or age_min > age_max:
        await message.answer(
            "Возраст должен быть от 16 до 99, а начало не больше конца."
        )
        return
    await state.clear()
    f = get_user_filter(message.from_user.id)
    f["age_min"] = age_min
    f["age_max"] = age_max
    save_state()
    await message.answer(
        format_filters_summary(message.from_user.id),
        reply_markup=build_settings_keyboard(),
    )


@dp.callback_query(F.data == "flt_geo_menu")
async def on_flt_geo_menu(callback: types.CallbackQuery):
    if callback.message:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🌍 Любой город", callback_data="set_city:any"
                    ),
                    InlineKeyboardButton(
                        text="🏙 Только мой город", callback_data="set_city:my"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="📏 Дистанция: Без ограничений",
                        callback_data="set_dist:any",
                    ),
                    InlineKeyboardButton(
                        text=f"📍 Поблизости (до {int(NEARBY_RADIUS_KM)} км)",
                        callback_data="set_dist:near",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="📍 Скинуть геолокацию",
                        callback_data="req_send_location",
                    )
                ],
            ]
        )
        await callback.message.answer(
            "📍 Выбери город, дистанцию или отправь свою геолокацию:",
            reply_markup=keyboard,
        )
    await callback.answer()


@dp.callback_query(F.data == "req_send_location")
async def on_request_send_location(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return
    await callback.message.answer(
        "📍 Нажми кнопку ниже, чтобы скинуть свою геолокацию, "
        "или отправь её через скрепку в чате.\n"
        "Точные координаты другим пользователям не показываются — только примерное расстояние.",
        reply_markup=build_location_request_keyboard(),
    )
    await callback.answer()


@dp.message(F.text == "❌ Отмена")
async def on_cancel_location_kb(message: types.Message):
    if not message.from_user:
        return
    await message.answer("Отменено.", reply_markup=ReplyKeyboardRemove())
    await message.answer(
        format_filters_summary(message.from_user.id),
        reply_markup=build_settings_keyboard(),
    )


@dp.message(F.location)
async def on_user_location(message: types.Message):
    if not message.from_user or not message.location:
        return
    uid = message.from_user.id
    rest_msg = get_restriction_status(uid)
    if rest_msg:
        await message.answer(rest_msg, reply_markup=ReplyKeyboardRemove())
        return
    user_locations[uid] = {
        "lat": message.location.latitude,
        "lon": message.location.longitude,
        "updated_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
    }
    save_state()
    await message.answer(
        "📍 Геолокация сохранена. Теперь в анкетах будет видна примерная дистанция, "
        f"а в режиме «Поблизости» — подбор в радиусе {int(NEARBY_RADIUS_KM)} км.",
        reply_markup=ReplyKeyboardRemove(),
    )
    await message.answer(
        format_filters_summary(uid),
        reply_markup=build_settings_keyboard(),
    )


@dp.callback_query(F.data.startswith("set_city:"))
async def on_set_city(callback: types.CallbackQuery):
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    mode = callback.data.split(":", 1)[1]
    f = get_user_filter(callback.from_user.id)
    f["city_mode"] = "my" if mode == "my" else "any"
    save_state()
    await callback.message.answer(
        format_filters_summary(callback.from_user.id),
        reply_markup=build_settings_keyboard(),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("set_dist:"))
async def on_set_dist(callback: types.CallbackQuery):
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    uid = callback.from_user.id
    dist = callback.data.split(":", 1)[1]
    f = get_user_filter(uid)
    if dist == "near":
        f["distance"] = "near"
        save_state()
        if uid not in user_locations:
            await callback.message.answer(
                f"📍 Выбран режим «Поблизости (до {int(NEARBY_RADIUS_KM)} км)». "
                "Скинь свою геолокацию, чтобы я мог считать расстояние до других:",
                reply_markup=build_location_request_keyboard(),
            )
            await callback.answer()
            return
    f["distance"] = "any"
    save_state()
    await callback.message.answer(
        format_filters_summary(uid),
        reply_markup=build_settings_keyboard(),
    )
    await callback.answer()


@dp.callback_query(F.data == "flt_expand_age")
async def on_flt_expand_age(callback: types.CallbackQuery):
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    f = get_user_filter(callback.from_user.id)
    prof = profiles.get(callback.from_user.id, {})
    min_allowed = 16 if (prof.get("age") or 18) < 18 else 18
    f["age_min"] = min_allowed
    f["age_max"] = min(99, max(f["age_max"] + 5, 30))
    save_state()
    await callback.message.answer(
        f"🎂 Диапазон расширен до {f['age_min']}-{f['age_max']} лет."
    )
    candidate_id = get_next_candidate_id(callback.from_user.id)
    if candidate_id is None:
        await send_no_candidates_prompt(callback.message, callback.from_user.id)
    else:
        await send_candidate(callback.message, callback.from_user.id, candidate_id)
    await callback.answer()


@dp.callback_query(F.data == "flt_any_city")
async def on_flt_any_city(callback: types.CallbackQuery):
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    f = get_user_filter(callback.from_user.id)
    f["city_mode"] = "any"
    save_state()
    await callback.message.answer("🌍 Теперь поиск по любому городу.")
    candidate_id = get_next_candidate_id(callback.from_user.id)
    if candidate_id is None:
        await send_no_candidates_prompt(callback.message, callback.from_user.id)
    else:
        await send_candidate(callback.message, callback.from_user.id, candidate_id)
    await callback.answer()


@dp.callback_query(F.data == "flt_reset")
async def on_flt_reset(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    if callback.from_user and callback.message:
        user_filters[callback.from_user.id] = get_default_filters()
        save_state()
        await callback.message.answer(
            format_filters_summary(callback.from_user.id),
            reply_markup=build_settings_keyboard(),
        )
    await callback.answer()


@dp.callback_query(F.data == "flt_save")
async def on_flt_save(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    if callback.from_user and callback.message:
        save_state()
        await callback.message.answer(
            "💾 Изменения сохранены. Запускай /find — дальше подбираю по ним."
        )
    await callback.answer()


@dp.message(F.text & ~F.text.startswith("/"))
async def on_anon_message(message: types.Message, state: FSMContext):
    if await state.get_state() is not None or not message.from_user:
        return
    sender_id = message.from_user.id
    rest_msg = get_restriction_status(sender_id)
    if rest_msg:
        await message.answer(rest_msg)
        return
    partner_id = active_chats.get(sender_id)
    if not partner_id:
        return
    if is_blocked_between(sender_id, partner_id):
        await message.answer("Сообщение не отправлено: чат заблокирован.")
        return
    msg_text = message.text or ""
    record_chat_message(sender_id, partner_id, msg_text)
    try:
        await bot.send_message(
            chat_id=partner_id,
            text=f"💬 Анонимно:\n{msg_text}",
        )
    except Exception:
        await message.answer("Не удалось доставить сообщение собеседнику.")


async def register_bot_commands() -> None:
    try:
        await bot.set_my_commands(
            [
                BotCommand(command="start", description="Запуск и анкета"),
                BotCommand(command="find", description="Смотреть анкеты"),
                BotCommand(command="matches", description="Взаимные лайки и чаты"),
                BotCommand(command="me", description="Моя анкета и бонусы"),
                BotCommand(command="settings", description="Фильтры и настройки"),
                BotCommand(command="donate", description="Звёзды, VIP и титулы"),
                BotCommand(command="krk", description="Дополнительный материал"),
                BotCommand(command="sos", description="Экстренная связь с модерацией"),
                BotCommand(command="mod", description="Панель модерации"),
            ]
        )
    except Exception:
        pass


async def main() -> None:
    load_state()
    await register_bot_commands()
    threading.Thread(target=keepalive, daemon=True).start()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
