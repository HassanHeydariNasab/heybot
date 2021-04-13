from typing import Union
import re
import logging
from random import choice
from redis import Redis
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
from configs import TOKEN, REQUEST_KWARGS


updater = Updater(
    token=TOKEN,
    use_context=True,
    request_kwargs=REQUEST_KWARGS,
)
dispatcher = updater.dispatcher

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

r = Redis(host="localhost", port=6379, db=1)

# call the bot
PREFIX = "hey "
# status of bot in a chat
IDLE = "IDLE"
LEARNING_QUESTION = "LEARNING_QUESTION"
LEARNING_ANSWER = "LEARNING_ANSWER"


def start(update, context):
    context.bot.send_message(
        chat_id=update.effective_chat.id, text="I'm a bot, please talk to me!"
    )


def learn(update, context):
    context.chat_data["status"] = LEARNING_QUESTION
    context.bot.send_message(
        chat_id=update.effective_chat.id, text="To what question should I answer?"
    )


def cancel(update, context):
    context.chat_data["status"] = IDLE
    context.bot.send_message(chat_id=update.effective_chat.id, text="Canceled.")


def message(update, context):
    if (
        update.message.chat.type != "private"
        and update.message.text[: len(PREFIX)] != PREFIX
    ):
        return
    if update.message.text[: len(PREFIX)] == PREFIX:
        update.message.text = update.message.text[len(PREFIX) :]
    if "status" not in context.chat_data:
        context.chat_data["status"] = IDLE

    if context.chat_data["status"] == LEARNING_QUESTION:
        if update.message.text[0] == "^":
            try:
                re.compile(update.message.text)
            except re.error:
                context.bot.send_message(
                    chat_id=update.effective_chat.id, text="Invalid Regex!"
                )
                return
        context.chat_data["question"] = update.message.text
        context.chat_data["status"] = LEARNING_ANSWER
        context.bot.send_message(
            chat_id=update.effective_chat.id, text="Then what should I say?"
        )
    elif context.chat_data["status"] == LEARNING_ANSWER:
        r.set(context.chat_data["question"], update.message.text)
        context.chat_data["status"] = IDLE
        context.chat_data["question"] = ""
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=choice(["OK", "I got it!", "I learned it."]),
        )
    elif context.chat_data["status"] == IDLE:
        regexes = r.keys("^*")
        print("regexes", regexes)
        _match: Union[re.Match, None] = None
        for regex in regexes:
            _match = re.match(regex.decode(), update.message.text)
            if _match is not None:
                break
        if _match is None:
            # non-regex question/answer
            answer_bytes: Union[bytes, None] = r.get(update.message.text)
            if answer_bytes is None:
                answer = "What?"
            else:
                answer = answer_bytes.decode()
        else:
            groups: dict = _match.groupdict()
            answer_bytes: Union[bytes, None] = r.get(regex)
            if answer_bytes is None:
                answer = "What?"
            else:
                answer = answer_bytes.decode()
                answer = answer.format(**groups)

        context.bot.send_message(chat_id=update.effective_chat.id, text=answer)


dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("learn", learn))
dispatcher.add_handler(CommandHandler("cancel", cancel))
dispatcher.add_handler(MessageHandler(Filters.text & (~Filters.command), message))
updater.start_polling()