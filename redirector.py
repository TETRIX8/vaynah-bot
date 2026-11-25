import os, asyncio
from aiogram import Bot, Dispatcher
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from aiogram.filters import CommandStart

TOKEN=os.environ.get('LEGACY_BOT_TOKEN','')
NEW='https://t.me/MyVainakhBot'
dp=Dispatcher()
def kb():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🚀 Открыть нового бота VAYNAH', url=NEW)]])
async def send(target, args=''):
    text='''Бот переехал на новый адрес. Все подписки, платежи, настройки и доступы сохранены.\n\nНажми кнопку ниже и продолжи работу в новом боте VAYNAH.'''
    if args: text += '\n\nТвоя ссылка перенаправлена автоматически.'
    await target.answer(text, reply_markup=kb())
@dp.message()
async def redirect_message(m: Message):
    args=''
    if m.text and m.text.startswith('/start'):
        args=m.text.partition(' ')[2]
    await send(m, args)
@dp.callback_query()
async def redirect_callback(q: CallbackQuery):
    await q.answer('Бот переехал на новый адрес', show_alert=True)
    await q.message.answer('Открой нового бота VAYNAH:', reply_markup=kb())
async def main():
    if not TOKEN: raise RuntimeError('LEGACY_BOT_TOKEN is empty')
    bot=Bot(TOKEN)
    await bot.delete_webhook(drop_pending_updates=False)
    await bot.set_my_commands([BotCommand(command='start',description='Открыть нового бота VAYNAH')])
    await dp.start_polling(bot, allowed_updates=['message','callback_query'])
if __name__=='__main__': asyncio.run(main())
