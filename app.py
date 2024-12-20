import os
import traceback
import joblib
import numpy as np
import pandas as pd
import pytz
import requests
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
from flask_pymongo import PyMongo
from datetime import datetime, timedelta
from dotenv import load_dotenv


load_dotenv()
app = Flask(__name__)
CORS(app)  # Handle CORS

EXCHANGE_URL = os.getenv('EXCHANGE_URL')
app.config["MONGO_URI"] = os.getenv('MONGO_URI')
mongo = PyMongo(app)
model = joblib.load(os.getenv('MODEL_PATH'))
scaler = joblib.load(os.getenv('SCALER_PATH'))


@app.after_request
def add_security_headers(resp):
    script_sources = "'self' https://cdn.ngrok.com https://code.jquery.com https://cdn.jsdelivr.net 'unsafe-eval' 'unsafe-inline'"
    style_sources = "'self' https://fonts.googleapis.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net 'unsafe-inline'"
    font_sources = "'self' https://fonts.gstatic.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com data:"

    # Combining CSP policies
    csp_policy = f"default-src 'self'; script-src {script_sources}; style-src {style_sources}; font-src {font_sources};"

    resp.headers['Content-Security-Policy'] = csp_policy
    return resp

@app.route('/')
def index():
    chat_id = request.args.get('chat_id')  # Extract chat_id from query parameters
    if chat_id:
        # Optionally, you can store this chat_id in session or pass it to the template
        return render_template('index.html', chat_id=chat_id)
    else:
        return "Chat ID is missing", 400  # Handle cases where chat_id is not provided


@app.route('/api/products')
def get_products():
    products_cursor = mongo .db.pizzas.find({}, {'_id': False})
    products_list = list(products_cursor)
    return jsonify(products_list)
@app.route('/api/place-order', methods=['POST'])
def place_order():
    data = request.json
    user_id = data['user_id']
    total_amount = data['total_amount']
    currency = data['currency']
    items = data['items']

    # Create a new order
    order = {
        'user_id': user_id,
        'total_amount': total_amount,
        'currency': currency,
        'items': items,
        'status': 'pending_payment',
        'order_date': datetime.now(pytz.utc)  # Store the current UTC time as order_date
    }

    # Insert the new order into the database
    result = mongo.db.orders.insert_one(order)
    order_id = result.inserted_id

    # Update the order to include the order_date
    mongo.db.orders.update_one(
        {'_id': order_id},
        {'$set': {
            'status': 'pending_payment',
            'order_date': datetime.now(pytz.utc)  # Update the order_date to the current UTC time
        }}
    )

    return jsonify({'success': True, 'order_id': str(order_id)})

def get_sales_data():
    # Using Flask-PyMongo to interact with the Mongo database
    sales_data = mongo.db.fake_orders_transformed.aggregate([
        {"$group": {"_id": "$order_date", "count": {"$sum": 1}}}
    ])
    return [{'date': str(entry['_id']), 'orders': entry['count']} for entry in sales_data]


@app.route('/admin')
def home():
    sales_data = get_sales_data()
    pizza_cursor = mongo.db.pizzas.find({}, {'_id': False})
    pizzas = list(pizza_cursor)  # Convert cursor to list
    return render_template('admin.html', sales_data=sales_data, pizzas=pizzas)


@app.route('/update_pizzas', methods=['POST'])
def update_pizzas():
    try:
        # Extracting JSON data directly
        new_pizzas = request.get_json()['pizzas']  # Getting JSON directly
        if isinstance(new_pizzas, list):
            mongo.db.pizzas.delete_many({})
            mongo.db.pizzas.insert_many(new_pizzas)
            return jsonify({'success': True, 'message': 'Pizzas updated successfully'})
        else:
            return jsonify({'success': False, 'message': 'Invalid pizza data received'}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/exchange-rate')
def get_exchange_rate():
    response = requests.get(EXCHANGE_URL)
    data = response.json()
    uah_rate = data['rates']['UAH']
    return jsonify({'rate': uah_rate})


@app.route('/predict', methods=['POST'])
def predict():
    try:
        # 1. Parse input data from request
        data = request.get_json()
        start_date = datetime.strptime(data['start'], '%B %d, %Y')
        end_date = datetime.strptime(data['end'], '%B %d, %Y')
        discounts = {key.split('_')[-1]: float(value) for key, value in data.items() if "discount" in key}

        # 2. Fetch pizzas from db
        pizza_cursor = mongo.db.pizzas.find({}, {'_id': False})
        pizzas = list(pizza_cursor)

        # 3. Calculate final prices
        pizza_prices = {pizza['name']: pizza['price'] * (1 - discounts.get(pizza['name'], 0)) for pizza in pizzas}

        # 4. Fetch users from db
        users = fetch_users()

        # 5. Create records for predictions, 1 per day per user
        orders = generate_fake_records(users, start_date, end_date, pizza_prices)

        # 6. Calculate all the features and apply scaler
        processed_orders = process_features(orders)
        scaled_features = scaler.transform(processed_orders)

        # 7. Perform predictions
        predictions = model.predict(scaled_features)

        # 8. Send expected sales back to frontend
        predicted_sales = sum(predictions)
        predicted_sales = int(predicted_sales)
        return jsonify({'predicted_sales': predicted_sales}), 200

    except Exception as e:
        traceback_details = traceback.format_exc()
        print(traceback_details)
        return jsonify({'error': 'Unable to process the request', 'trace': traceback_details}), 500

def fetch_users():
    return list(mongo.db.fake_orders.distinct('username'))

def generate_fake_records(users, start, end, pizza_prices):
    orders = []
    for date in pd.date_range(start, end):
        for user in users:
            order = {
                'username': user,
                'order_date': date,
                'final_prices': pizza_prices,
                'dob': '2001-07-11',  # Example DOB, for simplicity
            }
            orders.append(order)
    return pd.DataFrame(orders)


def is_holiday(date):
    # Assuming holidays fall on the same date each year
    return date.strftime('%m-%d') in ['12-25', '01-01', '01-07']


def process_features(data_frame):
    # Convert 'order_date' to datetime
    data_frame['order_date'] = pd.to_datetime(data_frame['order_date'])

    # Extract month and day of the week from 'order_date'
    data_frame['month'] = data_frame['order_date'].dt.month
    data_frame['day_of_week'] = data_frame['order_date'].dt.dayofweek

    # Determine if the day is a holiday
    data_frame['is_holiday'] = data_frame['order_date'].apply(is_holiday).astype(int)

    # Determine if it's the user's birthday
    data_frame['is_birthday'] = data_frame.apply(lambda row: row['order_date'].strftime('%m-%d') == row['dob'][5:], axis=1).astype(int)

    # Calculate the average price of ordered pizzas
    data_frame['average_price'] = data_frame['final_prices'].apply(lambda prices: np.mean(list(prices.values())))

    # Select the features that were used in the model training
    return data_frame[['month', 'day_of_week', 'is_holiday', 'is_birthday', 'average_price']]


if __name__ == '__main__':
    app.run(ssl_context='adhoc', debug=True)  # Runs with HTTPS