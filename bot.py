import asyncio
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

TOKEN = "9153210051:AAHE_03kRXkYpXhhb9oxmkZoa0XcKiW3nEg"

bot = Bot(token=TOKEN)
dp = Dispatcher()


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


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
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
async def on_gender(callback: types.CallbackQuery):
    gender_label = "Девушка" if callback.data == "gender_f" else "Парень"
    await callback.message.answer(f"Пол сохранён: {gender_label}. Следующий шаг.")
    await callback.answer()


@dp.message(Command("me"))
async def cmd_me(message: types.Message):
    await message.answer("🃏 Твой козырь")


@dp.message(Command("find"))
async def cmd_find(message: types.Message):
    await message.answer("👀 Твой типаж")


@dp.message(Command("matches"))
async def cmd_matches(message: types.Message):
    await message.answer("🍒 Взаимки")


@dp.message(Command("donate"))
async def cmd_donate(message: types.Message):
    await message.answer("💸 Задонатить")


@dp.message(Command("settings"))
async def cmd_settings(message: types.Message):
    await message.answer("⚙️ Подкрутить")


async def main() -> None:
    threading.Thread(target=keepalive, daemon=True).start()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

