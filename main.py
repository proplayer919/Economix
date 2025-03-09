import os
import json
import time
import random
import logging
import fcntl
import threading
from uuid import uuid4
from pathlib import Path
from logging.handlers import RotatingFileHandler
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash
from waitress import serve
from functools import wraps

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

# Log all incoming requests
@app.before_request
def log_all_requests():
    app.logger.info(f"Incoming request: {request.method} {request.url} from {request.remote_addr}")

# Configuration constants
DATA_DIR = Path(os.environ.get('DATA_DIR', 'data'))
try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    app.logger.info(f"Data directory created or exists at: {DATA_DIR}")
except Exception as e:
    app.logger.error(f"Error creating data directory {DATA_DIR}: {str(e)}")
CHAT_DIR = DATA_DIR / 'chats'
try:
    CHAT_DIR.mkdir(parents=True, exist_ok=True)
    app.logger.info(f"Chat directory created or exists at: {CHAT_DIR}")
except Exception as e:
    app.logger.error(f"Error creating chat directory {CHAT_DIR}: {str(e)}")
USERS_FILE = DATA_DIR / 'users.json'
ITEMS_FILE = DATA_DIR / 'items.json'
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

class JsonDatabase:
    """Thread-safe JSON database handler with file locking"""
    def __init__(self, filepath):
        self.filepath = filepath
        self.lock = threading.Lock()

    def load(self):
        """Load data from file with shared lock"""
        with self.lock:
            try:
                if not self.filepath.exists():
                    app.logger.info(f"{self.filepath} does not exist. Returning empty dict.")
                    return {}
                with open(self.filepath, 'r') as f:
                    fcntl.flock(f, fcntl.LOCK_SH)
                    data = json.load(f)
                    fcntl.flock(f, fcntl.LOCK_UN)
                    app.logger.info(f"Loaded data from {self.filepath}")
                    return data
            except (json.JSONDecodeError, PermissionError) as e:
                app.logger.error(f"Error loading {self.filepath}: {str(e)}")
                return {}
            except Exception as e:
                app.logger.critical(f"Critical error loading {self.filepath}: {str(e)}")
                raise

    def save(self, data):
        """Save data to file with exclusive lock"""
        with self.lock:
            try:
                with open(self.filepath, 'w') as f:
                    fcntl.flock(f, fcntl.LOCK_EX)
                    json.dump(data, f, indent=4, separators=(',', ':'))
                    fcntl.flock(f, fcntl.LOCK_UN)
                    app.logger.info(f"Saved data to {self.filepath}")
            except Exception as e:
                app.logger.critical(f"Error saving {self.filepath}: {str(e)}")
                raise
              
class ChatRoom:
    def __init__(self, name, public=True, allowed_users=[]):
        self.name = name
        self.messages = []
        self.database = JsonDatabase(CHAT_DIR / f"{name}.json")
        self.public = public
        self.allowed_users = allowed_users
        app.logger.info(f"ChatRoom '{name}' initialized with public={public}")

    def is_allowed(self, username):
        if self.public:
            return True
        return username in self.allowed_users
        
    def add_message(self, username, message):
        self.messages.append({"username": username, "message": message})
        self.database.save(self.messages)
        app.logger.info(f"Message added to room '{self.name}' by {username}")

    def get_messages(self):
        self.messages = self.database.load()
        app.logger.info(f"Messages retrieved from room '{self.name}'")
        return self.messages
    
    def clear_messages(self):
        self.messages = []
        self.database.save(self.messages)
        app.logger.info(f"Cleared messages in room '{self.name}'")

# Initialize databases
users_db = JsonDatabase(USERS_FILE)
items_db = JsonDatabase(ITEMS_FILE)

# Initialize chat rooms
chat_rooms = {
    'global': ChatRoom('global', public=True),
}

def generate_item(owner):
    """Generate a new random item with safety checks"""
    def weighted_choice(items, special_case=False):
        """
        Selects a random item from a dictionary where values represent weights.
        """
        choices, weights = zip(*items.items())
        if special_case:
            choices = list(items.keys())
            weights = []
            for choice in choices:
                weights.append(items[choice]["rarity"])
        return random.choices(choices, weights=weights, k=1)[0]
    
    try:
        noun = weighted_choice(NOUNS, special_case=True)
        new_item = {
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
        app.logger.info(f"Generated new item for owner {owner}: {new_item['id']}")
        return new_item
    except Exception as e:
        app.logger.error(f"Item generation failed: {str(e)}")
        raise

@app.before_request
def authenticate_user():
    # Skip authentication for certain endpoints
    if request.method == 'OPTIONS' or request.endpoint in ['register', 'login', 'restore_account', 'index', 'static_file', 'view_logs']:
        return

    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        app.logger.warning("Missing or invalid Authorization header")
        return jsonify({"error": "Missing or invalid Authorization header"}), 401
    token = auth_header.split(' ')[1]
    users = users_db.load()
    for username, user_data in users.items():
        if user_data.get('token') == token:
            request.username = username
            request.user_type = user_data.get('type')
            app.logger.info(f"Authenticated user: {username}")
            return
    app.logger.warning("Invalid token provided")
    return jsonify({"error": "Invalid token"}), 401
  
def requires_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            app.logger.warning("Admin access attempt with missing Authorization header")
            return jsonify({"error": "Missing or invalid Authorization header"}), 401
        token = auth_header.split(' ')[1]
        users = users_db.load()
        for username, user_data in users.items():
            if user_data.get('token') == token:
                if user_data.get('type') == 'admin':
                    app.logger.info(f"Admin privileges confirmed for user: {username}")
                    return f(*args, **kwargs)
                app.logger.warning(f"Admin privileges required for user: {username}")
                return jsonify({"error": "Admin privileges required"}), 403
        app.logger.warning("Invalid token provided for admin check")
        return jsonify({"error": "Invalid token"}), 401
    return decorated
  
def requires_mod(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            app.logger.warning("Mod access attempt with missing Authorization header")
            return jsonify({"error": "Missing or invalid Authorization header"}), 401
        token = auth_header.split(' ')[1]
        users = users_db.load()
        for username, user_data in users.items():
            if user_data.get('token') == token:
                if user_data.get('type') in ['admin', 'mod']:
                    app.logger.info(f"Mod privileges confirmed for user: {username}")
                    return f(*args, **kwargs)
                app.logger.warning(f"Mod privileges required for user: {username}")
                return jsonify({"error": "Mod privileges required"}), 403
        app.logger.warning("Invalid token provided for mod check")
        return jsonify({"error": "Invalid token"}), 401
    return decorated

@app.route('/')
def index():
    app.logger.info("Serving index.html")
    return send_from_directory('static', 'index.html')
  
@app.route('/<path:path>')
def static_file(path):
    app.logger.info(f"Serving static file: {path}")
    return send_from_directory('static', path)

@app.route('/api/register', methods=['POST'])
@csrf.exempt
def register():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    app.logger.info(f"Attempting registration for user: {username}")

    if not username or not password:
        app.logger.warning("Registration failed: Missing username or password")
        return jsonify({"error": "Missing username or password"}), 400

    users = users_db.load()
    if username in users:
        app.logger.warning(f"Registration failed: Username {username} already exists")
        return jsonify({"error": "Username already exists"}), 400

    hashed_password = generate_password_hash(password)
    users[username] = {
        'password_hash': hashed_password,
        'type': 'user',
        'tokens': 100,
        'last_item_time': 0,
        'last_mine_time': 0,
        'items': [],
        'token': None
    }
    users_db.save(users)
    app.logger.info(f"User registered successfully: {username}")
    return jsonify({"success": True}), 201

@app.route('/api/login', methods=['POST'])
@csrf.exempt
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    app.logger.info(f"Login attempt for user: {username}")

    if not username or not password:
        app.logger.warning("Login failed: Missing username or password")
        return jsonify({"error": "Missing username or password"}), 400

    users = users_db.load()
    user = users.get(username)
    if not user or not check_password_hash(user['password_hash'], password):
        app.logger.warning(f"Login failed: Invalid credentials for user: {username}")
        return jsonify({"error": "Invalid username or password"}), 401

    token = str(uuid4())
    user['token'] = token
    users_db.save(users)
    app.logger.info(f"User logged in successfully: {username}")
    return jsonify({"success": True, "token": token})

@app.route('/api/account', methods=['GET'])
@csrf.exempt
def get_account():
    users = users_db.load()
    username = request.username
    user = users.get(username)
    app.logger.info(f"Fetching account details for user: {username}")
    if not user:
        app.logger.error(f"User not found in account lookup: {username}")
        return jsonify({"error": "User not found"}), 404
    
    items = items_db.load()
    user_items = []
    for item_id in user['items']:
        item = items.get(item_id)
        if item:
            user_items.append(item)

    return jsonify({
        'username': username,
        'type': user['type'],
        'tokens': user['tokens'],
        'items': user_items,
        'last_item_time': user['last_item_time'],
        'last_mine_time': user['last_mine_time']
    })
    
@app.route('/api/reset_cooldowns', methods=['POST'])
@csrf.exempt
@requires_admin
def reset_cooldowns():
    users = users_db.load()
    username = request.username
    user = users.get(username)
    app.logger.info(f"Resetting cooldowns for admin user: {username}")
    if not user:
        app.logger.error(f"Admin user not found for cooldown reset: {username}")
        return jsonify({"error": "User not found"}), 404
    user['last_item_time'] = 0
    user['last_mine_time'] = 0
    users_db.save(users)
    return jsonify({"success": True})
  
@app.route('/api/edit_tokens', methods=['POST'])
@csrf.exempt
@requires_admin
def edit_tokens():
    data = request.get_json()
    tokens = data.get('tokens')
    users = users_db.load()
    target_username = data.get("username", request.username)
    app.logger.info(f"Admin {request.username} editing tokens for user: {target_username}")
    
    user = users.get(target_username)
    if not user:
        app.logger.error(f"User not found in token edit: {target_username}")
        return jsonify({"error": "User not found"}), 404
      
    user['tokens'] = tokens
    users_db.save(users)
    return jsonify({"success": True})
  
@app.route('/api/edit_item', methods=['POST'])
@csrf.exempt
@requires_admin
def edit_item():
    data = request.get_json()
    item_id = data.get('item_id')
    new_name = data.get('new_name', None)
    new_icon = data.get('new_icon', None)
    app.logger.info(f"Admin {request.username} editing item: {item_id}")
    items = items_db.load()
    item = items.get(item_id)
    if not item:
        app.logger.error(f"Item not found during edit: {item_id}")
        return jsonify({"error": "Item not found"}), 404
    if new_name:
        item['name'] = new_name
    if new_icon:
        item['icon'] = new_icon
    items_db.save(items)
    return jsonify({"success": True})
  
@app.route('/api/add_admin', methods=['POST'])
@csrf.exempt
@requires_admin
def add_admin():
    data = request.get_json()
    username = data.get('username')
    app.logger.info(f"Admin {request.username} attempting to add admin privileges to user: {username}")
    users = users_db.load()
    user = users.get(username)
    if not user:
        app.logger.error(f"User not found while adding admin: {username}")
        return jsonify({"error": "User not found"}), 404
    user['type'] = 'admin'
    users_db.save(users)
    app.logger.info(f"User {username} promoted to admin")
    return jsonify({"success": True})
  
@app.route('/api/add_mod', methods=['POST'])
@csrf.exempt
@requires_admin
def add_mod():
    data = request.get_json()
    username = data.get('username')
    app.logger.info(f"Admin {request.username} attempting to add mod privileges to user: {username}")
    users = users_db.load()
    user = users.get(username)
    if not user:
        app.logger.error(f"User not found while adding mod: {username}")
        return jsonify({"error": "User not found"}), 404
    if user['type'] == 'admin':
        app.logger.warning(f"Cannot promote admin user {username} to mod")
        return jsonify({"error": "User is an admin"}), 400
    user['type'] = 'mod'
    users_db.save(users)
    app.logger.info(f"User {username} promoted to mod")
    return jsonify({"success": True})
  
@app.route('/api/remove_mod', methods=['POST'])
@csrf.exempt
@requires_admin
def remove_mod():
    data = request.get_json()
    username = data.get('username')
    app.logger.info(f"Admin {request.username} attempting to remove mod privileges from user: {username}")
    users = users_db.load()
    user = users.get(username)
    if not user:
        app.logger.error(f"User not found while removing mod: {username}")
        return jsonify({"error": "User not found"}), 404
    if user['type'] != 'mod':
        app.logger.warning(f"User {username} is not a mod")
        return jsonify({"error": "User is not a mod"}), 400
    user['type'] = 'user'
    users_db.save(users)
    app.logger.info(f"User {username} demoted from mod")
    return jsonify({"success": True})
  
@app.route('/api/delete_item', methods=['POST'])
@csrf.exempt
@requires_admin
def delete_item():
    data = request.get_json()
    item_id = data.get('item_id')
    app.logger.info(f"Admin {request.username} attempting to delete item: {item_id}")
    items = items_db.load()
    item = items.get(item_id)
    if not item:
        app.logger.error(f"Item not found during deletion: {item_id}")
        return jsonify({"error": "Item not found"}), 404
    
    owner = item['owner']
    users = users_db.load()
    user = users.get(owner)
    
    if user and item_id in user['items']:
        user['items'].remove(item_id)
        del items[item_id]
        items_db.save(items)
        users_db.save(users)
        app.logger.info(f"Item {item_id} deleted by admin {request.username}")
        return jsonify({"success": True})
    else:
        app.logger.error(f"Owner not found or item not in owner's list for item: {item_id}")
        return jsonify({"error": "Owner not found or item not in owner's list"}), 404

@app.route('/api/create_item', methods=['POST'])
@csrf.exempt
def create_item():
    users = users_db.load()
    items = items_db.load()
    username = request.username
    user = users.get(username)
    now = time.time()
    app.logger.info(f"User {username} attempting to create an item")
    if not user:
        app.logger.error(f"User not found during item creation: {username}")
        return jsonify({"error": "User not found"}), 404

    if now - user['last_item_time'] < ITEM_CREATE_COOLDOWN:
        remaining = ITEM_CREATE_COOLDOWN - (now - user['last_item_time'])
        app.logger.warning(f"Item creation cooldown active for user {username}. Remaining: {remaining} seconds")
        return jsonify({"error": "Cooldown active", "remaining": remaining}), 429

    if user['tokens'] < 10:
        app.logger.warning(f"User {username} does not have enough tokens to create an item")
        return jsonify({"error": "Not enough tokens"}), 402

    try:
        new_item = generate_item(username)
        items[new_item['id']] = new_item
        user['items'].append(new_item['id'])
        user['last_item_time'] = now
        user['tokens'] -= 10
        
        items_db.save(items)
        users_db.save(users)
        app.logger.info(f"Item created successfully: {new_item['id']} for user {username}")
        return jsonify({k: v for k, v in new_item.items() if k != 'item_secret'})
    except Exception as e:
        app.logger.error(f"Item creation failed for user {username}: {str(e)}")
        return jsonify({"error": "Item creation failed"}), 500

@app.route('/api/mine_tokens', methods=['POST'])
@csrf.exempt
def mine_tokens():
    users = users_db.load()
    username = request.username
    user = users.get(username)
    now = time.time()
    app.logger.info(f"User {username} attempting to mine tokens")
    if not user:
        app.logger.error(f"User not found during token mining: {username}")
        return jsonify({"error": "User not found"}), 404

    if now - user['last_mine_time'] < TOKEN_MINE_COOLDOWN:
        remaining = TOKEN_MINE_COOLDOWN - (now - user['last_mine_time'])
        app.logger.warning(f"Token mining cooldown active for user {username}. Remaining: {remaining} seconds")
        return jsonify({"error": "Cooldown active", "remaining": remaining}), 429

    mined_tokens = random.randint(5, 10)
    user['tokens'] += mined_tokens
    user['last_mine_time'] = now
    users_db.save(users)
    app.logger.info(f"User {username} mined {mined_tokens} tokens")
    return jsonify({"success": True, "tokens": user['tokens']})

@app.route('/api/market', methods=['GET'])
def market():
    items = items_db.load()
    username = request.username
    app.logger.info(f"User {username} fetching market items")
    market_items = [
        {k: v for k, v in item.items() if k != 'item_secret'}
        for item in items.values()
        if item['for_sale'] and item['owner'] != username
    ]
    return jsonify(market_items)

@app.route('/api/sell_item', methods=['POST'])
@csrf.exempt
def sell_item():
    data = request.get_json()
    item_id = data.get('item_id')
    price = data.get('price')
    username = request.username
    app.logger.info(f"User {username} attempting to toggle sale for item: {item_id} with price: {price}")

    if not item_id or price is None:
        app.logger.warning("Sell item failed: Missing parameters")
        return jsonify({"error": "Missing parameters"}), 400

    try:
        price = float(price)
        if not MIN_ITEM_PRICE <= price <= MAX_ITEM_PRICE:
            app.logger.warning(f"Sell item failed: Invalid price {price} by user {username}")
            raise ValueError
    except ValueError:
        return jsonify({"error": f"Invalid price (must be {MIN_ITEM_PRICE}-{MAX_ITEM_PRICE})"}), 400

    items = items_db.load()

    if item_id not in items or items[item_id]['owner'] != username:
        app.logger.warning(f"Sell item failed: Item {item_id} not found or not owned by {username}")
        return jsonify({"error": "Item not found"}), 404

    if items[item_id]['for_sale']:
        items[item_id]['for_sale'] = False
        items[item_id]['price'] = 0
        app.logger.info(f"User {username} removed item {item_id} from sale")
    else:
        items[item_id]['for_sale'] = True
        items[item_id]['price'] = price
        app.logger.info(f"User {username} put item {item_id} up for sale at price {price}")
    items_db.save(items)
    return jsonify({"success": True})

@app.route('/api/buy_item', methods=['POST'])
@csrf.exempt
def buy_item():
    data = request.get_json()
    item_id = data.get('item_id')
    buyer_username = request.username
    app.logger.info(f"User {buyer_username} attempting to buy item: {item_id}")

    if not item_id:
        app.logger.warning("Buy item failed: Missing item_id")
        return jsonify({"error": "Missing item_id"}), 400

    users = users_db.load()
    items = items_db.load()
    buyer = users.get(buyer_username)

    if item_id not in items or not items[item_id]['for_sale']:
        app.logger.warning(f"Buy item failed: Item {item_id} not available for sale")
        return jsonify({"error": "Item not available"}), 404

    item = items[item_id]
    if buyer_username == item['owner']:
        app.logger.warning(f"Buy item failed: User {buyer_username} attempted to buy their own item")
        return jsonify({"error": "Cannot buy your own item"}), 400

    if buyer['tokens'] < item['price']:
        app.logger.warning(f"Buy item failed: User {buyer_username} does not have enough tokens")
        return jsonify({"error": "Not enough tokens"}), 402

    seller_username = item['owner']
    seller = users[seller_username]

    # Transfer tokens
    buyer['tokens'] -= item['price']
    seller['tokens'] += item['price']

    # Transfer ownership
    seller['items'].remove(item_id)
    buyer['items'].append(item_id)
    item['owner'] = buyer_username
    item['for_sale'] = False
    item['price'] = 0

    items_db.save(items)
    users_db.save(users)
    app.logger.info(f"User {buyer_username} bought item {item_id} from {seller_username}")
    return jsonify({"success": True, "item": item_id})

@app.route('/api/lookup_item', methods=['GET'])
def lookup_item():
    item_id = request.args.get('item_id')
    username = request.username
    app.logger.info(f"User {username} looking up item: {item_id}")

    if not item_id:
        app.logger.warning("Lookup item failed: Missing item_id")
        return jsonify({"error": "Missing item_id"}), 400

    items = items_db.load()
    item = items.get(item_id)

    if not item:
        app.logger.warning(f"Lookup item failed: Item {item_id} not found")
        return jsonify({"error": "Item not found"}), 404

    item_data = {k: v for k, v in item.items() if k != 'item_secret'}
    return jsonify({"item": item_data})
  
@app.route('/api/take_item', methods=['POST'])
@csrf.exempt
def take_item():
    data = request.get_json()
    item_secret = data.get('item_secret')
    username = request.username
    app.logger.info(f"User {username} attempting to take item with secret: {item_secret}")

    if not item_secret:
        app.logger.warning("Take item failed: Missing item_secret")
        return jsonify({"error": "Missing item_secret"}), 400

    items = items_db.load()
    item = next((item for item in items.values() if item['item_secret'] == item_secret), None)

    if not item:
        app.logger.warning("Take item failed: Item not found")
        return jsonify({"error": "Item not found"}), 404
      
    users = users_db.load()
    user = users.get(username)
    if not user:
        app.logger.error(f"User not found during take item: {username}")
        return jsonify({"error": "User not found"}), 404

    old_owner = item['owner']
    if old_owner in users:
        old_owner_items = users[old_owner]['items']
        if item['id'] in old_owner_items:
            old_owner_items.remove(item['id'])
    user['items'].append(item['id'])
    item['owner'] = username
    items_db.save(items)
    users_db.save(users)
    app.logger.info(f"User {username} successfully took item {item['id']} from {old_owner}")
    return jsonify({"success": True})
  
# chat endpoints

@app.route('/api/send_message', methods=['POST'])
@csrf.exempt
def send_message():
    data = request.get_json()
    room = data.get('room')
    message = data.get('message')
    username = request.username
    app.logger.info(f"User {username} sending message to room: {room}")

    if not room or not message:
        app.logger.warning("Send message failed: Missing parameters")
        return jsonify({"error": "Missing parameters"}), 400

    if room not in chat_rooms:
        app.logger.warning(f"Send message failed: Room {room} not found")
        return jsonify({"error": "Room not found"}), 404

    chat_rooms[room].add_message(username, message)
    return jsonify({"success": True})
  
@app.route('/api/get_messages', methods=['GET'])
def get_messages():
    room = request.args.get('room')
    username = request.username
    app.logger.info(f"User {username} requesting messages from room: {room}")

    if not room:
        app.logger.warning("Get messages failed: Missing room parameter")
        return jsonify({"error": "Missing parameters"}), 400

    if room not in chat_rooms:
        app.logger.warning(f"Get messages failed: Room {room} not found")
        return jsonify({"error": "Room not found"}), 404
      
    if not chat_rooms[room].is_allowed(username) and request.user_type != 'admin':
        app.logger.warning(f"User {username} not allowed to access room {room}")
        return jsonify({"error": "You are not allowed to access this room"}), 403

    messages = chat_rooms[room].get_messages()
    return jsonify({"messages": messages})
  
@app.route('/api/create_room', methods=['POST'])
@csrf.exempt
def create_room():
    data = request.get_json()
    room = data.get('room')
    allowed_users = data.get('allowed_users')
    username = request.username
    app.logger.info(f"User {username} attempting to create room: {room}")

    if not room:
        app.logger.warning("Create room failed: Missing room parameter")
        return jsonify({"error": "Missing parameters"}), 400

    if room in chat_rooms:
        app.logger.warning(f"Create room failed: Room {room} already exists")
        return jsonify({"error": "Room already exists"}), 409

    chat_rooms[room] = ChatRoom(room, public=False, allowed_users=allowed_users)
    app.logger.info(f"Room {room} created by user {username}")
    return jsonify({"success": True})
  
@app.route('/api/get_rooms', methods=['GET'])
def get_rooms():
    username = request.username
    app.logger.info(f"User {username} requesting list of chat rooms")
    all_rooms = [room.name for room in chat_rooms.values()]
    for room in list(chat_rooms.values()):
        if not room.is_allowed(username) and request.user_type != 'admin':
            if room.name in all_rooms:
                all_rooms.remove(room.name)
    return jsonify({"rooms": all_rooms})
  
@app.route('/api/leaderboard', methods=['GET'])
def leaderboard():
    users = users_db.load()
    app.logger.info("Fetching leaderboard data")
    leaderboard = sorted(users.items(), key=lambda x: x[1]['tokens'], reverse=True)
    
    def ordinal(n):
        return "%d%s" % (n, "tsnrhtdd"[((n//10%10!=1)*(n%10<4)*n%10)::4])
    
    leaderboard = [{"username": username, "place": ordinal(i+1), "tokens": user['tokens']} for i, (username, user) in enumerate(leaderboard)]
    return jsonify({"leaderboard": leaderboard[:10]})

@app.route('/logs', methods=['GET'])
def view_logs():
    app.logger.info("Log file requested")
    try:
        with open('app.log', 'r') as f:
            log_content = f.read()
    except Exception as e:
        app.logger.error(f"Could not read log file: {str(e)}")
        return jsonify({"error": "Could not read log file", "message": str(e)}), 500

    def colorize_line(line):
        if "DEBUG:" in line:
            return f'<span class="debug">{line}</span>'
        elif "INFO:" in line:
            return f'<span class="info">{line}</span>'
        elif "WARNING:" in line:
            return f'<span class="warning">{line}</span>'
        elif "ERROR:" in line:
            return f'<span class="error">{line}</span>'
        elif "CRITICAL:" in line:
            return f'<span class="critical">{line}</span>'
        else:
            return line

    log_lines = log_content.splitlines()
    new_run_indices = [i for i, line in enumerate(log_lines) if "Data directory created or exists at:" in line]
    if not new_run_indices:
        colored_lines = []
    else:
        last_new_run_index = new_run_indices[-1]
        colored_lines = [colorize_line(line) for line in log_lines[last_new_run_index:]]
        
    colored_lines.reverse()

    html = f"""
    <html>
      <head>
        <title>Application Logs</title>
        <style>
          body {{
            background-color: #f4f4f4;
            font-family: 'Courier New', Courier, monospace;
            color: #333;
            padding: 20px;
          }}
          h1 {{
            text-align: center;
          }}
          .log-container {{
            background-color: #fff;
            border: 1px solid #ccc;
            padding: 20px;
            margin: auto;
            max-width: 80%;
            overflow: auto;
            box-shadow: 0 0 10px rgba(0,0,0,0.1);
          }}
          pre {{
            white-space: pre-wrap;
            word-wrap: break-word;
          }}
          .debug {{ color: #007acc; }}      /* Blue */
          .info {{ color: #666; }}          /* Grey */
          .warning {{ color: #b8860b; }}    /* DarkGoldenrod */
          .error {{ color: #cc0000; }}      /* Red */
          .critical {{ color: #8b0000; font-weight: bold; }}  /* DarkRed */
        </style>
      </head>
      <body>
        <h1>Application Logs</h1>
        <div class="log-container">
          <pre>{'\n'.join(reversed(colored_lines))}</pre>
        </div>
      </body>
    </html>
    """
    return html


if __name__ == '__main__':
    app.logger.info("Starting application with Waitress")
    serve(app, host='0.0.0.0', port=5000, threads=4)
    app.logger.info("Application stopped")