import os
import json
import time
import random
import logging
from uuid import uuid4
from logging.handlers import RotatingFileHandler
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash
from waitress import serve
from functools import wraps
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

# Initialize Flask application
app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get('FLASK_SECRET_KEY', '1234'),
    WTF_CSRF_ENABLED=True,
    WTF_CSRF_TIME_LIMIT=3600
)

# Security middleware
CORS(app, origins=os.environ.get('CORS_ORIGINS', '').split(','))
csrf = CSRFProtect(app)

# Configure logging
handler = RotatingFileHandler(
    'app.log',
    maxBytes=1024 * 1024 * 10,  # 10 MB
    backupCount=5
)
handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
))
app.logger.addHandler(handler)
app.logger.setLevel(logging.INFO)

# MongoDB configuration
client = MongoClient(os.environ.get('MONGODB_URI'))
db = client.get_database(os.environ.get('MONGODB_DB'))

# Collections
users_collection = db.users
items_collection = db.items
messages_collection = db.messages
rooms_collection = db.rooms

# Create indexes
users_collection.create_index([('username', ASCENDING)], unique=True)
items_collection.create_index([('id', ASCENDING)], unique=True)
messages_collection.create_index([('room', ASCENDING), ('timestamp', DESCENDING)])
rooms_collection.create_index([('name', ASCENDING)], unique=True)

# Configuration constants
ITEM_CREATE_COOLDOWN = int(os.environ.get('ITEM_CREATE_COOLDOWN', 60))
TOKEN_MINE_COOLDOWN = int(os.environ.get('TOKEN_MINE_COOLDOWN', 600))
MAX_ITEM_PRICE = 10000
MIN_ITEM_PRICE = 1

# Item generation constants
try:
    with open('words/adjectives.json', 'r') as f:
        ADJECTIVES = json.load(f)
    with open('words/materials.json', 'r') as f:
        MATERIALS = json.load(f)
    with open('words/nouns.json', 'r') as f:
        NOUNS = json.load(f)
    with open('words/suffixes.json', 'r') as f:
        SUFFIXES = json.load(f)
    app.logger.info("Loaded item generation word lists successfully")
except Exception as e:
    app.logger.critical(f"Failed to load word lists: {str(e)}")
    raise

# Authentication middleware
@app.before_request
def authenticate_user():
    if request.method == 'OPTIONS' or request.endpoint in ['register', 'login', 'restore_account', 'index', 'static_file', 'view_logs', 'get_stats']:
        return

    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        app.logger.warning("Missing or invalid Authorization header")
        return jsonify({"error": "Missing or invalid Authorization header"}), 401
    
    token = auth_header.split(' ')[1]
    user = users_collection.find_one({'token': token})
    if user:
        request.username = user['username']
        request.user_type = user.get('type', 'user')
        return
    
    app.logger.warning("Invalid token provided")
    return jsonify({"error": "Invalid token"}), 401

# Admin requirement decorator
def requires_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = users_collection.find_one({'username': request.username})
        if user.get('type') != 'admin':
            app.logger.warning(f"Admin privileges required for user: {request.username}")
            return jsonify({"error": "Admin privileges required"}), 403
        return f(*args, **kwargs)
    return decorated

# Mod requirement decorator
def requires_mod(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = users_collection.find_one({'username': request.username})
        if user.get('type') not in ['admin', 'mod']:
            app.logger.warning(f"Mod privileges required for user: {request.username}")
            return jsonify({"error": "Mod privileges required"}), 403
        return f(*args, **kwargs)
    return decorated

# Item generation function
def generate_item(owner):
    def weighted_choice(items, special_case=False):
        choices, weights = zip(*items.items())
        if special_case:
            choices = list(items.keys())
            weights = []
            for choice in choices:
                weights.append(items[choice]["rarity"])
        return random.choices(choices, weights=weights, k=1)[0]
    
    noun = weighted_choice(NOUNS, special_case=True)
    return {
        "id": str(uuid4()),
        "item_secret": str(uuid4()),
        "name": {
            "adjective": weighted_choice(ADJECTIVES),
            "material": weighted_choice(MATERIALS),
            "noun": noun,
            "suffix": weighted_choice(SUFFIXES),
            "number": random.randint(1, 9999),
            "icon": NOUNS[noun]["icon"],
        },
        "for_sale": False,
        "price": 0,
        "owner": owner,
        "created_at": int(time.time())
    }

# Routes
@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/<path:path>')
def static_file(path):
    return send_from_directory('static', path)

@app.route('/api/register', methods=['POST'])
@csrf.exempt
def register():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({"error": "Missing username or password"}), 400

    try:
        hashed_password = generate_password_hash(password)
        users_collection.insert_one({
            'username': username,
            'password_hash': hashed_password,
            'type': 'user',
            'tokens': 100,
            'last_item_time': 0,
            'last_mine_time': 0,
            'items': [],
            'token': None
        })
        
        
        return jsonify({"success": True}), 201
    except DuplicateKeyError:
        return jsonify({"error": "Username already exists"}), 400

@app.route('/api/login', methods=['POST'])
@csrf.exempt
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    user = users_collection.find_one({'username': username})
    if not user or not check_password_hash(user['password_hash'], password):
        return jsonify({"error": "Invalid username or password"}), 401

    token = str(uuid4())
    users_collection.update_one(
        {'username': username},
        {'$set': {'token': token}}
    )
    return jsonify({"success": True, "token": token})

@app.route('/api/account', methods=['GET'])
@csrf.exempt
def get_account():
    user = users_collection.find_one({'username': request.username})
    if not user:
        return jsonify({"error": "User not found"}), 404

    # Exclude _id from the items query
    items = items_collection.find({'id': {'$in': user['items']}}, {'_id': 0})
    user_items = [item for item in items]

    return jsonify({
        'username': user['username'],
        'type': user.get('type', 'user'),
        'tokens': user['tokens'],
        'items': user_items,
        'last_item_time': user['last_item_time'],
        'last_mine_time': user['last_mine_time']
    })

@app.route('/api/create_item', methods=['POST'])
@csrf.exempt
def create_item():
    username = request.username
    now = time.time()

    user = users_collection.find_one({'username': username}, {'_id': 0})
    if not user:
        return jsonify({"error": "User not found"}), 404

    if now - user['last_item_time'] < ITEM_CREATE_COOLDOWN:
        remaining = ITEM_CREATE_COOLDOWN - (now - user['last_item_time'])
        return jsonify({"error": "Cooldown active", "remaining": remaining}), 429

    if user['tokens'] < 10:
        return jsonify({"error": "Not enough tokens"}), 402

    new_item = generate_item(username)
    items_collection.insert_one(new_item)
    users_collection.update_one(
        {'username': username},
        {
            '$push': {'items': new_item['id']},
            '$set': {'last_item_time': now},
            '$inc': {'tokens': -10}
        }
    )
    return jsonify({k: v for k, v in new_item.items() if k != '_id' and k != 'item_secret'})

@app.route('/api/mine_tokens', methods=['POST'])
@csrf.exempt
def mine_tokens():
    username = request.username
    now = time.time()

    user = users_collection.find_one({'username': username}, {'_id': 0})
    if not user:
        return jsonify({"error": "User not found"}), 404

    if now - user['last_mine_time'] < TOKEN_MINE_COOLDOWN:
        remaining = TOKEN_MINE_COOLDOWN - (now - user['last_mine_time'])
        return jsonify({"error": "Cooldown active", "remaining": remaining}), 429

    mined_tokens = random.randint(5, 10)
    users_collection.update_one(
        {'username': username},
        {
            '$inc': {'tokens': mined_tokens},
            '$set': {'last_mine_time': now}
        }
    )
    return jsonify({"success": True, "tokens": user['tokens'] + mined_tokens})

@app.route('/api/market', methods=['GET'])
def market():
    username = request.username
    # Exclude _id from the items query
    items = items_collection.find({
        'for_sale': True,
        'owner': {'$ne': username}
    }, {'_id': 0})
    return jsonify([{k: v for k, v in item.items() if k != 'item_secret'} for item in items])

@app.route('/api/sell_item', methods=['POST'])
@csrf.exempt
def sell_item():
    data = request.get_json()
    item_id = data.get('item_id')
    price = data.get('price')
    username = request.username

    try:
        price = float(price)
        if not MIN_ITEM_PRICE <= price <= MAX_ITEM_PRICE:
            raise ValueError
    except ValueError:
        return jsonify({"error": f"Invalid price (must be {MIN_ITEM_PRICE}-{MAX_ITEM_PRICE})"}), 400

    item = items_collection.find_one({'id': item_id, 'owner': username}, {'_id': 0})
    if not item:
        return jsonify({"error": "Item not found"}), 404

    update_data = {
        'for_sale': not item['for_sale'],
        'price': price if not item['for_sale'] else 0
    }
    items_collection.update_one(
        {'id': item_id},
        {'$set': update_data}
    )
    return jsonify({"success": True})

@app.route('/api/buy_item', methods=['POST'])
@csrf.exempt
def buy_item():
    data = request.get_json()
    item_id = data.get('item_id')
    buyer_username = request.username

    item = items_collection.find_one({'id': item_id, 'for_sale': True}, {'_id': 0})
    if not item:
        return jsonify({"error": "Item not available"}), 404

    if buyer_username == item['owner']:
        return jsonify({"error": "Cannot buy your own item"}), 400

    buyer = users_collection.find_one({'username': buyer_username}, {'_id': 0})
    if buyer['tokens'] < item['price']:
        return jsonify({"error": "Not enough tokens"}), 402

    with client.start_session() as session:
        session.start_transaction()
        try:
            users_collection.update_one(
                {'username': buyer_username},
                {'$inc': {'tokens': -item['price']}},
                session=session
            )
            users_collection.update_one(
                {'username': item['owner']},
                {'$inc': {'tokens': item['price']}},
                session=session
            )
            users_collection.update_one(
                {'username': item['owner']},
                {'$pull': {'items': item_id}},
                session=session
            )
            users_collection.update_one(
                {'username': buyer_username},
                {'$push': {'items': item_id}},
                session=session
            )
            items_collection.update_one(
                {'id': item_id},
                {'$set': {'owner': buyer_username, 'for_sale': False, 'price': 0}},
                session=session
            )
            session.commit_transaction()
        except Exception as e:
            session.abort_transaction()
            return jsonify({"error": str(e)}), 500

    return jsonify({"success": True})

@app.route('/api/leaderboard', methods=['GET'])
def leaderboard():
    pipeline = [
        {"$sort": {"tokens": DESCENDING}},
        {"$limit": 10},
        {"$project": {
            "_id": 0,  # Exclude _id from the result
            "username": 1,
            "tokens": 1
        }}
    ]
    results = list(users_collection.aggregate(pipeline))
    
    def ordinal(n):
        return "%d%s" % (n, "tsnrhtdd"[((n//10%10!=1)*(n%10<4)*n%10)::4])
    
    for i, item in enumerate(results):
        item['place'] = ordinal(i+1)
    
    return jsonify({"leaderboard": results})
  
@app.route('/api/take_item', methods=['POST'])
@csrf.exempt
def take_item():
    data = request.get_json()
    item_secret = data.get('item_secret')
    username = request.username

    item = items_collection.find_one({'item_secret': item_secret})
    if not item:
        return jsonify({"error": "Invalid secret"}), 404

    previous_owner = item['owner']
    with client.start_session() as session:
        session.start_transaction()
        try:
            # Remove from previous owner
            users_collection.update_one(
                {'username': previous_owner},
                {'$pull': {'items': item['id']}},
                session=session
            )
            # Add to current user
            users_collection.update_one(
                {'username': username},
                {'$push': {'items': item['id']}},
                session=session
            )
            # Update item ownership
            items_collection.update_one(
                {'item_secret': item_secret},
                {'$set': {'owner': username, 'for_sale': False, 'price': 0}},
                session=session
            )
            session.commit_transaction()
        except Exception as e:
            session.abort_transaction()
            return jsonify({"error": str(e)}), 500
    return jsonify({"success": True})

@app.route('/api/reset_cooldowns', methods=['POST'])
@csrf.exempt
@requires_admin
def reset_cooldowns():
    username = request.username
    users_collection.update_one(
        {'username': username},
        {'$set': {'last_item_time': 0, 'last_mine_time': 0}}
    )
    return jsonify({"success": True})

@app.route('/api/edit_tokens', methods=['POST'])
@csrf.exempt
@requires_admin
def edit_tokens():
    data = request.get_json()
    tokens = data.get('tokens')
    target_username = data.get('username', request.username)

    try:
        tokens = float(tokens)
    except ValueError:
        return jsonify({"error": "Invalid tokens value"}), 400

    target_user = users_collection.find_one({'username': target_username})
    if not target_user:
        return jsonify({"error": "User not found"}), 404

    users_collection.update_one(
        {'username': target_username},
        {'$set': {'tokens': tokens}}
    )
    return jsonify({"success": True})

@app.route('/api/add_admin', methods=['POST'])
@csrf.exempt
@requires_admin
def add_admin():
    data = request.get_json()
    username = data.get('username')

    user = users_collection.find_one({'username': username})
    if not user:
        return jsonify({"error": "User not found"}), 404

    users_collection.update_one(
        {'username': username},
        {'$set': {'type': 'admin'}}
    )
    return jsonify({"success": True})

@app.route('/api/add_mod', methods=['POST'])
@csrf.exempt
@requires_admin
def add_mod():
    data = request.get_json()
    username = data.get('username')

    user = users_collection.find_one({'username': username})
    if not user:
        return jsonify({"error": "User not found"}), 404

    users_collection.update_one(
        {'username': username},
        {'$set': {'type': 'mod'}}
    )
    return jsonify({"success": True})

@app.route('/api/remove_mod', methods=['POST'])
@csrf.exempt
@requires_admin
def remove_mod():
    data = request.get_json()
    username = data.get('username')

    user = users_collection.find_one({'username': username})
    if not user:
        return jsonify({"error": "User not found"}), 404

    users_collection.update_one(
        {'username': username},
        {'$set': {'type': 'user'}}
    )
    return jsonify({"success": True})

@app.route('/api/edit_item', methods=['POST'])
@csrf.exempt
@requires_admin
def edit_item():
    data = request.get_json()
    item_id = data.get('item_id')
    new_name = data.get('new_name')
    new_icon = data.get('new_icon')

    item = items_collection.find_one({'id': item_id})
    if not item:
        return jsonify({"error": "Item not found"}), 404

    updates = {}
    if new_name:
        updates['name.adjective'] = new_name
    if new_icon:
        updates['name.icon'] = new_icon

    if updates:
        items_collection.update_one(
            {'id': item_id},
            {'$set': updates}
        )
    return jsonify({"success": True})

@app.route('/api/delete_item', methods=['POST'])
@csrf.exempt
@requires_admin
def delete_item():
    data = request.get_json()
    item_id = data.get('item_id')

    item = items_collection.find_one({'id': item_id})
    if not item:
        return jsonify({"error": "Item not found"}), 404

    owner = item['owner']
    users_collection.update_one(
        {'username': owner},
        {'$pull': {'items': item_id}}
    )
    items_collection.delete_one({'id': item_id})
    return jsonify({"success": True})

@app.route('/api/send_message', methods=['POST'])
@csrf.exempt
def send_message():
    data = request.get_json()
    room = data.get('room')
    message = data.get('message')
    username = request.username

    if not room or not message:
        return jsonify({"error": "Missing room or message"}), 400

    # Ensure room exists
    if not rooms_collection.find_one({'name': room}):
        rooms_collection.insert_one({'name': room})

    messages_collection.insert_one({
        'room': room,
        'username': username,
        'message': message,
        'timestamp': time.time()
    })
    return jsonify({"success": True})

@app.route('/api/get_messages', methods=['GET'])
def get_messages():
    room = request.args.get('room')
    if not room:
        return jsonify({"error": "Missing room parameter"}), 400

    messages = messages_collection.find(
        {'room': room}, 
        {'_id': 0}
    ).sort('timestamp', ASCENDING)
    return jsonify({"messages": list(messages)})
  
@app.route('/api/stats', methods=['GET'])
def get_stats():
    accounts_cursor = users_collection.find()
    items_cursor = items_collection.find()
    mods_cursor = users_collection.find({'type': 'mod'})
    admins_cursor = users_collection.find({'type': 'admin'})
    users_cursor = users_collection.find({'type': 'user'})

    accounts = list(accounts_cursor)
    admins = list(admins_cursor)
    mods = list(mods_cursor)
    users = list(users_cursor)
    items = list(items_cursor)

    total_tokens = sum(user['tokens'] for user in accounts)

    return jsonify([
      {
        "name": "Total Accounts",
        "value": len(accounts)
      },
      {
        "name": "Total Admins",
        "value": len(admins)
      },
      {
        "name": "Total Mods",
        "value": len(mods)
      },
      {
        "name": "Total Users",
        "value": len(users)
      },
      {
        "name": "Total Tokens",
        "value": total_tokens
      },
      {
        "name": "Total Items",
        "value": len(items)
      }
    ])

if __name__ == '__main__':
    app.logger.info("Starting application with Waitress")
    user = users_collection.find_one({'username': 'proplayer919'})
    if user:
        users_collection.update_one(
            {'username': 'proplayer919'},
            {'$set': {'type': 'admin'}}
        )
    serve(app, host='0.0.0.0', port=5000, threads=4)