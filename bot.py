#!/usr/bin/env python3
import logging
from time import sleep
import traceback
import sys
from html import escape

import pickledb

from telegram import ParseMode, TelegramError, Update
from telegram.ext import Updater, MessageHandler, CommandHandler, Filters
from telegram.ext.dispatcher import run_async

from config import BOTNAME, TOKEN

help_text = (
    "Приветствует всех, кто заходит в групповой чат,"
    "частью которого является этот бот. По умолчанию"
    "только тот, кто пригласил бота в группу, может "
    "изменять настройки.\nКоманды:\n\n"
    "/welcome - Установить приветственное сообщение\n"
    "/goodbye - Установить прощальное сообщение\n"
    "/disable\\_goodbye - Отключите прощальное сообщение\n"
    "/lock - Только человек, пригласивший бота, может изменять сообщения\n"
    "/unlock - Каждый может изменять сообщения\n"
    '/quiet - Отключите "Извините, только тот, кто..." '
    "и справочные сообщения\n"
    '/unquiet - Включить "Извините, только тот, кто..." '
    "и справочные сообщения\n\n"
    "Вы можете использовать $username и $title в качестве заполнителей "
    "при настройке сообщений.\n"
)

"""
Create database object
Database schema:
<chat_id> -> welcome message
<chat_id>_bye -> goodbye message
<chat_id>_adm -> user id of the user who invited the bot
<chat_id>_lck -> boolean if the bot is locked or unlocked
<chat_id>_quiet -> boolean if the bot is quieted

chats -> list of chat ids where the bot has received messages in.
"""
# Create database object
db = pickledb.load("bot.db", True)

if not db.get("chats"):
    db.set("chats", [])

# Set up logging
root = logging.getLogger()
root.setLevel(logging.INFO)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)


@run_async
def send_async(context, *args, **kwargs):
    context.bot.send_message(*args, **kwargs)


def check(update, context, override_lock=None):
    """
    Perform some checks on the update. If checks were successful, returns True,
    else sends an error message to the chat and returns False.
    """

    chat_id = update.message.chat_id
    chat_str = str(chat_id)

    if chat_id > 0:
        send_async(
            context, chat_id=chat_id, text="Пожалуйста, сначала добавьте меня в группу!",
        )
        return False

    locked = override_lock if override_lock is not None else db.get(chat_str + "_lck")

    if locked and db.get(chat_str + "_adm") != update.message.from_user.id:
        if not db.get(chat_str + "_quiet"):
            send_async(
                context,
                chat_id=chat_id,
                text="Извините, это может сделать только тот, кто меня пригласил.",
            )
        return False

    return True


# Welcome a user to the chat
def welcome(update, context, new_member):
    """ Welcomes a user to the chat """

    message = update.message
    chat_id = message.chat.id
    logger.info(
        "%s joined to chat %d (%s)",
        escape(new_member.first_name),
        chat_id,
        escape(message.chat.title),
    )

    # Pull the custom message for this chat from the database
    text = db.get(str(chat_id))

    # Use default message if there's no custom one set
    if text is None:
        text = "Привет $username! Добро пожаловать в $title 😊"

    # Replace placeholders and send message
    text = text.replace("$username", new_member.first_name)
    text = text.replace("$title", message.chat.title)
    send_async(context, chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)


# Welcome a user to the chat
def goodbye(update, context):
    """ Sends goodbye message when a user left the chat """

    message = update.message
    chat_id = message.chat.id
    logger.info(
        "%s left chat %d (%s)",
        escape(message.left_chat_member.first_name),
        chat_id,
        escape(message.chat.title),
    )

    # Pull the custom message for this chat from the database
    text = db.get(str(chat_id) + "_bye")

    # Goodbye was disabled
    if text is False:
        return

    # Use default message if there's no custom one set
    if text is None:
        text = "До свидания, $username!"

    # Replace placeholders and send message
    text = text.replace("$username", message.left_chat_member.first_name)
    text = text.replace("$title", message.chat.title)
    send_async(context, chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)


# Introduce the bot to a chat its been added to
def introduce(update, context):
    """
    Introduces the bot to a chat its been added to and saves the user id of the
    user who invited us.
    """

    chat_id = update.message.chat.id
    invited = update.message.from_user.id

    logger.info(
        "Приглашен %s to chat %d (%s)", invited, chat_id, update.message.chat.title,
    )

    db.set(str(chat_id) + "_adm", invited)
    db.set(str(chat_id) + "_lck", True)

    text = (
        f"Привет {update.message.chat.title}! "
        "Теперь я буду приветствовать любого, кто присоединится к этому чату, "
        "приятным сообщением. 😊 \nПроверьте команду /help для получения дополнительной информации!"
    )
    send_async(context, chat_id=chat_id, text=text)


# Print help text
def help(update, context):
    """ Prints help text """

    chat_id = update.message.chat.id
    chat_str = str(chat_id)
    if (
        not db.get(chat_str + "_quiet")
        or db.get(chat_str + "_adm") == update.message.from_user.id
    ):
        send_async(
            context,
            chat_id=chat_id,
            text=help_text,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )


# Set custom message
def set_welcome(update, context):
    """ Sets custom welcome message """

    chat_id = update.message.chat.id

    # Check admin privilege and group context
    if not check(update, context):
        return

    # Split message into words and remove mentions of the bot
    message = update.message.text.partition(" ")[2]

    # Only continue if there's a message
    if not message:
        send_async(
            context,
            chat_id=chat_id,
            text="Вам нужно отправить сообщение! Например:\n"
            "<code>/welcome Привет $username, Добро Пожаловать в "
            "$title!</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    # Put message into database
    db.set(str(chat_id), message)

    send_async(context, chat_id=chat_id, text="Сделано!")


# Set custom message
def set_goodbye(update, context):
    """ Enables and sets custom goodbye message """

    chat_id = update.message.chat.id

    # Check admin privilege and group context
    if not check(update, context):
        return

    # Split message into words and remove mentions of the bot
    message = update.message.text.partition(" ")[2]

    # Only continue if there's a message
    if not message:
        send_async(
            context,
            chat_id=chat_id,
            text="Вам нужно отправить сообщение! Например:\n"
            "<code>/goodbye До свидания, $username!</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    # Put message into database
    db.set(str(chat_id) + "_bye", message)

    send_async(context, chat_id=chat_id, text="Сделано!")


def disable_goodbye(update, context):
    """ Disables the goodbye message """

    chat_id = update.message.chat.id

    # Check admin privilege and group context
    if not check(update, context):
        return

    # Disable goodbye message
    db.set(str(chat_id) + "_bye", False)

    send_async(context, chat_id=chat_id, text="Сделано!")


def lock(update, context):
    """ Locks the chat, so only the invitee can change settings """

    chat_id = update.message.chat.id

    # Check admin privilege and group context
    if not check(update, context, override_lock=True):
        return

    # Lock the bot for this chat
    db.set(str(chat_id) + "_lck", True)

    send_async(context, chat_id=chat_id, text="Сделано!")


def quiet(update, context):
    """ Quiets the chat, so no error messages will be sent """

    chat_id = update.message.chat.id

    # Check admin privilege and group context
    if not check(update, context, override_lock=True):
        return

    # Lock the bot for this chat
    db.set(str(chat_id) + "_quiet", True)

    send_async(context, chat_id=chat_id, text="Сделано!")


def unquiet(update, context):
    """ Unquiets the chat """

    chat_id = update.message.chat.id

    # Check admin privilege and group context
    if not check(update, context, override_lock=True):
        return

    # Lock the bot for this chat
    db.set(str(chat_id) + "_quiet", False)

    send_async(context, chat_id=chat_id, text="Сделано!")


def unlock(update, context):
    """ Unlocks the chat, so everyone can change settings """

    chat_id = update.message.chat.id

    # Check admin privilege and group context
    if not check(update, context):
        return

    # Unlock the bot for this chat
    db.set(str(chat_id) + "_lck", False)

    send_async(context, chat_id=chat_id, text="Сделано!")


def empty_message(update, context):
    """
    Empty messages could be status messages, so we check them if there is a new
    group member, someone left the chat or if the bot has been added somewhere.
    """

    # Keep chatlist
    chats = db.get("chats")

    if update.message.chat.id not in chats:
        chats.append(update.message.chat.id)
        db.set("chats", chats)
        logger.info("Меня добавили %d чатов" % len(chats))

    if update.message.new_chat_members:
        for new_member in update.message.new_chat_members:
            # Bot was added to a group chat
            if new_member.username == BOTNAME:
                return introduce(update, context)
            # Another user joined the chat
            else:
                return welcome(update, context, new_member)

    # Someone left the chat
    elif update.message.left_chat_member is not None:
        if update.message.left_chat_member.username != BOTNAME:
            return goodbye(update, context)


def error(update, context, **kwargs):
    """ Error handling """
    error = context.error

    try:
        if isinstance(error, TelegramError) and (
            error.message == "Неавторизованный"
            or error.message == "Нет прав на отправку сообщения"
            or "PEER_ID_INVALID" in error.message
        ):
            chats = db.get("chats")
            chats.remove(update.message.chat_id)
            db.set("chats", chats)
            logger.info("Удаленный chat_id %s из списка чатов" % update.message.chat_id)
        else:
            logger.error("Произошла (%s) ошибка: %s" % (type(error), error.message))
    except:
        pass


def main():
    # Create the Updater and pass it your bot's token.
    updater = Updater(TOKEN, workers=10, use_context=True)

    # Get the dispatcher to register handlers
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", help))
    dp.add_handler(CommandHandler("help", help))
    dp.add_handler(CommandHandler("welcome", set_welcome))
    dp.add_handler(CommandHandler("goodbye", set_goodbye))
    dp.add_handler(CommandHandler("disable_goodbye", disable_goodbye))
    dp.add_handler(CommandHandler("lock", lock))
    dp.add_handler(CommandHandler("unlock", unlock))
    dp.add_handler(CommandHandler("quiet", quiet))
    dp.add_handler(CommandHandler("unquiet", unquiet))

    dp.add_handler(MessageHandler(Filters.status_update, empty_message))

    dp.add_error_handler(error)

    updater.start_polling(timeout=30, clean=True)
    updater.idle()


if __name__ == "__main__":
    main()
