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

# Configuration constants
DATA_DIR = Path(os.environ.get('DATA_DIR', 'data'))
DATA_DIR.mkdir(parents=True, exist_ok=True)
CHAT_DIR = DATA_DIR / 'chats'
CHAT_DIR.mkdir(parents=True, exist_ok=True)
USERS_FILE = DATA_DIR / 'users.json'
ITEMS_FILE = DATA_DIR / 'items.json'
ITEM_CREATE_COOLDOWN = int(os.environ.get('ITEM_CREATE_COOLDOWN', 60))
TOKEN_MINE_COOLDOWN = int(os.environ.get('TOKEN_MINE_COOLDOWN', 600))
MAX_ITEM_PRICE = 10000
MIN_ITEM_PRICE = 1

# Item generation constants
with open('words/adjectives.json', 'r') as f:
    ADJECTIVES = json.load(f)
with open('words/materials.json', 'r') as f:
    MATERIALS = json.load(f)
with open('words/nouns.json', 'r') as f:
    NOUNS = json.load(f)
with open('words/suffixes.json', 'r') as f:
    SUFFIXES = json.load(f)

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
                    return {}
                
                with open(self.filepath, 'r') as f:
                    fcntl.flock(f, fcntl.LOCK_SH)
                    data = json.load(f)
                    fcntl.flock(f, fcntl.LOCK_UN)
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
        
    def is_allowed(self, username):
        if self.public:
            return True
        return username in self.allowed_users
        
    def add_message(self, username, message):
        self.messages.append({"username": username, "message": message})
        self.database.save(self.messages)
        
    def get_messages(self):
        self.messages = self.database.load()
        return self.messages
    
    def clear_messages(self):
        self.messages = []
        self.database.save(self.messages)

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
        
        :param items: dict - A dictionary where keys are items and values are their weights.
        :return: str - A randomly selected key based on weights.
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
    except Exception as e:
        app.logger.error(f"Item generation failed: {str(e)}")
        raise

@app.before_request
def authenticate_user():
    if request.method == 'OPTIONS' or request.endpoint in ['register', 'login', 'restore_account', 'index', 'static_file']:
        return

    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Missing or invalid Authorization header"}), 401
    token = auth_header.split(' ')[1]
    users = users_db.load()
    for username, user_data in users.items():
        if user_data.get('token') == token:
            request.username = username
            request.user_type = user_data.get('type')
            return
    return jsonify({"error": "Invalid token"}), 401
  
def requires_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"error": "Missing or invalid Authorization header"}), 401
        token = auth_header.split(' ')[1]
        users = users_db.load()
        for username, user_data in users.items():
            if user_data.get('token') == token:
                if user_data.get('type') == 'admin':
                    return f(*args, **kwargs)
                return jsonify({"error": "Admin privileges required"}), 403
        return jsonify({"error": "Invalid token"}), 401
    return decorated
  
def requires_mod(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"error": "Missing or invalid Authorization header"}), 401
        token = auth_header.split(' ')[1]
        users = users_db.load()
        for username, user_data in users.items():
            if user_data.get('token') == token:
                if user_data.get('type') == 'admin' or user_data.get('type') == 'mod':
                    return f(*args, **kwargs)
                return jsonify({"error": "Mod privileges required"}), 403
        return jsonify({"error": "Invalid token"}), 401
    return decorated

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

    users = users_db.load()
    if username in users:
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
    return jsonify({"success": True}), 201

@app.route('/api/login', methods=['POST'])
@csrf.exempt
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({"error": "Missing username or password"}), 400

    users = users_db.load()
    user = users.get(username)
    if not user or not check_password_hash(user['password_hash'], password):
        return jsonify({"error": "Invalid username or password"}), 401

    token = str(uuid4())
    user['token'] = token
    users_db.save(users)
    return jsonify({"success": True, "token": token})

@app.route('/api/account', methods=['GET'])
@csrf.exempt
def get_account():
    users = users_db.load()
    username = request.username
    user = users.get(username)
    if not user:
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
    if not user:
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
    user = users.get(request.username)
    if not user:
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
    items = items_db.load()
    item = items.get(item_id)
    if not item:
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
    users = users_db.load()
    user = users.get(username)
    if not user:
        return jsonify({"error": "User not found"}), 404
    user['type'] = 'admin'
    users_db.save(users)
    return jsonify({"success": True})
  
@app.route('/api/add_mod', methods=['POST'])
@csrf.exempt
@requires_admin
def add_mod():
    data = request.get_json()
    username = data.get('username')
    users = users_db.load()
    user = users.get(username)
    if not user:
        return jsonify({"error": "User not found"}), 404
    if user['type'] == 'admin':
        return jsonify({"error": "User is an admin"}), 400
    user['type'] = 'mod'
    users_db.save(users)
    return jsonify({"success": True})
  
@app.route('/api/remove_mod', methods=['POST'])
@csrf.exempt
@requires_admin
def remove_mod():
    data = request.get_json()
    username = data.get('username')
    users = users_db.load()
    user = users.get(username)
    if not user:
        return jsonify({"error": "User not found"}), 404
    if not user['type'] == 'mod':
        return jsonify({"error": "User is not a mod"}), 400
    user['type'] = 'user'
    users_db.save(users)
    return jsonify({"success": True})

@app.route('/api/create_item', methods=['POST'])
@csrf.exempt
def create_item():
    users = users_db.load()
    items = items_db.load()
    username = request.username
    user = users.get(username)
    now = time.time()

    if not user:
        return jsonify({"error": "User not found"}), 404

    if now - user['last_item_time'] < ITEM_CREATE_COOLDOWN:
        remaining = ITEM_CREATE_COOLDOWN - (now - user['last_item_time'])
        return jsonify({"error": "Cooldown active", "remaining": remaining}), 429

    if user['tokens'] < 10:
        return jsonify({"error": "Not enough tokens"}), 402

    try:
        new_item = generate_item(username)
        items[new_item['id']] = new_item
        user['items'].append(new_item['id'])
        user['last_item_time'] = now
        user['tokens'] -= 10
        
        items_db.save(items)
        users_db.save(users)
        return jsonify({k: v for k, v in new_item.items() if k != 'item_secret'})
    except Exception as e:
        app.logger.error(f"Item creation failed: {str(e)}")
        return jsonify({"error": "Item creation failed"}), 500

@app.route('/api/mine_tokens', methods=['POST'])
@csrf.exempt
def mine_tokens():
    users = users_db.load()
    username = request.username
    user = users.get(username)
    now = time.time()

    if not user:
        return jsonify({"error": "User not found"}), 404

    if now - user['last_mine_time'] < TOKEN_MINE_COOLDOWN:
        remaining = TOKEN_MINE_COOLDOWN - (now - user['last_mine_time'])
        return jsonify({"error": "Cooldown active", "remaining": remaining}), 429

    user['tokens'] += random.randint(5, 10)
    user['last_mine_time'] = now
    users_db.save(users)
    return jsonify({"success": True, "tokens": user['tokens']})

@app.route('/api/market', methods=['GET'])
def market():
    items = items_db.load()
    username = request.username
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

    if not item_id or price is None:
        return jsonify({"error": "Missing parameters"}), 400

    try:
        price = int(price)
        if not MIN_ITEM_PRICE <= price <= MAX_ITEM_PRICE:
            raise ValueError
    except ValueError:
        return jsonify({"error": f"Invalid price (must be {MIN_ITEM_PRICE}-{MAX_ITEM_PRICE})"}), 400

    items = items_db.load()
    username = request.username

    if item_id not in items or items[item_id]['owner'] != username:
        return jsonify({"error": "Item not found"}), 404

    if items[item_id]['for_sale']:
        items[item_id]['for_sale'] = False
        items[item_id]['price'] = 0
    else:
        items[item_id]['for_sale'] = True
        items[item_id]['price'] = price
    items_db.save(items)
    return jsonify({"success": True})

@app.route('/api/buy_item', methods=['POST'])
@csrf.exempt
def buy_item():
    data = request.get_json()
    item_id = data.get('item_id')

    if not item_id:
        return jsonify({"error": "Missing item_id"}), 400

    users = users_db.load()
    items = items_db.load()
    buyer_username = request.username
    buyer = users.get(buyer_username)

    if item_id not in items or not items[item_id]['for_sale']:
        return jsonify({"error": "Item not available"}), 404

    item = items[item_id]
    if buyer_username == item['owner']:
        return jsonify({"error": "Cannot buy your own item"}), 400

    if buyer['tokens'] < item['price']:
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
    return jsonify({"success": True, "item": item_id})

@app.route('/api/lookup_item', methods=['GET'])
def lookup_item():
    item_id = request.args.get('item_id')

    if not item_id:
        return jsonify({"error": "Missing item_id"}), 400

    items = items_db.load()
    item = items.get(item_id)

    if not item:
        return jsonify({"error": "Item not found"}), 404

    item_data = {k: v for k, v in item.items() if k != 'item_secret'}
    return jsonify({"item": item_data})
  
@app.route('/api/take_item', methods=['POST'])
@csrf.exempt
def take_item():
    data = request.get_json()
    item_secret = data.get('item_secret')

    if not item_secret:
        return jsonify({"error": "Missing item_secret"}), 400

    items = items_db.load()
    item = next((item for item in items.values() if item['item_secret'] == item_secret), None)

    if not item:
        return jsonify({"error": "Item not found"}), 404
      
    username = request.username
    user = users_db.load().get(username)
    if not user:
        return jsonify({"error": "User not found"}), 404

    old_owner = item['owner']
    old_owner_items = users_db.load()[old_owner]['items']
    if item['id'] in old_owner_items:
        old_owner_items.remove(item['id'])
    
    user['items'].append(item['id'])
    item['owner'] = username
    items_db.save(items)
    users_db.save(users_db.load())
    return jsonify({"success": True})
  
# chat endpoints

@app.route('/api/send_message', methods=['POST'])
@csrf.exempt
def send_message():
    data = request.get_json()
    room = data.get('room')
    message = data.get('message')

    if not room or not message:
        return jsonify({"error": "Missing parameters"}), 400

    if room not in chat_rooms:
        return jsonify({"error": "Room not found"}), 404

    chat_rooms[room].add_message(request.username, message)
    return jsonify({"success": True})
  
@app.route('/api/get_messages', methods=['GET'])
def get_messages():
    room = request.args.get('room')

    if not room:
        return jsonify({"error": "Missing parameters"}), 400

    if room not in chat_rooms:
        return jsonify({"error": "Room not found"}), 404
      
    if not chat_rooms[room].is_allowed(request.username) and request.user_type != 'admin':
        return jsonify({"error": "You are not allowed to access this room"}), 403

    messages = chat_rooms[room].get_messages()
    return jsonify({"messages": messages})
  
@app.route('/api/create_room', methods=['POST'])
@csrf.exempt
def create_room():
    data = request.get_json()
    room = data.get('room')
    allowed_users = data.get('allowed_users')

    if not room:
        return jsonify({"error": "Missing parameters"}), 400

    if room in chat_rooms:
        return jsonify({"error": "Room already exists"}), 409

    chat_rooms[room] = ChatRoom(room, public=False, allowed_users=allowed_users)
    return jsonify({"success": True})
  
@app.route('/api/get_rooms', methods=['GET'])
def get_rooms():
    all_rooms = [room.name for room in chat_rooms.values()]
    for room in chat_rooms.values():
        if not room.is_allowed(request.username) and request.user_type != 'admin':
            all_rooms.remove(room.name)
    return jsonify({"rooms": all_rooms})
  
@app.route('/api/leaderboard', methods=['GET'])
def leaderboard():
    users = users_db.load()
    leaderboard = sorted(users.items(), key=lambda x: x[1]['tokens'], reverse=True)
    
    def ordinal(n):
        return "%d%s" % (n, "tsnrhtdd"[((n//10%10!=1)*(n%10<4)*n%10)::4])
    
    leaderboard = [{"username": username, "place": ordinal(i+1), "tokens": user['tokens']} for i, (username, user) in enumerate(leaderboard)]
    return jsonify({"leaderboard": leaderboard[:10]})
  
@app.route('/healthcheck', methods=['GET'])
def healthcheck():
    return jsonify({"status": "OK"}), 200

if __name__ == '__main__':
    serve(app, host='0.0.0.0', port=5000, threads=4)