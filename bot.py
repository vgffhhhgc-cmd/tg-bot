import asyncio
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

TOKEN = "9153210051:AAHE_03kRXkYpXhhb9oxmkZoa0XcKiW3nEg"

bot = Bot(token=TOKEN)
dp = Dispatcher()


def keepalive() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, format: str, *args) -> None:
            return

    HTTPServer(("0.0.0.0", 10000), Handler).serve_forever()


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Привет! Команда /start сработала.")


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
