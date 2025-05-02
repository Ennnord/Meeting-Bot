import datetime
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.types import ReplyKeyboardRemove, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
import aiomysql
import config  # Конфигурационный файл с токеном и данными для подключения к БД

# Настройка логгирования
logging.basicConfig(level=logging.INFO, handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),  # Указываем кодировку UTF-8
        logging.StreamHandler()  # Для вывода логов в консоль
    ])
logger = logging.getLogger(__name__)

# Инициализация бота
bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher(bot)

# Класс для работы с базой данных
class DatabaseManager:
    def __init__(self, host, user, password, db):
        self.host = host
        self.user = user
        self.password = password
        self.db = db
        self.connection = None

    async def connect(self):
        """Подключение к базе данных."""
        self.connection = await aiomysql.connect(
            host=self.host,
            user=self.user,
            password=self.password,
            db=self.db
        )
        logger.info("База данных подключена!")

    async def close(self):
        """Закрытие соединения с базой данных."""
        if self.connection:
            await self.connection.close()
            logger.info("Соединение с базой данных закрыто.")

    async def fetch_groups(self):
        """Получение списка групп из базы данных."""
        async with self.connection.cursor() as cursor:
            await cursor.execute("SELECT DISTINCT group_id FROM schedule WHERE group_id NOT LIKE '%,%'")
            return await cursor.fetchall()

    async def fetch_schedule(self, day, groups):
        """Получение расписания для указанных групп и дня."""
        async with self.connection.cursor() as cursor:
            await cursor.execute("""
                SELECT time FROM schedule 
                WHERE date = %s AND 
                (group_id IN %s OR CONCAT(',', group_id, ',') LIKE %s)
                """, (day, tuple(groups), f'%,{groups},%'))
            return await cursor.fetchall()

# Инициализация менеджера базы данных
db_manager = DatabaseManager(config.DB_HOST, config.DB_USER, config.DB_PASSWORD, config.DB_NAME)

# Словарь для хранения состояния каждого пользователя
user_data = {}

# Функция для подключения к базе данных при старте бота
async def on_startup(dp):
    await db_manager.connect()

# Функция для закрытия соединения с базой данных при завершении работы бота
async def on_shutdown(dp):
    await db_manager.close()

# Обработчик команды /start
@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    btn = types.KeyboardButton('Запланировать новую встречу')
    markup.add(btn)
    await message.reply(
        """\n<b>Привет!\n
🌟 Это бот для планирования встречи с группами ИУБиП</b>🌟\n\n
<i><b>• Что бот может?</b></i>🤖\n
    - Бот способен, анализируя базу данных расписания всех групп, подобрать для тебя время для проведения встречи до или после пар.\n\n
<i><b>• Как использовать бота?</b></i>⁉️\n
    1. Нажмите кнопку ниже, чтобы запланировать новую встречу.\n
    2. Выбери нужные группы (все выбранные группы будут отображаться в сообщении ниже).\n
    3. После выбора групп нажми кнопку "Запланировать встречу".\n\n
<i><b>• Что делать, если выбрал лишнюю группу?</b></i>❌\n
    - Ничего страшного, нажмите ещё раз на группу, чтобы убрать её из списка.""",
        reply_markup=markup,
        parse_mode="HTML"
    )

# Обработчик кнопки "Запланировать новую встречу"
@dp.message_handler(lambda message: message.text == 'Запланировать новую встречу')
async def plan_meeting(message: types.Message):
    global db_manager
    try:
        await db_manager.connect()
        # Получаем список групп из базы данных
        groups = await db_manager.fetch_groups()
        await message.reply("Выберите группы для встречи", reply_markup=ReplyKeyboardRemove())

        # Создаем инлайн-клавиатуру с группами
        markup = InlineKeyboardMarkup()
        for i in range(0, len(groups), 3):
            if len(groups) - i >= 3:
                markup.row(
                    InlineKeyboardButton(groups[i][0], callback_data=groups[i][0]),
                    InlineKeyboardButton(groups[i + 1][0], callback_data=groups[i + 1][0]),
                    InlineKeyboardButton(groups[i + 2][0], callback_data=groups[i + 2][0])
                )
            elif len(groups) - i == 2:
                markup.row(
                    InlineKeyboardButton(groups[i][0], callback_data=groups[i][0]),
                    InlineKeyboardButton(groups[i + 1][0], callback_data=groups[i + 1][0])
                )
            else:
                markup.row(
                    InlineKeyboardButton(groups[i][0], callback_data=groups[i][0])
                )
        await message.answer("Список всех групп:", reply_markup=markup)
    except Exception as e:
        logger.error(f"Ошибка при получении групп: {e}")
        await message.reply("Произошла ошибка при получении списка групп. Попробуйте позже.")

# Функция для генерации расписания встреч
async def generate_meeting_schedule(user_id: int, days: list[str]) -> list[str]:
    await db_manager.connect()
    """Генерирует расписание встреч для пользователя на указанные дни."""
    schedule = []
    for day in days:
        answer = f"Время для встречи {datetime.datetime.strptime(day,'%d-%m-%Y').strftime('%d.%m')}🗓\n\n"

        try:
            times = await db_manager.fetch_schedule(day, user_data[user_id]['used_groups'])
            if times:
                start_times = []
                end_times = []
                for time_range in times:
                    start, end = time_range[0].split('-')
                    start_times.append(datetime.datetime.strptime(start, "%H:%M").time())
                    end_times.append(datetime.datetime.strptime(end, "%H:%M").time())
                min_time = min(start_times).strftime("%H:%M")
                max_time = max(end_times).strftime("%H:%M")
                answer += f"                До {min_time}☀️\n                    ИЛИ\n              После {max_time}🌛"
            else:
                answer += "Любое время, пар нет🎊"
        except Exception as e:
            logger.error(f"Ошибка при генерации расписания: {e}")
            answer += "Не удалось получить расписание."
        schedule.append(answer)
    return schedule

# Обработчик callback-запросов
@dp.callback_query_handler(lambda callback_query: True)
async def handle_callback(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    if user_id not in user_data:
        user_data[user_id] = {
            'last_message_id': None,
            'last_chat_id': None,
            'last_message_text': "",
            'used_groups': []
        }

    if callback_query.data == "make_meet":
        # Генерация расписания на ближайшую неделю
        days = [datetime.date.today() + datetime.timedelta(days=i) for i in range(7)]
        formatted_days = [day.strftime("%d-%m-%Y") for day in days]
        schedule = await generate_meeting_schedule(user_id, formatted_days)
        for answer in schedule:
            await callback_query.message.answer(answer)
        user_data[user_id]['used_groups'].clear()
        user_data[user_id]['last_message_id'] = None
        user_data[user_id]['last_chat_id'] = None

        # Возврат кнопки "Запланировать новую встречу"
        markup = ReplyKeyboardMarkup(resize_keyboard=True)
        btn = types.KeyboardButton('Запланировать новую встречу')
        markup.add(btn)
        await callback_query.message.reply(
            "Вот план для встречи на ближайшую неделю. Нажмите на кнопку ниже, чтобы спланировать новую встречу",
            reply_markup=markup)
    else:
        await callback_query.answer() # Убираю время отката кнопки

        if callback_query.data not in user_data[user_id]['used_groups']: # Если такой группы нет в списки - добавляю, иначе убираю
            user_data[user_id]['used_groups'].append(callback_query.data)
        else:
            user_data[user_id]['used_groups'].remove(callback_query.data)

        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("Запланировать встречу", callback_data="make_meet"))

        """Цикл для отображения выбранных групп"""
        new_text = "Выбранные вами группы:"
        for group in user_data[user_id]['used_groups']:
            new_text += f"\n{group}"

        # Обновление сообщения с выбранными группами
        if user_data[user_id]['last_chat_id'] and user_data[user_id]['last_message_id']:
            await bot.edit_message_text(
                new_text,
                chat_id=user_data[user_id]['last_chat_id'],
                message_id=user_data[user_id]['last_message_id'],
                reply_markup=markup if user_data[user_id]['used_groups'] != [] else None
            )
        else: # Иначе создаю новое сообщение и запоминаю его id
            message = await callback_query.message.answer(new_text,reply_markup=markup)
            user_data[user_id]['last_message_id'] = message.message_id
            user_data[user_id]['last_chat_id'] = message.chat.id

# Запуск бота
if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup, on_shutdown=on_shutdown)