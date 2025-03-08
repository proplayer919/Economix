from flask import Flask, request, jsonify, session, render_template
from flask_cors import CORS
from uuid import uuid4
import time
import random
import json
import os

app = Flask(__name__)
CORS(app)
app.secret_key = os.getenv('FLASK_SECRET_KEY')

# File paths for JSON "databases"
USERS_FILE = 'users.json'
ITEMS_FILE = 'items.json'

ITEM_CREATE_COOLDOWN = 60 # 60 seconds
TOKEN_MINE_COOLDOWN = 60 * 10 # 10 minutes

# Helper functions to load/save JSON data.
def load_json(filepath):
    if os.path.exists(filepath):
        with open(filepath, 'r') as f:
            return json.load(f)
    return {}

def save_json(filepath, data):
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=4)

def load_users():
    return load_json(USERS_FILE)

def save_users(users):
    save_json(USERS_FILE, users)

def load_items():
    return load_json(ITEMS_FILE)

def save_items(items):
    save_json(ITEMS_FILE, items)

# Load databases at startup.
users = load_users()  # key: user_id, value: dict with tokens, last_item_time, items list
items = load_items()  # key: item_id, value: dict with name, icon, owner, sale status, price, created_at

# Automatically assign a unique user id if one doesn't exist.
@app.before_request
def assign_user():
    global users
    if 'user_id' not in session:
        user_id = str(uuid4())
        session['user_id'] = user_id
        users[user_id] = {
            'tokens': 100,      # Starting tokens for the user.
            'last_item_time': 0,
            'last_mine_time': 0,
            'items': []
        }
        save_users(users)

# Data used for random item generation.
adjectives = ["Ancient", "Mystic", "Enchanted", "Cursed", "Legendary"]
materials = ["Iron", "Gold", "Diamond", "Ruby", "Emerald", "Sapphire", "Opal", "Mythril", "Adamantium"]
nouns = ["Sword", "Shield", "Amulet", "Helmet", "Ring", "Boots", "Gloves"]
special = ["of the Gods", "of the Dark", "of the Light", "of the Stars", "of the Moon", "of the Sun"]
icons = ["⚔️", "🛡️", "💍", "🏹", "🔮", "🧿", "🥇", "✨", "🔥", "⭐", "🚀"]

def generate_item():
    """Generate a new item with a random name and icon."""
    try:
        name = f"{random.choice(adjectives)} {random.choice(materials)} {random.choice(nouns)} {random.choice(special)} #{random.randint(1, 9999)}"
        icon = random.choice(icons)
        item_id = str(uuid4())
        item_secret = str(uuid4())
    except Exception as e:
        raise RuntimeError(f"Error generating item: {str(e)}")

    return {
        "id": item_id,
        "item_secret": item_secret,
        "name": name,
        "icon": icon,
        "for_sale": False,
        "price": 0,
        "created_at": int(time.time())
    }

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/account', methods=['GET'])
def get_account():
    user_id = session['user_id']
    user = users.get(user_id)
    return jsonify({
        'tokens': user['tokens'],
        'items': user['items'],
        'last_item_time': user['last_item_time'],
        'last_mine_time': user['last_mine_time']
    })

@app.route('/api/create_item', methods=['POST'])
def create_item():
    global users, items
    user_id = session['user_id']
    user = users.get(user_id)
    now = time.time()
    if now - user['last_item_time'] < ITEM_CREATE_COOLDOWN:
        remaining = ITEM_CREATE_COOLDOWN - (now - user['last_item_time'])
        return jsonify({"error": "Cooldown active", "remaining": remaining}), 400

    if user['tokens'] < 10:
        return jsonify({"error": "Not enough tokens"}), 400

    new_item = generate_item()
    new_item['owner'] = user_id
    items[new_item['id']] = new_item
    user['items'].append(new_item)
    user['last_item_time'] = now
    user['tokens'] -= 10

    # Save changes to JSON files.
    save_items(items)
    save_users(users)
    
    return jsonify(new_item)
  
@app.route('/api/mine_tokens', methods=['POST'])
def mine_tokens():
    user_id = session['user_id']
    user = users.get(user_id)
    now = time.time()
    if now - user['last_mine_time'] < TOKEN_MINE_COOLDOWN:
        remaining = TOKEN_MINE_COOLDOWN - (now - user['last_mine_time'])
        return jsonify({"error": "Cooldown active", "remaining": remaining}), 400

    tokens_mined = random.randint(5, 10)
    user['tokens'] += tokens_mined
    user['last_mine_time'] = now

    save_users(users)
    return jsonify({"success": True, "tokens_mined": tokens_mined})
  
@app.route('/api/take_item', methods=['POST'])
def take_item():
    data = request.get_json()
    item_secret = data.get('item_secret')
    new_owner = session['user_id']
    if not item_secret:
        return jsonify({"error": "Missing item_secret"}), 400
    
    if users[new_owner]['tokens'] < 10:
        return jsonify({"error": "Not enough tokens"}), 400
    
    for item in items.values():
        if item['item_secret'] == item_secret:
            old_owner = item['owner']
            users[old_owner]['items'] = [i for i in users[old_owner]['items'] if i['id'] != item['id']]
            users[new_owner]['items'].append(item)
            users[new_owner]['tokens'] -= 10
            save_users(users)
            item['owner'] = new_owner
            item['item_secret'] = str(uuid4())
            save_items(items)
            return jsonify({"success": True, "item": item})
    
    return jsonify({"error": "Item not found"}), 404

@app.route('/api/market', methods=['GET'])
def market():
    user_id = session['user_id']
    market_items = [item for item in items.values() if item['for_sale'] and item['owner'] != user_id]
    market_items = [{key: value for key, value in item.items() if key != 'item_secret'} for item in market_items]
    return jsonify(market_items)

@app.route('/api/sell_item', methods=['POST'])
def sell_item():
    global users, items
    data = request.get_json()
    item_id = data.get('item_id')
    price = data.get('price')
    if not item_id or price is None:
        return jsonify({"error": "Missing item_id or price"}), 400

    user_id = session['user_id']
    item = items.get(item_id)
    if not item or item['owner'] != user_id:
        return jsonify({"error": "Item not found or not owned"}), 404

    # List the item for sale at the specified price.
    item['for_sale'] = True
    item['price'] = price

    save_items(items)
    return jsonify({"success": True, "item": item})

@app.route('/api/buy_item', methods=['POST'])
def buy_item():
    global users, items
    data = request.get_json()
    item_id = data.get('item_id')
    if not item_id:
        return jsonify({"error": "Missing item_id"}), 400

    user_id = session['user_id']
    buyer = users.get(user_id)
    item = items.get(item_id)
    if not item or not item['for_sale']:
        return jsonify({"error": "Item not available"}), 404
    if buyer['tokens'] < item['price']:
        return jsonify({"error": "Not enough tokens"}), 400

    # Process the purchase: transfer tokens and change ownership.
    seller_id = item['owner']
    seller = users.get(seller_id)
    buyer['tokens'] -= item['price']
    seller['tokens'] += item['price']

    # Remove the item from the seller's list.
    seller['items'] = [i for i in seller['items'] if i['id'] != item_id]

    # Transfer ownership to the buyer and remove sale status.
    item['owner'] = user_id
    item['for_sale'] = False
    item['price'] = 0
    buyer['items'].append(item)

    # Save changes.
    save_users(users)
    save_items(items)

    return jsonify({"success": True, "item": item})

if __name__ == '__main__':
    app.run(debug=False)
