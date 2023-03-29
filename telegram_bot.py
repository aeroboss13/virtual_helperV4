import asyncio
import logging
import os

import telegram.constants as constants
from telegram import Update, InlineQueryResultArticle, InputTextMessageContent, InlineKeyboardMarkup, \
    InlineKeyboardButton
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, InlineQueryHandler, \
    CallbackQueryHandler

import payments

logging.basicConfig(level=logging.INFO)
from openai_helper import OpenAIHelper
from pydub import AudioSegment
from docx import Document
import datetime
import json


class ChatGPT3TelegramBot:
    """
    Class representing a Chat-GPT3 Telegram Bot.
    """

    def __init__(self, config: dict, openai: OpenAIHelper):
        """
        Initializes the bot with the given configuration and GPT-3 bot object.
        :param config: A dictionary containing the bot configuration
        :param openai: OpenAIHelper object
        """
        self.config = config
        self.openai = openai
        self.last_response = None
        self.hours_dict = {'day': 24, 'month': 720, '6month': 4320, 'year': 8760}
        self.prices_dict = {'day': 99, 'month': 390, '6month': 690, 'year': 990}
        self.name_dict = {'day': '1 день подписки', 'month': "1 месяц подписки", '6month': "6 месяцев подписки", 'year': "1 год подписки"}

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Shows the help menu.
        """
        with open('userlist.json', 'r') as file:
            data = json.loads(file.read())
        try:
            _ = data[str(update.effective_chat.id)]
        except KeyError:
            data[str(update.effective_chat.id)] = [10, 0]
            with open('userlist.json', 'w', encoding='utf-8') as file:
                json.dump(data, file, indent=4, ensure_ascii=False)
        await update.message.reply_text(
            "Привет! Я бот, который поможет тебе в учебе. Напиши что нужно сделать и я займусь этим!\n\n"


            "/image - 🌅 Чтобы сгенерировать изображение, начните свой запрос с /image. Работает в тестовом режиме на английском языке\n"
            "/word - После того как вы получили ответ от бота - отправьте сообщение /word и бот предоставит свой ответ в формате файла word\n"
            "/reset - сбросить предыдущие ответы бота",
            disable_web_page_preview=True)

    async def reset(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Resets the conversation.
        """
        chat_id = update.effective_chat.id
        if not await self.is_allowed(chat_id, context):
            logging.warning(f'User {update.message.from_user.name} is not allowed to use the bot')
            keyb = InlineKeyboardMarkup([[InlineKeyboardButton(text='Купить подписку', callback_data='subscription')]])
            await update.message.reply_text(text="Извини, но у тебя нет доступа к боту. Для покупки подписки нажми на "
                                                 "кнопку ниже.", reply_markup=keyb)
            return

        logging.info(f'Resetting the conversation for user {update.message.from_user.name}...')

        chat_id = update.effective_chat.id
        self.openai.reset_chat_history(chat_id=chat_id)
        await context.bot.send_message(chat_id=chat_id, text='Done!')

    async def image(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Generates an image for the given prompt using DALL·E APIs
        """


        logging.info(f'New image generation request received from user {update.message.from_user.name}')

        chat_id = update.effective_chat.id
        image_query = update.message.text.replace('/image', '').strip()
        if image_query == '':
            await context.bot.send_message(chat_id=chat_id, text='Please provide a prompt!')
            return

        await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)

        message = await context.bot.send_message(chat_id=chat_id, text='Подождите, я печатаю...')

        try:
            image_url = self.openai.generate_image(prompt=image_query)
            await context.bot.delete_message(chat_id=chat_id, message_id=message.message_id)
            await context.bot.send_photo(
                chat_id=chat_id,
                reply_to_message_id=update.message.message_id,
                photo=image_url
            )
        except Exception as e:
            logging.exception(e)
            await context.bot.delete_message(chat_id=chat_id, message_id=message.message_id)
            await context.bot.send_message(
                chat_id=chat_id,
                reply_to_message_id=update.message.message_id,
                text=f'Failed to generate image: {str(e)}'
            )

    async def transcribe(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Transcribe audio messages.
        """
        chat_id = update.effective_chat.id
        if not await self.is_allowed(chat_id, context):
            logging.warning(f'User {update.message.from_user.name} is not allowed to use the bot')
            keyb = InlineKeyboardMarkup([[InlineKeyboardButton(text='Купить подписку', callback_data='subscription')]])
            await update.message.reply_text(text="Извини, но у тебя нет доступа к боту. Для покупки подписки нажми на "
                                                 "кнопку ниже.", reply_markup=keyb)
            return

        if not update.message.voice and not update.message.audio:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                reply_to_message_id=update.message.message_id,
                text='Unsupported file type'
            )
            return

        logging.info(f'New transcribe request received from user {update.message.from_user.name}')

        chat_id = update.effective_chat.id
        await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)
        filename = update.message.voice.file_unique_id if update.message.voice else update.message.audio.file_unique_id
        filename_ogg = f'{filename}.ogg'
        filename_mp3 = f'{filename}.mp3'

        try:
            if update.message.voice:
                audio_file = await context.bot.get_file(update.message.voice.file_id)
                await audio_file.download_to_drive(filename_ogg)
                ogg_audio = AudioSegment.from_ogg(filename_ogg)
                ogg_audio.export(filename_mp3, format="mp3")

            elif update.message.audio:
                audio_file = await context.bot.get_file(update.message.audio.file_id)
                await audio_file.download_to_drive(filename_mp3)

            # Transcribe the audio file
            transcript = self.openai.transcribe(filename_mp3)

            if self.config['voice_reply_transcript']:
                # Send the transcript
                await context.bot.send_message(
                    chat_id=chat_id,
                    reply_to_message_id=update.message.message_id,
                    text=f'_Transcript:_\n"{transcript}"',
                    parse_mode=constants.ParseMode.MARKDOWN
                )
            else:
                # Send the response of the transcript
                response = self.openai.get_chat_response(chat_id=chat_id, query=transcript)
                await context.bot.send_message(
                    chat_id=chat_id,
                    reply_to_message_id=update.message.message_id,
                    text=f'_Transcript:_\n"{transcript}"\n\n_Answer:_\n{response}',
                    parse_mode=constants.ParseMode.MARKDOWN
                )
        except Exception as e:
            logging.exception(e)
            await context.bot.send_message(
                chat_id=chat_id,
                reply_to_message_id=update.message.message_id,
                text=f'У тебя очень крутой голос, но я не люблю слушать людей... Напиши мне текстом то, что тебя интересует!'
            )
        finally:
            # Cleanup files
            if os.path.exists(filename_mp3):
                os.remove(filename_mp3)
            if os.path.exists(filename_ogg):
                os.remove(filename_ogg)

    def word1(self, chat_id: int, response: str):
        """
        Generates a docx file and saves it on the server.
        """
        if os.path.exists(f'{chat_id}.docx'):
            os.remove(f'{chat_id}.docx')
        document = Document()
        document.add_paragraph(response)
        document.save(f"{chat_id}.docx")

    async def word(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        # Send the response as a document
        await context.bot.send_document(chat_id=chat_id, document=open(f"{chat_id}.docx", "rb"))
        if os.path.exists(f'{chat_id}.docx'):
            os.remove(f'{chat_id}.docx')

    async def prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handles incoming messages and generates a response using GPT-3.
        """
        chat_id = update.effective_chat.id
        if not await self.is_allowed(chat_id, context):
            logging.warning(f'User {update.message.from_user.name} is not allowed to use the bot')
            keyb = InlineKeyboardMarkup([[InlineKeyboardButton(text='Купить подписку', callback_data='subscription')]])
            await update.message.reply_text(text="Извини, но у тебя нет доступа к боту. Для покупки подписки нажми на "
                                                 "кнопку ниже.", reply_markup=keyb)
            return

        logging.info(f'New prompt received from user {update.message.from_user.name}')

        # Send "Подождите" notification to the user
        message = await context.bot.send_message(chat_id=chat_id, text="Подождите, я печатаю...")

        # Generate a response
        response = self.openai.get_chat_response(chat_id=chat_id, query=update.message.text)

        # Remove the "Подождите" notification
        await context.bot.delete_message(chat_id=chat_id, message_id=message.message_id)

        await context.bot.send_message(chat_id=chat_id, text=response)

        # Generate a docx file and save it on the server
        self.word1(chat_id, response)

    async def inline_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handle the inline query. This is run when you type: @botusername <query>
        """
        query = update.inline_query.query

        if query == "":
            return

        results = [
            InlineQueryResultArticle(
                id=query,
                title="Ask ChatGPT",
                input_message_content=InputTextMessageContent(query),
                description=query,
                thumb_url='https://user-images.githubusercontent.com/11541888/223106202-7576ff11-2c8e-408d-94ea-b02a7a32149a.png'
            )
        ]

        await update.inline_query.answer(results)

    async def send_disallowed_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Sends the disallowed message to the user.
        """
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=self.disallowed_message,
            disable_web_page_preview=True
        )

    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Handles errors in the telegram-python-bot library.
        """
        logging.debug(f'Exception while handling an update: {context.error}')

    async def subscription(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        board = [[InlineKeyboardButton(text=f'1 день', callback_data=f'price-day')],
                 [InlineKeyboardButton(text=f'1 месяц', callback_data=f'price-month')],
                 [InlineKeyboardButton(text=f'6 месяцев', callback_data=f'price-6month')],
                 [InlineKeyboardButton(text=f'1 Год', callback_data=f'price-year')]]
        await update.callback_query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(board))

    async def buying_subscription(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.callback_query.answer()
        sum = self.prices_dict[update.callback_query.data.split('-')[1]]
        text = self.name_dict[update.callback_query.data.split('-')[1]]
        buy = payments.create_payment(summ=sum, description=f'{text}')
        hours = self.hours_dict[update.callback_query.data.split('-')[1]]
        keyb = InlineKeyboardMarkup([[InlineKeyboardButton(text=f'{sum} Рублей за {text}', url=buy[0])],
                                     [InlineKeyboardButton(text='Проверить оплату', callback_data=f'checkoplata__{buy[1]}__{hours}')],
                                     [InlineKeyboardButton(text='К выбору подписки', callback_data='backbuttonsub')]])
        await update.callback_query.message.edit_reply_markup(keyb)

    async def applying_sub(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        id = update.callback_query.data.split('__')[1]
        if payments.get_payment_status(id):
            try:
                self.date_writer(update.effective_chat.id, id, int(update.callback_query.data.split('__')[2]), self.prices_dict[[k for k,v in self.hours_dict.items() if v == int(update.callback_query.data.split('__')[2])][0]])
            except Exception as _EX:
                logging.warning(_EX)
            logging.info(f"User {update.effective_chat.username}({update.effective_chat.id}) paid {int(update.callback_query.data.split('__')[2])//24} дней подписки(счет {id})")
            with open('userlist.json', 'rt', encoding='utf-8') as file:
                data = json.loads(file.read())
            try:
                data[str(update.effective_chat.id)][1] = data[str(update.effective_chat.id)][1] + int(update.callback_query.data.split('__')[2])
                with open('userlist.json', 'w', encoding='utf-8') as file:
                    json.dump(data, file, indent=4, ensure_ascii=False)
                await update.callback_query.message.delete()
                days = int(update.callback_query.data.split('__')[2])//24
                await update.callback_query.message.reply_text(f"Ты успешно оплатил подписку на {days}{' дня' if str(days)[-1] in ['2', '3', '4'] else ' день' if str(days)[-1] in ['1'] else ' дней'}")
            except KeyError:
                pass

    def is_group_chat(self, update: Update) -> bool:
        """
        Checks if the message was sent from a group chat
        """
        return update.effective_chat.type in [
            constants.ChatType.GROUP,
            constants.ChatType.SUPERGROUP
        ]

    async def is_user_in_group(self, update: Update, user_id: int) -> bool:
        """
        Checks if user_id is a member of the group
        """
        member = await update.effective_chat.get_member(user_id)
        return member.status in [
            constants.ChatMemberStatus.OWNER,
            constants.ChatMemberStatus.ADMINISTRATOR,
            constants.ChatMemberStatus.MEMBER
        ]

    async def is_allowed(self, chat_id: int, context: ContextTypes.DEFAULT_TYPE = None) -> bool:
        with open('userlist.json', 'rt', encoding='utf-8') as file:
            data = json.loads(file.read())
        try:
            user_info = data[str(chat_id)]
            if user_info[1] > 0:
                print(1)
                return True
            elif user_info[0] > 0:
                print(2)
                if user_info[0] == 1:
                    await context.bot.send_message(chat_id= chat_id, text=f'Закончились беспланые сообщения...')

                data[str(chat_id)][0] -= 1
                with open('userlist.json', 'w', encoding='utf-8') as file:
                    json.dump(data, file, indent=4, ensure_ascii=False)
                print(22)
                return True
            else:
                return False
        except KeyError:
            pass


    def date_writer(self, chat_id, pay_id, hours, summ):
        with open('subscriptions.json', 'rt', encoding='utf-8') as file:
            data = json.loads(file.read())
        data[str(pay_id)] = [str(chat_id), str(hours), str(summ),
                             f"{datetime.datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"]
        with open('subscriptions.json', 'w', encoding='utf-8') as file:
            json.dump(data, file, indent=4, ensure_ascii=False)


    def run(self):
        """
        Runs the bot indefinitely until the user presses Ctrl+C
        """
        application = ApplicationBuilder() \
            .token(self.config['token']) \
            .proxy_url(self.config['proxy']) \
            .get_updates_proxy_url(self.config['proxy']) \
            .build()

        application.add_handler(CommandHandler('reset', self.reset))
        application.add_handler(CommandHandler('start', self.help))
        application.add_handler(CommandHandler('image', self.image))
        application.add_handler(CommandHandler('word', self.word))
        application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, self.transcribe))
        application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), self.prompt))
        application.add_handler(InlineQueryHandler(self.inline_query, chat_types=[
            constants.ChatType.GROUP, constants.ChatType.SUPERGROUP
        ]))
        application.add_handler(CallbackQueryHandler(self.subscription, 'subscription'))
        application.add_handler(CallbackQueryHandler(self.buying_subscription, 'price-'))
        application.add_handler(CallbackQueryHandler(self.applying_sub, 'checkoplata__'))
        application.add_handler(CallbackQueryHandler(self.subscription, 'backbuttonsub'))
        application.add_error_handler(self.error_handler)

        application.run_polling()




async def task():
    while True:
        with open('userlist.json', 'r', encoding='utf-8') as file:
            data = json.loads(file.read())
        for i, v in data.items():
            if v[1] > 0:
                data[i][1] = v[1] - 1
        with open('userlist.json', 'w', encoding='utf-8') as file:
            json.dump(data, file, indent=4, ensure_ascii=False)
        await asyncio.sleep(3600)


loop = asyncio.get_event_loop()
loop.create_task(task())