import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart,Command:
from aiogram.filters import CommandStart, Command

TOKEN = "9153210051:AAHE_03kRXkYpXhhb9oxmkZoa0XcKiW3nEg"

bot = Bot(token=TOKEN)
dp = Dispatcher()

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer("Я умею отвечать на /start и /help.")

@dp.message(CommandStart())
async def cmd_start(message: types.Message) -> None:
    await message.answer("Бот работает")


async def main() -> None:
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
