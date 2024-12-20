from datetime import datetime
import pytz
import telebot
from bson import ObjectId
from telebot import types
import schedule
import time
from threading import Thread
from dotenv import load_dotenv
import os


# Load environment variables
load_dotenv()

TOKEN = os.getenv('TOKEN')
MONGO_URI = os.getenv('MONGO_URI')
DB_NAME = os.getenv('DB_NAME')
PROVIDER_TOKEN = os.getenv('PROVIDER_TOKEN')
NGROK_BASE_URL = os.getenv('NGROK_BASE_URL')

bot = telebot.TeleBot(TOKEN)
from pymongo import MongoClient

# Connect to the MongoDB server
client = MongoClient(MONGO_URI)
db = client[DB_NAME]
orders_collection = db.orders

@bot.message_handler(commands=['clear'])
def clear_chat(message):
    bot.send_message(message.chat.id, "New message without buttons.")


@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = types.InlineKeyboardMarkup()
    button = types.InlineKeyboardButton(text="Order Food", callback_data="openapp")
    markup.add(button)
    bot.send_message(message.chat.id, "Вітаю! натисніть щоб замовити піцу", reply_markup=markup)


# Define handler for the /inform command with inline button
@bot.message_handler(commands=['inform'])
def send_information(message):
    markup = types.InlineKeyboardMarkup()
    button = types.InlineKeyboardButton(text="Отримати фото", callback_data="send_photo")
    markup.add(button)
    bot.send_message(message.chat.id, "Натисніть на кнопку, щоб отримати фото:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data == "send_photo")
def send_photo(call):
    bot.send_photo(call.message.chat.id, photo=open('photo.jpg', 'rb'))


# # Define handler for 3-button keyboard
# @bot.message_handler(commands=['three_buttons'])
# def three_buttons(message):
#     markup = types.ReplyKeyboardMarkup(row_width=3)
#     button1 = types.KeyboardButton("Кнопка 1")
#     button2 = types.KeyboardButton("Кнопка 2")
#     button3 = types.KeyboardButton("Кнопка 3")
#     markup.add(button1, button2, button3)
#     bot.send_message(message.chat.id, "Оберіть опцію:", reply_markup=markup)
#
#
# # Define handler for 4-button keyboard
# @bot.message_handler(commands=['four_buttons'])
# def four_buttons(message):
#     markup = types.ReplyKeyboardMarkup()
#     button1 = types.KeyboardButton("Кнопка 1")
#     button2 = types.KeyboardButton("Кнопка 2")
#     button3 = types.KeyboardButton("Кнопка 3")
#     button4 = types.KeyboardButton("Кнопка 4")
#     markup.row(button1, button2, button3,)
#     markup.row(button4)
#     bot.send_message(message.chat.id, "Оберіть опцію:", reply_markup=markup)


# # Define handler for 5-button keyboard
# @bot.message_handler(commands=['five_buttons'])
# def five_buttons(message):
#     markup = types.ReplyKeyboardMarkup()
#     button1 = types.KeyboardButton("Кнопка 1")
#     button2 = types.KeyboardButton("Кнопка 2")
#     button3 = types.KeyboardButton("Кнопка 3")
#     button4 = types.KeyboardButton("Кнопка 4")
#     button5 = types.KeyboardButton("Кнопка 5")
#     markup.row(button1, button2, button3)
#     markup.row(button4, button5)
#     bot.send_message(message.chat.id, "Оберіть опцію:", reply_markup=markup)


@bot.message_handler(commands=['openapp'])
def open_app(message):
    chat_id = message.chat.id
    base_url = NGROK_BASE_URL
    url_with_chat_id = f"{base_url}?chat_id={chat_id}"  # Append chat_id as a query parameter
    web_app_url = types.WebAppInfo(url=url_with_chat_id)
    button = types.InlineKeyboardButton(text="Open Mini App", web_app=web_app_url)
    markup = types.InlineKeyboardMarkup()
    markup.add(button)
    bot.send_message(chat_id, "Click the button to open the mini-app:", reply_markup=markup)


@bot.message_handler(commands=['admin'])
def open_admin_page(message):
    chat_id = message.chat.id
    base_url = NGROK_BASE_URL+'/admin'
    url_with_chat_id = f"{base_url}?chat_id={chat_id}"  # Append chat_id as a query parameter
    web_app_url = types.WebAppInfo(url=url_with_chat_id)
    button = types.InlineKeyboardButton(text="Open Admin page", web_app=web_app_url)
    markup = types.InlineKeyboardMarkup()
    markup.add(button)
    bot.send_message(chat_id, "Click the button to open admin page:", reply_markup=markup)

@bot.pre_checkout_query_handler(func=lambda query: True)
def checkout(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@bot.message_handler(content_types=['successful_payment'])
def handle_payment(message):
    # Retrieve the order ID from the invoice payload and convert it back to ObjectId
    order_id_str = message.successful_payment.invoice_payload
    order_id = ObjectId(order_id_str)  # Convert string to ObjectId

    # Fetch the order from the database to ensure it exists
    order = orders_collection.find_one({"_id": order_id})

    if order:
        print(f"Payment received: {message.successful_payment.total_amount / 100} {message.successful_payment.currency}")

        # Update the existing order in the database
        orders_collection.update_one(
            {"_id": order_id},
            {"$set": {
                "status": "paid",
                "total_amount": message.successful_payment.total_amount / 100,
                "currency": message.successful_payment.currency,
                "payment_date": datetime.now(pytz.utc)
            }}
        )
        bot.reply_to(message, "Thank you for your payment!")
    else:
        # Handle case where order is not found
        bot.reply_to(message, "Order not found or already processed.")


@bot.callback_query_handler(func=lambda call: True)
def handle_query(call):
    print(call)
    bot.send_message(call.message.chat.id, "Received: " + call.data)

@bot.message_handler(content_types=['text'])
def handle_text(message):
    bot.send_message(message.chat.id, "Received: " + message.text)


def check_pending_payments():
    pending_orders = orders_collection.find({'status': 'pending_payment'})
    for order in pending_orders:
        # Convert ObjectId to string explicitly
        order_id_str = str(order['_id'])

        prices = [types.LabeledPrice(label='Pizza', amount=int(order['total_amount'] * 100))]
        bot.send_invoice(
            chat_id=order['user_id'],
            title='Order Payment',
            description='Payment for your Pizza Order',
            provider_token=PROVIDER_TOKEN,
            currency='USD',
            prices=prices,
            start_parameter='time-machine-example',
            invoice_payload=order_id_str
        )
        orders_collection.update_one({'_id': order['_id']}, {'$set': {'status': 'payment_initiated'}})

schedule.every(1).seconds.do(check_pending_payments)

def run_bot():
    while True:
        schedule.run_pending()
        time.sleep(0.5)  # Shorter sleep time for more frequent checks

if __name__ == "__main__":
    thread = Thread(target=run_bot)
    thread.start()
    bot.infinity_polling(none_stop=True)