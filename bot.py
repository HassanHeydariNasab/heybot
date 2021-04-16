import logging
import re
import sys
from random import choice
from typing import Union

from redis import Redis
from telegram.ext import CommandHandler, Filters, MessageHandler, Updater

from configs import (
    REQUEST_KWARGS,
    TOKEN,
    WEBHOOK_URL,
    SSL_CERTIFICATE,
    LISTEN,
    PORT,
    BOT_USERNAME,
    ADMIN_ID,
)

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
r2 = Redis(host="localhost", port=6379, db=2)

# call the bot
PREFIXES = ["hey ", "Hey ", "hoy ", "Hoy ", "هوی ", "هوي "]
# status of bot in a chat
IDLE = "IDLE"
LEARNING_QUESTION = "LEARNING_QUESTION"
LEARNING_ANSWER = "LEARNING_ANSWER"
FORGET = "FORGET"


def compile_regexes(context):
    context.bot_data["regexes"]: list[tuple[str, re.Pattern]] = []
    regexes = r.keys("^*")
    for regex in regexes:
        context.bot_data["regexes"].append((regex.decode(), re.compile(regex.decode())))


def start(update, context):
    r2.set(update.effective_chat.id, str(update.effective_chat))
    r2.incr("starts")
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Hello {first_name}! I'm a bot, please talk to me and teach me to talk".format(
            first_name=update.effective_chat.first_name
        ),
    )


def learn(update, context):
    context.chat_data["status"] = LEARNING_QUESTION
    context.bot.send_message(
        chat_id=update.effective_chat.id, text="To what question should I answer?"
    )


def cancel(update, context):
    context.chat_data["status"] = IDLE
    context.bot.send_message(chat_id=update.effective_chat.id, text="Canceled.")


def list_(update, context):
    questions = r.keys("*")
    questions_lines: str = ""
    for question in questions:
        questions_lines += question.decode() + "\n\n"
    context.bot.send_message(chat_id=update.effective_chat.id, text=questions_lines)


def forget(update, context):
    context.chat_data["status"] = FORGET
    context.bot.send_message(
        chat_id=update.effective_chat.id, text="What should I forget?"
    )


def stats(update, context):
    if update.effective_chat.id != ADMIN_ID:
        return
    keys: list = r2.keys("*")
    text = ""
    for key in keys:
        text += key.decode() + ": " + r2.get(key).decode() + "\n"
    context.bot.send_message(chat_id=update.effective_chat.id, text=text)


def on_new_chat_member(update, context):
    for member in update.message.new_chat_members:
        if member.username == BOT_USERNAME:
            r2.set(update.effective_chat.id, str(update.effective_chat))
            r2.incr("joins")
            if update.effective_chat.type != "private":
                context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="Hello everyone :)\nSay Hey hello\nYou can teach me to talk",
                )


def on_left_chat_member(update, context):
    if update.message.left_chat_member["username"] == BOT_USERNAME:
        r2.delete(update.effective_chat.id)
        r2.incr("lefts")


def message(update, context):
    if update.message.text + " " in PREFIXES:
        pass
    elif update.message.chat.type != "private" and (
        update.message.text[:4] not in PREFIXES
    ):
        return
    if update.message.text[:4] in PREFIXES:
        update.message.text = update.message.text[4:]
    if "status" not in context.chat_data:
        context.chat_data["status"] = IDLE

    if context.chat_data["status"] == IDLE:
        if "regexes" not in context.bot_data:
            compile_regexes(context=context)
        matched: Union[re.Match, None] = None
        for regex in context.bot_data["regexes"]:
            matched = regex[1].match(update.message.text)
            if matched is not None:
                break
        if matched is None:
            # non-regex question/answer
            answer_bytes: Union[bytes, None] = r.get(update.message.text)
            if answer_bytes is None:
                answer = "What?"
            else:
                answer = answer_bytes.decode()
        else:
            groups: dict = matched.groupdict()
            answer_bytes: Union[bytes, None] = r.get(regex[0])
            # A rare case when redis and context.bot_data["regexes"] are out of sync
            if answer_bytes is None:
                compile_regexes(context=context)
                answer = "What? I can't remember well"
            else:
                answer = answer_bytes.decode()
                answer = answer.format(**groups)

        context.bot.send_message(chat_id=update.effective_chat.id, text=answer)

    elif context.chat_data["status"] == LEARNING_QUESTION:
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
        if context.chat_data["question"][0] == "^":
            compile_regexes(context=context)
        context.chat_data["status"] = IDLE
        context.chat_data["question"] = ""
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=choice(["OK", "I got it!", "I learned it."]),
        )

    elif context.chat_data["status"] == FORGET:
        context.chat_data["status"] = IDLE
        number_of_deleted = r.delete(update.message.text)
        if number_of_deleted == 0:
            context.bot.send_message(
                chat_id=update.effective_chat.id, text="Not found!"
            )
        elif number_of_deleted == 1:
            context.bot.send_message(
                chat_id=update.effective_chat.id, text="I forgot it!"
            )


dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("learn", learn))
dispatcher.add_handler(CommandHandler("list", list_))
dispatcher.add_handler(CommandHandler("forget", forget))
dispatcher.add_handler(CommandHandler("cancel", cancel))
dispatcher.add_handler(CommandHandler("stats", stats))
dispatcher.add_handler(MessageHandler(Filters.text & (~Filters.command), message))
dispatcher.add_handler(
    MessageHandler(Filters.status_update.new_chat_members, on_new_chat_member)
)
dispatcher.add_handler(
    MessageHandler(Filters.status_update.left_chat_member, on_left_chat_member)
)
if "--webhook" in sys.argv:
    updater.start_webhook(
        listen=LISTEN,
        port=PORT,
        url_path=TOKEN,
        webhook_url=WEBHOOK_URL,
        cert=open(SSL_CERTIFICATE, "rb"),
    )
else:
    updater.start_polling()
