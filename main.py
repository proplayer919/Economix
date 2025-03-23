import os
import json
import time
import random
import logging
from uuid import uuid4
from logging.handlers import RotatingFileHandler
from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from hashlib import sha256
from functools import wraps
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError
import re
import html
import pyotp
import qrcode
import io
from better_profanity import profanity
import requests
import stripe


# Initialize Flask application
app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("FLASK_SECRET_KEY", "1234"),
)

# Security middleware
CORS(app, origins=os.environ.get("CORS_ORIGINS", "").split(","))

# Configure logging
handler = RotatingFileHandler(
    "app.log", maxBytes=1024 * 1024 * 10, backupCount=5  # 10 MB
)
handler.setFormatter(
    logging.Formatter(
        "%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]"
    )
)
app.logger.addHandler(handler)
app.logger.setLevel(logging.INFO)

# Profanity filter
profanity.load_censor_words()

# MongoDB configuration
client = MongoClient(os.environ.get("MONGODB_URI"))
db = client.get_database(os.environ.get("MONGODB_DB"))

# Collections
users_collection = db.users
items_collection = db.items
messages_collection = db.messages
rooms_collection = db.rooms
item_meta_collection = db.item_meta
misc_collection = db.misc

# Create indexes
users_collection.create_index([("username", ASCENDING)], unique=True)
items_collection.create_index([("id", ASCENDING)], unique=True)
messages_collection.create_index([("room", ASCENDING), ("timestamp", DESCENDING)])
rooms_collection.create_index([("name", ASCENDING)], unique=True)
item_meta_collection.create_index([("id", ASCENDING)])
misc_collection.create_index([("type", ASCENDING)])

# Configuration constants
ITEM_CREATE_COOLDOWN = int(os.environ.get("ITEM_CREATE_COOLDOWN", 60))
TOKEN_MINE_COOLDOWN = int(os.environ.get("TOKEN_MINE_COOLDOWN", 120))
MAX_ITEM_PRICE = 1000000000000
MIN_ITEM_PRICE = 1
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK")

# Stripe configuration
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY")
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")

stripe.api_key = STRIPE_SECRET_KEY

# Item generation constants
try:
    with open("words/adjectives.json", "r") as f:
        ADJECTIVES = json.load(f)
    with open("words/materials.json", "r") as f:
        MATERIALS = json.load(f)
    with open("words/nouns.json", "r") as f:
        NOUNS = json.load(f)
    with open("words/suffixes.json", "r") as f:
        SUFFIXES = json.load(f)
    app.logger.info("Loaded item generation word lists successfully")
except Exception as e:
    app.logger.critical(f"Failed to load word lists: {str(e)}")
    raise


# Utility functions
def split_name(name):
    return {
        "adjective": name.split(" ")[0],
        "material": name.split(" ")[1],
        "noun": name.split(" ")[2],
        "suffix": " ".join(name.split(" ")[3:]).split("#")[0],
        "number": " ".join(name.split(" ")[3:]).split("#")[1],
    }


def get_level(rarity):
    if rarity <= 0.1:
        return "Godlike"
    elif rarity <= 1:
        return "Legendary"
    elif rarity <= 5:
        return "Epic"
    elif rarity <= 10:
        return "Rare"
    elif rarity <= 25:
        return "Uncommon"
    elif rarity <= 50:
        return "Common"
    elif rarity <= 75:
        return "Scrap"
    else:
        return "Trash"


def parse_time(length):
    now = time.time()
    if not length or length.lower() == "perma":
        # Forever
        end_time = 0
    else:
        # Parse duration
        parts = length.split("+")
        duration = 0
        for part in parts:
            if part[-1].lower() == "s":
                duration += int(part[:-1])
            elif part[-1].lower() == "m":
                duration += 60 * int(part[:-1])
            elif part[-1].lower() == "h":
                duration += 60 * 60 * int(part[:-1])
            elif part[-1].lower() == "d":
                duration += 60 * 60 * 24 * int(part[:-1])
            elif part[-1].lower() == "w":
                duration += 60 * 60 * 24 * 7 * int(part[:-1])
            elif part[-1].lower() == "y":
                duration += 60 * 60 * 24 * 365 * int(part[:-1])

        end_time = now + duration

    return end_time


def send_discord_notification(title, description, color=0x00FF00):
    webhook_url = DISCORD_WEBHOOK
    if not webhook_url:
        app.logger.error("Discord webhook URL not configured.")
        return

    data = {"embeds": [{"title": title, "description": description, "color": color}]}

    response = requests.post(webhook_url, json=data)
    if response.status_code == 204:
        app.logger.info("Notification sent to Discord successfully.")
    else:
        app.logger.error(
            f"Failed to send notification to Discord: {response.status_code} {response.text}"
        )


# Authentication middleware
@app.before_request
def authenticate_user():
    if request.method == "OPTIONS" or request.endpoint in [
        "register_endpoint",
        "login_endpoint",
        "index",
        "static_file",
        "stats_endpoint",
        "stripe_webhook",
    ]:
        return

    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        app.logger.warning("Missing or invalid Authorization header")
        return (
            jsonify(
                {
                    "error": "Missing or invalid Authorization header",
                    "code": "invalid-credentials",
                }
            ),
            401,
        )

    token = auth_header.split(" ")[1]
    user = users_collection.find_one({"token": token})
    if user:
        request.username = user["username"]
        request.user_type = user.get("type", "user")
        return

    app.logger.warning("Invalid token provided")
    return jsonify({"error": "Invalid token", "code": "invalid-credentials"}), 401


# Database updaters
def update_item(item_id):
    item = items_collection.find_one({"id": item_id})
    if not item:
        return

    name = item["name"]

    meta_id = None

    if "meta_id" not in item:
        meta_id = sha256(
            f"{name['adjective']}{name['material']}{name['noun']}{name['suffix']}".encode()
        ).hexdigest()

        meta = item_meta_collection.find_one({"id": meta_id})
        if not meta:
            rarity = round(random.uniform(0.1, 100), 1)

            meta = {
                "id": meta_id,
                "adjective": name["adjective"],
                "material": name["material"],
                "noun": name["noun"],
                "suffix": name["suffix"],
                "rarity": rarity,
                "level": get_level(rarity),
                "patented": False,
                "patent_owner": None,
                "price_history": [],
            }
            item_meta_collection.insert_one(meta)
    else:
        meta_id = item["meta_id"]
        meta = item_meta_collection.find_one({"id": meta_id})

    if "history" not in item:
        items_collection.update_one({"id": item_id}, {"$set": {"history": []}})
        items_collection.update_one(
            {"id": item_id}, {"$set": {"rarity": round(item["rarity"], 1)}}
        )

    items_collection.update_one(
        {"id": item_id},
        {
            "$set": {
                "meta_id": meta_id,
                "rarity": meta["rarity"],
                "level": meta["level"],
            }
        },
    )


def update_account(username):
    user = users_collection.find_one({"username": username})
    if not user:
        return jsonify({"error": "User not found", "code": "user-not-found"}), 404

    if (
        "banned_until" not in user
        or "banned_reason" not in user
        or "banned" not in user
    ):
        users_collection.update_one(
            {"username": username},
            {"$set": {"banned_until": None, "banned_reason": None, "banned": False}},
        )

    if "history" not in user:
        users_collection.update_one({"username": username}, {"$set": {"history": []}})

    if "exp" not in user or "level" not in user:
        users_collection.update_one(
            {"username": username},
            {"$set": {"exp": 0, "level": 1}},
        )

    if "frozen" not in user:
        users_collection.update_one({"username": username}, {"$set": {"frozen": False}})

    if "muted" not in user or "muted_until" not in user:
        users_collection.update_one(
            {"username": username},
            {"$set": {"muted": False, "muted_until": None}},
        )

    if "inventory_visibility" not in user:
        users_collection.update_one(
            {"username": username},
            {"$set": {"inventory_visibility": "private"}},
        )

    if "2fa_enabled" not in user:
        users_collection.update_one(
            {"username": username}, {"$set": {"2fa_enabled": False}}
        )

    if "subscriptions" not in user:
        users_collection.update_one(
            {"username": username}, {"$set": {"subscriptions": []}}
        )

    if "override_plan" not in user:
        users_collection.update_one(
            {"username": username}, {"$set": {"override_plan": None}}
        )

    if user.get("banned_until", None) and (
        user["banned_until"] < time.time() and user["banned_until"] != 0
    ):
        users_collection.update_one(
            {"username": username},
            {"$set": {"banned_until": None, "banned_reason": None}},
        )

    if user.get("muted_until", None) and (
        user["muted_until"] < time.time() and user["muted_until"] != 0
    ):
        users_collection.update_one(
            {"username": username},
            {"$set": {"muted": False, "muted_until": None}},
        )

    for item_id in user["items"]:
        update_item(item_id)

    if user["type"] == "admin":
        users_collection.update_one(
            {"username": username}, {"$set": {"override_plan": "proplus"}}
        )


# Admin requirement decorator
def requires_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = users_collection.find_one({"username": request.username})
        if user.get("type") != "admin":
            app.logger.warning(
                f"Admin privileges required for user: {request.username}"
            )
            return (
                jsonify(
                    {"error": "Admin privileges required", "code": "admin-required"}
                ),
                403,
            )
        return f(*args, **kwargs)

    return decorated


# Mod requirement decorator
def requires_mod(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = users_collection.find_one({"username": request.username})
        if user.get("type") not in ["admin", "mod"]:
            app.logger.warning(f"Mod privileges required for user: {request.username}")
            return (
                jsonify({"error": "Mod privileges required", "code": "mod-required"}),
                403,
            )
        return f(*args, **kwargs)

    return decorated


# Unbanned requirement decorator
def requires_unbanned(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = users_collection.find_one({"username": request.username})
        if user.get("banned_until", None):
            app.logger.warning(f"User is banned: {request.username}")
            return jsonify({"error": "You are banned", "code": "banned"}), 403
        return f(*args, **kwargs)

    return decorated


# Subscription requirement
def requires_subscription(username, plan):
    if plan == "pro":
        user = users_collection.find_one({"username": username})
        if user["override_plan"] in ["pro", "proplus"]:
            return True

        for subscription in user["subscriptions"]:
            if subscription["plan"] == "pro" or subscription["plan"] == "proplus":
                return True
    elif plan == "proplus":
        user = users_collection.find_one({"username": username})
        if user["override_plan"] == "proplus":
            return True

        for subscription in user["subscriptions"]:
            if subscription["plan"] == "proplus":
                return True

    return False


# Item generation function
def generate_item(owner):
    def weighted_choice(items, special_case=False):
        choices, weights = zip(*items.items())
        if special_case:
            choices = list(items.keys())
            weights = []
            for choice in choices:
                weights.append(1 / items[choice]["rarity"])
        return random.choices(choices, weights=weights, k=1)[0]

    noun = weighted_choice(NOUNS, special_case=True)

    name = {
        "adjective": weighted_choice(ADJECTIVES),
        "material": weighted_choice(MATERIALS),
        "noun": noun,
        "suffix": weighted_choice(SUFFIXES),
        "number": random.randint(1, 9999),
        "icon": NOUNS[noun]["icon"],
    }

    meta_id = sha256(
        f"{name['adjective']}{name['material']}{name['noun']}{name['suffix']}".encode()
    ).hexdigest()

    meta = item_meta_collection.find_one({"id": meta_id})
    if not meta:
        rarity = round(random.uniform(0.1, 100), 1)

        meta = {
            "id": meta_id,
            "adjective": name["adjective"],
            "material": name["material"],
            "noun": name["noun"],
            "suffix": name["suffix"],
            "rarity": rarity,
            "level": get_level(rarity),
            "patented": False,
            "patent_owner": None,
            "price_history": [],
        }
        item_meta_collection.insert_one(meta)

    return {
        "id": str(uuid4()),
        "meta_id": meta_id,
        "item_secret": str(uuid4()),
        "rarity": meta["rarity"],
        "level": meta["level"],
        "name": name,
        "history": [],
        "for_sale": False,
        "price": 0,
        "owner": owner,
        "created_at": int(time.time()),
    }


# EXP Functions
def exp_for_level(level):
    return int(25 * (1.2 ** (level - 1)))


def add_exp(username, exp):
    user = users_collection.find_one({"username": username})
    if not user:
        return

    next_level = user["level"] + 1

    users_collection.update_one({"username": username}, {"$inc": {"exp": exp}})

    if user["exp"] >= exp_for_level(next_level):
        users_collection.update_one(
            {"username": username}, {"$set": {"level": next_level}}
        )


def set_exp(username, exp):
    user = users_collection.find_one({"username": username})
    if not user:
        return

    next_level = user["level"] + 1

    users_collection.update_one({"username": username}, {"$set": {"exp": exp}})

    if user["exp"] >= exp_for_level(next_level):
        users_collection.update_one(
            {"username": username}, {"$set": {"level": next_level}}
        )


def set_level(username, level):
    user = users_collection.find_one({"username": username})
    if not user:
        return

    level_exp = exp_for_level(level)
    users_collection.update_one(
        {"username": username}, {"$set": {"level": level, "exp": level_exp}}
    )


##########################
#        Handlers        #
##########################


def get_user(username):
    return users_collection.find_one({"username": username})


def get_users():
    users = users_collection.find({}, {"_id": 0, "username": 1})
    usernames = [user["username"] for user in users]
    return jsonify({"usernames": usernames})


def get_banned_users():
    users = users_collection.find({"banned": True}, {"_id": 0, "username": 1})
    usernames = [user["username"] for user in users]
    return jsonify({"usernames": usernames})


def get_muted_users():
    users = users_collection.find({"muted": True}, {"_id": 0, "username": 1})
    usernames = [user["username"] for user in users]
    return jsonify({"usernames": usernames})


def register(username, password):
    if not username or not password:
        return (
            jsonify(
                {"error": "Missing username or password", "code": "missing-credentials"}
            ),
            400,
        )

    # Sanitize and validate username
    validateUsername = username.strip()
    validateUsername = profanity.censor(validateUsername, censor_char="-")
    if not re.match(r"^[a-zA-Z0-9_-]{3,20}$", validateUsername):
        return (
            jsonify(
                {
                    "error": "Username must be 3-20 characters, alphanumeric, underscores, or hyphens"
                }
            ),
            400,
        )

    try:
        hashed_password = generate_password_hash(password)
        users_collection.insert_one(
            {
                "created_at": int(time.time()),
                "username": username,
                "password_hash": hashed_password,
                "type": "user",
                "tokens": 100,
                "last_item_time": 0,
                "last_mine_time": 0,
                "items": [],
                "token": None,
                "banned_until": None,
                "banned_reason": None,
                "banned": False,
                "frozen": False,
                "muted": False,
                "muted_until": None,
                "history": [],
                "exp": 0,
                "level": 1,
                "2fa_enabled": False,
                "inventory_visibility": "private",
                "subscriptions": [],
                "override_plan": None,
            }
        )

        send_discord_notification(f"New user registered", f"Username: {username}")

        return jsonify({"success": True}), 201
    except DuplicateKeyError:
        return (
            jsonify({"error": "Username already exists", "code": "username-exists"}),
            400,
        )


def login(username, password, code=None, token=None):
    user = users_collection.find_one({"username": username})
    if not user or not check_password_hash(user["password_hash"], password):
        return (
            jsonify(
                {"error": "Invalid username or password", "code": "invalid-credentials"}
            ),
            401,
        )

    if user.get("2fa_enabled", False):
        if not code and not token:
            return (
                jsonify(
                    {
                        "error": "2FA is enabled. Please provide a OTP token or backup code",
                        "code": "2fa-required",
                    }
                ),
                401,
            )

        if code:
            if not user["2fa_code"] == code:
                return (
                    jsonify(
                        {"error": "Invalid 2FA backup code", "code": "invalid-2fa-code"}
                    ),
                    401,
                )
        else:
            user = users_collection.find_one({"username": username})
            totp = pyotp.TOTP(user["2fa_secret"])
            if not totp.verify(token):
                return (
                    jsonify(
                        {"error": "Invalid 2FA token", "code": "invalid-2fa-token"}
                    ),
                    401,
                )

    token = str(uuid4())
    users_collection.update_one({"username": username}, {"$set": {"token": token}})
    send_discord_notification(f"User logged in", f"Username: {username}")
    return jsonify({"success": True, "token": token})


def delete_account(username):
    user = users_collection.find_one({"username": username})
    if not user:
        return jsonify({"error": "User not found", "code": "user-not-found"}), 404

    # Delete user's items
    items_collection.delete_many({"owner": username})

    # Delete the user
    users_collection.delete_one({"username": username})

    for sub in user.get("subscriptions", []):
        if sub["status"] == "active":
            try:
                stripe.Subscription.delete(sub["subscription_id"])
            except stripe.error.StripeError as e:
                app.logger.error(f"Error canceling subscription: {str(e)}")

    send_discord_notification(f"User deleted", f"Username: {username}")

    return jsonify({"success": True})


def setup_2fa(username):
    user = users_collection.find_one({"username": username})
    if user.get("2fa_enabled", False):
        return (
            jsonify({"error": "2FA is already enabled", "code": "2fa-already-enabled"}),
            400,
        )
    if "2fa_secret" not in user:
        secret = pyotp.random_base32(32)
        users_collection.update_one(
            {"username": username}, {"$set": {"2fa_secret": secret}}
        )
    if "2fa_code" not in user:
        code = str(uuid4())
        users_collection.update_one(
            {"username": username}, {"$set": {"2fa_code": code}}
        )
    user = users_collection.find_one({"username": username})
    totp = pyotp.TOTP(user["2fa_secret"])
    provisioning_uri = totp.provisioning_uri(
        name=request.username,
        issuer_name="Economix",
        image="https://economix.proplayer919.dev/brand/logo.png",
    )
    code = user["2fa_code"]
    send_discord_notification(f"2FA enabled", f"Username: {username}")
    return jsonify(
        {"success": True, "provisioning_uri": provisioning_uri, "backup_code": code}
    )


def get_2fa_qrcode(username):
    user = users_collection.find_one({"username": username})
    if "2fa_secret" not in user:
        return (
            jsonify(
                {"error": "2FA is not enabled for this user", "code": "2fa-not-enabled"}
            ),
            400,
        )
    totp = pyotp.TOTP(user["2fa_secret"])
    provisioning_uri = totp.provisioning_uri(
        name=username,
        issuer_name="Economix",
        image="https://economix.proplayer919.dev/brand/logo.png",
    )
    img = qrcode.make(provisioning_uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


def verify_2fa(username, token):
    user = users_collection.find_one({"username": username})
    if "2fa_secret" not in user:
        return (
            jsonify(
                {"error": "2FA is not setup for this user", "code": "2fa-not-setup"}
            ),
            400,
        )
    totp = pyotp.TOTP(user["2fa_secret"])
    if not totp.verify(token):
        return jsonify({"error": "Invalid 2FA token", "code": "invalid-2fa-token"}), 401
    users_collection.update_one({"username": username}, {"$set": {"2fa_enabled": True}})
    return jsonify({"success": True})


def disable_2fa(username):
    users_collection.update_one(
        {"username": username},
        {"$set": {"2fa_enabled": False, "2fa_secret": None, "2fa_code": None}},
    )
    send_discord_notification(f"2FA disabled", f"Username: {username}")
    return jsonify({"success": True})


def create_item(username):
    now = time.time()

    user = users_collection.find_one({"username": username}, {"_id": 0})
    if not user:
        return jsonify({"error": "User not found", "code": "user-not-found"}), 404

    if now - user["last_item_time"] < ITEM_CREATE_COOLDOWN:
        remaining = ITEM_CREATE_COOLDOWN - (now - user["last_item_time"])
        return (
            jsonify(
                {
                    "error": "Cooldown active",
                    "remaining": remaining,
                    "code": "cooldown-active",
                }
            ),
            429,
        )

    if user["tokens"] < 10:
        return jsonify({"error": "Not enough tokens", "code": "not-enough-tokens"}), 402

    new_item = generate_item(username)
    items_collection.insert_one(new_item)
    users_collection.update_one(
        {"username": username},
        {
            "$push": {"items": new_item["id"]},
            "$set": {"last_item_time": now},
            "$inc": {"tokens": -10},
        },
    )

    users_collection.update_one(
        {"username": username},
        {
            "$push": {
                "history": {
                    "item_id": new_item["id"],
                    "action": "create",
                    "timestamp": now,
                }
            }
        },
    )

    add_exp(username, 10)

    item = new_item
    name_parts = [
        item["name"]["adjective"],
        item["name"]["material"],
        item["name"]["noun"],
    ]
    suffix = item["name"]["suffix"]
    if suffix.strip():
        name_parts.append(suffix)
    name_parts.append(f"#{item['name']['number']}")
    item_name = " ".join(name_parts)

    send_discord_notification(
        title="New Item Created",
        description=f"User {username} created a new item: {item_name} (Rarity: {new_item['rarity']}, Level: {new_item['level']})",
        color=0x00FF00,
    )

    return jsonify(
        {k: v for k, v in new_item.items() if k != "_id" and k != "item_secret"}
    )


def mine_tokens(username):
    now = time.time()

    user = users_collection.find_one({"username": username}, {"_id": 0})
    if not user:
        return jsonify({"error": "User not found", "code": "user-not-found"}), 404

    if now - user["last_mine_time"] < TOKEN_MINE_COOLDOWN:
        remaining = TOKEN_MINE_COOLDOWN - (now - user["last_mine_time"])
        return (
            jsonify(
                {
                    "error": "Cooldown active",
                    "remaining": remaining,
                    "code": "cooldown-active",
                }
            ),
            429,
        )

    mined_tokens = random.randint(5, 10)
    users_collection.update_one(
        {"username": username},
        {"$inc": {"tokens": mined_tokens}, "$set": {"last_mine_time": now}},
    )

    users_collection.update_one(
        {"username": username},
        {"$push": {"history": {"item_id": None, "action": "mine", "timestamp": now}}},
    )

    add_exp(username, 5)

    send_discord_notification(
        title="Tokens Mined",
        description=f"User {username} mined {mined_tokens} tokens",
        color=0x00FF00,
    )

    return jsonify({"success": True, "tokens": mined_tokens})


def get_market(username):
    items = items_collection.find(
        {"for_sale": True, "owner": {"$ne": username}}, {"_id": 0, "item_secret": 0}
    )
    return jsonify(list(items))


def sell_item(username, item_id, price):
    try:
        price = float(price)
        if not MIN_ITEM_PRICE <= price <= MAX_ITEM_PRICE:
            raise ValueError
    except ValueError:
        return (
            jsonify(
                {"error": f"Invalid price (must be {MIN_ITEM_PRICE}-{MAX_ITEM_PRICE})"}
            ),
            400,
        )

    item = items_collection.find_one({"id": item_id, "owner": username}, {"_id": 0})
    if not item:
        return jsonify({"error": "Item not found", "code": "item-not-found"}), 404

    update_data = {
        "for_sale": not item["for_sale"],
        "price": price if not item["for_sale"] else 0,
    }
    items_collection.update_one({"id": item_id}, {"$set": update_data})

    users_collection.update_one(
        {"username": username},
        {
            "$push": {
                "history": {
                    "item_id": item_id,
                    "action": "sell",
                    "timestamp": time.time(),
                }
            }
        },
    )

    # Construct item name
    name_parts = [
        item["name"]["adjective"],
        item["name"]["material"],
        item["name"]["noun"],
    ]
    suffix = item["name"]["suffix"]
    if suffix.strip():
        name_parts.append(suffix)
    name_parts.append(f"#{item['name']['number']}")
    item_name = " ".join(name_parts)

    if update_data["for_sale"]:
        send_discord_notification(
            title="Item Listed for Sale",
            description=f"User {username} listed {item_name} for {price} tokens",
            color=0xFFFF00,
        )
    else:
        send_discord_notification(
            title="Item Unlisted",
            description=f"User {username} unlisted {item_name}",
            color=0xFFFF00,
        )

    return jsonify({"success": True})


def buy_item(username, item_id):
    item = items_collection.find_one({"id": item_id, "for_sale": True}, {"_id": 0})
    if not item:
        return jsonify({"error": "Item not available", "code": "item-not-found"}), 404

    seller_username = item["owner"]

    if username == item["owner"]:
        return (
            jsonify(
                {
                    "error": "Cannot buy your own item",
                    "code": "cannot-buy-your-own-item",
                }
            ),
            400,
        )

    buyer = users_collection.find_one({"username": username}, {"_id": 0})
    if buyer["tokens"] < item["price"]:
        return jsonify({"error": "Not enough tokens", "code": "not-enough-tokens"}), 402

    with client.start_session() as session:
        session.start_transaction()
        try:
            users_collection.update_one(
                {"username": username},
                {"$inc": {"tokens": -item["price"]}},
                session=session,
            )
            users_collection.update_one(
                {"username": item["owner"]},
                {"$inc": {"tokens": item["price"]}},
                session=session,
            )
            users_collection.update_one(
                {"username": item["owner"]},
                {"$pull": {"items": item_id}},
                session=session,
            )
            users_collection.update_one(
                {"username": username},
                {"$push": {"items": item_id}},
                session=session,
            )
            items_collection.update_one(
                {"id": item_id},
                {"$set": {"owner": username, "for_sale": False, "price": 0}},
                session=session,
            )
            session.commit_transaction()
        except Exception as e:
            session.abort_transaction()
            return jsonify({"error": str(e), "code": "transaction-failed"}), 500

    users_collection.update_one(
        {"username": username},
        {
            "$push": {
                "history": {
                    "item_id": item_id,
                    "action": "buy",
                    "timestamp": time.time(),
                }
            }
        },
    )
    users_collection.update_one(
        {"username": seller_username},
        {
            "$push": {
                "history": {
                    "item_id": item_id,
                    "action": "sell_complete",
                    "timestamp": time.time(),
                }
            }
        },
    )

    meta_id = item["meta_id"]
    meta = item_meta_collection.find_one({"id": meta_id})
    if meta:
        meta["price_history"].append({"timestamp": time.time(), "price": item["price"]})
        item_meta_collection.update_one({"id": meta_id}, {"$set": meta})

    add_exp(username, 5)
    add_exp(seller_username, 5)

    # Construct item name
    name_parts = [
        item["name"]["adjective"],
        item["name"]["material"],
        item["name"]["noun"],
    ]
    suffix = item["name"]["suffix"]
    if suffix.strip():
        name_parts.append(suffix)
    name_parts.append(f"#{item['name']['number']}")
    item_name = " ".join(name_parts)

    send_discord_notification(
        title="Item Purchased",
        description=f"User {username} bought {item_name} from {seller_username} for {item['price']} tokens",
        color=0x0000FF,
    )

    return jsonify({"success": True})


def take_item(username, item_secret):
    item = items_collection.find_one({"item_secret": item_secret})
    if not item:
        return jsonify({"error": "Invalid secret", "code": "invalid-secret"}), 404

    previous_owner = item["owner"]
    with client.start_session() as session:
        session.start_transaction()
        try:
            # Remove from previous owner
            users_collection.update_one(
                {"username": previous_owner},
                {"$pull": {"items": item["id"]}},
                session=session,
            )
            # Add to current user
            users_collection.update_one(
                {"username": username},
                {"$push": {"items": item["id"]}},
                session=session,
            )
            # Update item ownership
            items_collection.update_one(
                {"item_secret": item_secret},
                {"$set": {"owner": username, "for_sale": False, "price": 0}},
                session=session,
            )
            session.commit_transaction()
        except Exception as e:
            session.abort_transaction()
            return jsonify({"error": str(e), "code": "transaction-failed"}), 500

    users_collection.update_one(
        {"username": username},
        {
            "$push": {
                "history": {
                    "item_id": item["id"],
                    "action": "take",
                    "timestamp": time.time(),
                }
            }
        },
    )
    users_collection.update_one(
        {"username": previous_owner},
        {
            "$push": {
                "history": {
                    "item_id": item["id"],
                    "action": "taken_from",
                    "timestamp": time.time(),
                }
            }
        },
    )
    return jsonify({"success": True})


def get_leaderboard():
    pipeline = [
        {"$match": {"banned": {"$ne": True}}},
        {"$sort": {"tokens": DESCENDING}},
        {"$limit": 10},
        {
            "$project": {
                "_id": 0,
                "username": 1,
                "tokens": 1,
            }
        },
    ]
    results = list(users_collection.aggregate(pipeline))

    def ordinal(n):
        return "%d%s" % (
            n,
            "tsnrhtdd"[((n // 10 % 10 != 1) * (n % 10 < 4) * n % 10) :: 4],
        )

    for i, item in enumerate(results):
        item["place"] = ordinal(i + 1)

    return jsonify({"leaderboard": results})


# Admin/Mod Functions
def reset_cooldowns(username):
    users_collection.update_one(
        {"username": username}, {"$set": {"last_item_time": 0, "last_mine_time": 0}}
    )

    send_discord_notification(
        title="Cooldowns Reset",
        description=f"Admin {request.username} reset cooldowns for {username}",
        color=0xFFA500,
    )

    return jsonify({"success": True})


def edit_tokens(username, tokens):
    try:
        tokens = float(tokens)
    except ValueError:
        return (
            jsonify({"error": "Invalid tokens value", "code": "invalid-tokens-value"}),
            400,
        )

    target_user = users_collection.find_one({"username": username})
    if not target_user:
        return jsonify({"error": "User not found", "code": "user-not-found"}), 404

    users_collection.update_one({"username": username}, {"$set": {"tokens": tokens}})

    send_discord_notification(
        title="Tokens Edited",
        description=f"Admin {request.username} set {username}'s tokens to {tokens}",
        color=0xFFA500,
    )

    return jsonify({"success": True})


def edit_exp(username, exp):
    try:
        exp = float(exp)
    except ValueError:
        return jsonify({"error": "Invalid exp value", "code": "invalid-value"}), 400

    if exp < 0:
        return (
            jsonify({"error": "Exp cannot be negative", "code": "cannot-be-negative"}),
            400,
        )

    target_user = users_collection.find_one({"username": username})
    if not target_user:
        return jsonify({"error": "User not found", "code": "user-not-found"}), 404

    set_exp(username, exp)

    send_discord_notification(
        title="Experience Edited",
        description=f"Admin {request.username} set {username}'s experience to {exp}",
        color=0xFFA500,
    )

    return jsonify({"success": True})


def edit_level(username, level):
    try:
        level = int(level)
    except ValueError:
        return jsonify({"error": "Invalid level value", "code": "invalid-value"}), 400

    if level < 1:
        return (
            jsonify(
                {"error": "Level cannot be less than 1", "code": "cannot-be-negative"}
            ),
            400,
        )

    target_user = users_collection.find_one({"username": username})
    if not target_user:
        return jsonify({"error": "User not found", "code": "user-not-found"}), 404

    set_level(username, level)

    send_discord_notification(
        title="Level Edited",
        description=f"Admin {request.username} set {username}'s level to {level}",
        color=0xFFA500,
    )

    return jsonify({"success": True})


def add_admin(username):
    user = users_collection.find_one({"username": username})
    if not user:
        return jsonify({"error": "User not found", "code": "user-not-found"}), 404

    users_collection.update_one({"username": username}, {"$set": {"type": "admin"}})
    send_discord_notification(
        title="Admin Added",
        description=f"Admin {request.username} added {username} as an admin",
        color=0xFFA500,
    )
    return jsonify({"success": True})


def remove_admin(username):
    user = users_collection.find_one({"username": username})
    if not user:
        return jsonify({"error": "User not found", "code": "user-not-found"}), 404

    users_collection.update_one({"username": username}, {"$set": {"type": "user"}})
    send_discord_notification(
        title="Admin Removed",
        description=f"Admin {request.username} removed {username} as an admin",
        color=0xFFA500,
    )
    return jsonify({"success": True})


def add_mod(username):
    user = users_collection.find_one({"username": username})
    if not user:
        return jsonify({"error": "User not found", "code": "user-not-found"}), 404

    users_collection.update_one({"username": username}, {"$set": {"type": "mod"}})
    send_discord_notification(
        title="Mod Added",
        description=f"Admin {request.username} added {username} as a mod",
        color=0xFFA500,
    )
    return jsonify({"success": True})


def remove_mod(username):
    user = users_collection.find_one({"username": username})
    if not user:
        return jsonify({"error": "User not found", "code": "user-not-found"}), 404

    users_collection.update_one({"username": username}, {"$set": {"type": "user"}})
    send_discord_notification(
        title="Mod Removed",
        description=f"Admin {request.username} removed {username} as a mod",
        color=0xFFA500,
    )
    return jsonify({"success": True})


def edit_item(item_id, new_name, new_icon, new_rarity):
    item = items_collection.find_one({"id": item_id})
    if not item:
        return jsonify({"error": "Item not found", "code": "item-not-found"}), 404

    updates = {}
    if new_name:
        parts = split_name(new_name)
        # Sanitize each component
        updates["name.adjective"] = html.escape(parts["adjective"].strip())
        updates["name.material"] = html.escape(parts["material"].strip())
        updates["name.noun"] = html.escape(parts["noun"].strip())
        updates["name.suffix"] = html.escape(parts["suffix"].strip())
        updates["name.number"] = html.escape(parts["number"].strip())
    if new_icon:
        updates["name.icon"] = html.escape(new_icon.strip())
    if new_rarity:
        updates["rarity"] = float(new_rarity)
        updates["level"] = get_level(float(new_rarity))

    if updates:
        items_collection.update_one({"id": item_id}, {"$set": updates})

        item = items_collection.find_one({"id": item_id}, {"_id": 0})
        name_parts = [
            item["name"]["adjective"],
            item["name"]["material"],
            item["name"]["noun"],
        ]
        suffix = item["name"]["suffix"]
        if suffix.strip():
            name_parts.append(suffix)
        name_parts.append(f"#{item['name']['number']}")
        item_name = " ".join(name_parts)

        updates_str = ", ".join([f"{k}: {v}" for k, v in updates.items()])
        send_discord_notification(
            title="Item Edited",
            description=f"Admin {request.username} edited item {item_name} (ID: {item_id}). Changes: {updates_str}",
            color=0xFFA500,
        )

    return jsonify({"success": True})


def delete_item(item_id):
    item = items_collection.find_one({"id": item_id})
    if not item:
        return jsonify({"error": "Item not found", "code": "item-not-found"}), 404

    owner = item["owner"]
    users_collection.update_one({"username": owner}, {"$pull": {"items": item_id}})
    items_collection.delete_one({"id": item_id})

    send_discord_notification(
        title="Item Deleted",
        description=f"Admin {request.username} deleted item {item_id}",
        color=0xFF0000,
    )

    return jsonify({"success": True})


def ban_user(username, length, reason):
    user = users_collection.find_one({"username": username})
    if not user:
        return jsonify({"error": "User not found", "code": "user-not-found"}), 404

    if user.get("type") == "admin":
        return (
            jsonify({"error": "Cannot ban an admin", "code": "cannot-ban-admin"}),
            403,
        )

    end_time = parse_time(length)

    users_collection.update_one(
        {"username": username},
        {"$set": {"banned_until": end_time, "banned_reason": reason, "banned": True}},
    )

    for sub in user.get("subscriptions", []):
        if sub["status"] == "active":
            try:
                subscription = stripe.Subscription.retrieve(sub["subscription_id"])
                stripe.Subscription.delete(sub["subscription_id"])

                # Refund the latest invoice
                invoice = stripe.Invoice.retrieve(subscription.latest_invoice)
                stripe.Refund.create(payment_intent=invoice.payment_intent)
            except stripe.error.StripeError as e:
                app.logger.error(f"Error processing refund: {str(e)}")

    send_discord_notification(
        title="User Banned",
        description=f"Admin {request.username} banned {username} for {length}. Reason: {reason}",
        color=0xFF0000,
    )
    return jsonify({"success": True})


def unban_user(username):
    user = users_collection.find_one({"username": username})
    if not user:
        return jsonify({"error": "User not found", "code": "user-not-found"}), 404

    users_collection.update_one(
        {"username": username},
        {"$set": {"banned_until": None, "banned_reason": None, "banned": False}},
    )
    send_discord_notification(
        title="User Unbanned",
        description=f"Admin {request.username} unbanned {username}",
        color=0xFFA500,
    )
    return jsonify({"success": True})


def mute_user(username, length):
    user = users_collection.find_one({"username": username})
    if not user:
        return jsonify({"error": "User not found", "code": "user-not-found"}), 404

    end_time = parse_time(length)

    users_collection.update_one(
        {"username": username},
        {"$set": {"muted_until": end_time, "muted": True}},
    )
    send_discord_notification(
        title="User Muted",
        description=f"Admin {request.username} muted {username} for {length}",
        color=0xFFA500,
    )
    return jsonify({"success": True})


def unmute_user(username):
    user = users_collection.find_one({"username": username})
    if not user:
        return jsonify({"error": "User not found", "code": "user-not-found"}), 404

    users_collection.update_one(
        {"username": username}, {"$set": {"muted": False, "muted_until": None}}
    )
    send_discord_notification(
        title="User Unmuted",
        description=f"Admin {request.username} unmuted {username}",
        color=0xFFA500,
    )
    return jsonify({"success": True})


def fine_user(username, amount):
    user = users_collection.find_one({"username": username})
    if not user:
        return jsonify({"error": "User not found", "code": "user-not-found"}), 404

    users_collection.update_one({"username": username}, {"$inc": {"tokens": -amount}})
    send_discord_notification(
        title="User Fined",
        description=f"Admin {request.username} fined {username} {amount} tokens",
        color=0xFFA500,
    )
    return jsonify({"success": True})


def delete_message(message_id):
    if not message_id:
        return (
            jsonify({"error": "Missing message_id", "code": "missing-parameters"}),
            400,
        )

    messages_collection.delete_one({"id": message_id})

    send_discord_notification(
        title="Message Deleted",
        description=f"Mod/Admin {request.username} deleted message with ID {message_id}",
        color=0xFF0000,
    )

    return jsonify({"success": True})


def set_banner(banner):
    misc_collection.delete_many({"type": "banner"})
    misc_collection.insert_one({"type": "banner", "value": banner})

    send_discord_notification(
        title="Banner Updated",
        description=f"Admin {request.username} set the banner to {banner}",
        color=0x00FF00,
    )

    return jsonify({"success": True})


def parse_command(command, room_name):
    command_parts = command[1:].split(" ")
    command, *args = command_parts

    if command == "clear_chat":
        messages_collection.delete_many({"room": room_name})
        system_message = f"Cleared chat in {room_name}"
    elif command == "clear_user" and len(args) == 1:
        target_username = args[0]
        messages_collection.delete_many(
            {"room": room_name, "username": target_username}
        )
        system_message = f"Deleted messages from {target_username} in {room_name}"
    elif command == "delete_many" and len(args) == 1:
        amount = args[0]
        try:
            amount = int(amount)
            messages_to_delete = (
                messages_collection.find({"room": room_name})
                .sort("timestamp", DESCENDING)
                .limit(amount)
            )
            ids_to_delete = [doc["_id"] for doc in messages_to_delete]
            messages_collection.delete_many({"_id": {"$in": ids_to_delete}})
            system_message = f"Deleted {amount} messages from {room_name}"
        except ValueError:
            system_message = "Invalid amount specified for deletion"

    elif command == "ban" and len(args) >= 3:
        target_username, duration, *reason_parts = args
        reason = " ".join(reason_parts)
        ban_user(target_username, reason, duration)
        system_message = f"Banned {target_username} for {reason} ({duration})"
    elif command == "mute" and len(args) == 2:
        target_username, duration = args
        mute_user(target_username, duration)
        system_message = f"Muted {target_username} for {duration}"
    elif command == "unban" and len(args) == 1:
        target_username = args[0]
        users_collection.update_one(
            {"username": target_username}, {"$set": {"banned": False}}
        )
        system_message = f"Unbanned {target_username}"
    elif command == "unmute" and len(args) == 1:
        target_username = args[0]
        unmute_user(target_username)
        system_message = f"Unmuted {target_username}"
    elif command == "sudo" and len(args) >= 2:
        sudo_username = args[0]
        sudo_message = " ".join(args[1:])
        sudo_user = users_collection.find_one({"username": sudo_username})
        if not sudo_user:
            system_message = f"User {sudo_username} not found"
        else:
            messages_collection.insert_one(
                {
                    "id": str(uuid4()),
                    "room": room_name,
                    "username": sudo_username,
                    "message": sudo_message,
                    "timestamp": time.time(),
                    "type": sudo_user["type"],
                }
            )
    elif command == "list_banned":
        banned_users = users_collection.find({"banned": True})

        if len(list(banned_users)) == 0:
            system_message = "Nobody is banned."
        else:
            banned_users_list = "\n".join(
                [
                    f"{user['username']} - {user.get("banned_reason", "No reason provided")}"
                    for user in banned_users
                ]
            )
            system_message = "Banned users:\n" + banned_users_list
    elif command == "list_frozen":
        frozen_users = users_collection.find({"frozen": True})

        if len(list(frozen_users)) == 0:
            system_message = "Nobody is frozen."
        else:
            frozen_users_list = "\n".join([user["username"] for user in frozen_users])
            system_message = "Frozen users:\n" + frozen_users_list
    elif command == "help":
        system_message = "Available commands: /clear_chat, /clear_user <username>, /delete_many <amount>, /ban <username> <duration> <reason>, /mute <username> <duration>, /unban <username>, /unmute <username>, /sudo <username> <message>, /list_banned, /list_frozen, /help"
    else:
        system_message = "Invalid command"

    return system_message


def send_message(room_name, message_content, username):
    user = users_collection.find_one({"username": username})
    if user["muted"]:
        return jsonify({"error": "You are muted", "code": "user-muted"}), 400

    if not room_name or not message_content:
        return (
            jsonify({"error": "Missing room or message", "code": "missing-parameters"}),
            400,
        )

    if not re.match(r"^[a-zA-Z0-9_-]{1,50}$", room_name):
        return jsonify({"error": "Invalid room name", "code": "invalid-room"}), 400

    sanitized_message = html.escape(message_content.strip())
    sanitized_message = profanity.censor(sanitized_message)
    if len(sanitized_message) == 0:
        return (
            jsonify({"error": "Message cannot be empty", "code": "empty-message"}),
            400,
        )
    if len(sanitized_message) > 100:
        return jsonify({"error": "Message too long", "code": "message-too-long"}), 400

    if not rooms_collection.find_one({"name": room_name}):
        rooms_collection.insert_one({"name": room_name})

    system_message = None
    if user["type"] == "admin" and sanitized_message.startswith("/"):
        system_message = parse_command(sanitized_message, room_name)
    else:
        messages_collection.insert_one(
            {
                "id": str(uuid4()),
                "room": room_name,
                "username": username,
                "message": sanitized_message,
                "timestamp": time.time(),
                "type": user["type"],
            }
        )

    if system_message:
        messages_collection.insert_one(
            {
                "id": str(uuid4()),
                "room": room_name,
                "username": "Command Handler",
                "message": system_message,
                "timestamp": time.time(),
                "type": "system",
            }
        )
    return jsonify({"success": True})


def get_messages(room_name):
    if not room_name:
        return (
            jsonify({"error": "Missing room parameter", "code": "missing-parameters"}),
            400,
        )

    messages = messages_collection.find({"room": room_name}, {"_id": 0}).sort(
        "timestamp", ASCENDING
    )
    return jsonify({"messages": list(messages)})


def get_stats():
    accounts_cursor = users_collection.find()
    items_cursor = items_collection.find()
    mods_cursor = users_collection.find({"type": "mod"})
    admins_cursor = users_collection.find({"type": "admin"})
    users_cursor = users_collection.find({"type": "user"})

    accounts = list(accounts_cursor)
    admins = list(admins_cursor)
    mods = list(mods_cursor)
    users = list(users_cursor)
    items = list(items_cursor)

    total_tokens = sum(user["tokens"] for user in accounts)

    return jsonify(
        {
            "stats": [
                {"name": "Total Accounts", "value": len(accounts)},
                {"name": "Total Admins", "value": len(admins)},
                {"name": "Total Mods", "value": len(mods)},
                {"name": "Total Users", "value": len(users)},
                {"name": "Total Tokens", "value": total_tokens},
                {"name": "Total Items", "value": len(items)},
            ]
        }
    )


def get_banner():
    banner = misc_collection.find_one({"type": "banner"}, {"_id": 0})
    return jsonify({"banner": banner})


##########################
#        Routes          #
##########################


# Static files
@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/<path:path>")
def static_file(path):
    return send_from_directory("static", path)


@app.route("/api/register", methods=["POST"])
def register_endpoint():
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")

    return register(username, password)


@app.route("/api/login", methods=["POST"])
def login_endpoint():
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")

    return login(username, password)


@app.route("/api/setup_2fa", methods=["POST"])
@requires_unbanned
def setup_2fa_endpoint():
    return setup_2fa(request.username)


@app.route("/api/2fa_qrcode", methods=["GET"])
@requires_unbanned
def get_2fa_qrcode_endpoint():
    return get_2fa_qrcode(request.username)


@app.route("/api/verify_2fa", methods=["POST"])
@requires_unbanned
def verify_2fa_endpoint():
    data = request.get_json()
    code = data.get("code")

    return verify_2fa(request.username, code)


@app.route("/api/disable_2fa", methods=["POST"])
@requires_unbanned
def disable_2fa_endpoint():
    return disable_2fa(request.username)


@app.route("/api/account", methods=["GET"])
@requires_unbanned
def account_endpoint():
    update_account(request.username)

    user = users_collection.find_one({"username": request.username})

    items = items_collection.find({"id": {"$in": user["items"]}}, {"_id": 0})
    user_items = [item for item in items]

    return jsonify(
        {
            "username": user["username"],
            "type": user.get("type", "user"),
            "tokens": user["tokens"],
            "items": user_items,
            "last_item_time": user["last_item_time"],
            "last_mine_time": user["last_mine_time"],
            "banned_until": user.get("banned_until"),
            "banned_reason": user.get("banned_reason"),
            "banned": user.get("banned"),
            "frozen": user.get("frozen"),
            "muted": user.get("muted"),
            "muted_until": user.get("muted_until"),
            "exp": user.get("exp"),
            "level": user.get("level"),
            "history": user.get("history"),
        }
    )


@app.route("/api/delete_account", methods=["POST"])
@requires_unbanned
def delete_account_endpoint():
    return delete_account(request.username)


@app.route("/api/create_item", methods=["POST"])
@requires_unbanned
def create_item_endpoint():
    return create_item(request.username)


@app.route("/api/mine_tokens", methods=["POST"])
@requires_unbanned
def mine_tokens_endpoint():
    return mine_tokens(request.username)


@app.route("/api/market", methods=["GET"])
@requires_unbanned
def market_endpoint():
    return get_market(request.username)


@app.route("/api/sell_item", methods=["POST"])
@requires_unbanned
def sell_item_endpoint():
    data = request.get_json()
    item_id = data.get("item_id")
    price = data.get("price")

    return sell_item(request.username, item_id, price)


@app.route("/api/buy_item", methods=["POST"])
@requires_unbanned
def buy_item_endpoint():
    data = request.get_json()
    item_id = data.get("item_id")

    return buy_item(request.username, item_id)


@app.route("/api/take_item", methods=["POST"])
@requires_unbanned
def take_item_endpoint():
    data = request.get_json()
    item_secret = data.get("item_secret")

    return take_item(request.username, item_secret)


@app.route("/api/leaderboard", methods=["GET"])
@requires_unbanned
def leaderboard_endpoint():
    return get_leaderboard()


@app.route("/api/send_message", methods=["POST"])
@requires_unbanned
def send_message_endpoint():
    data = request.get_json()
    message = data.get("message")
    room = data.get("room", "global")

    return send_message(room, message, request.username)


@app.route("/api/get_messages", methods=["GET"])
@requires_unbanned
def get_messages_endpoint():
    data = request.args
    room = data.get("room", "global")

    return get_messages(room)


@app.route("/api/get_banner", methods=["GET"])
@requires_unbanned
def get_banner_endpoint():
    return get_banner()


@app.route("/api/stats", methods=["GET"])
def stats_endpoint():
    return get_stats()


# Admin routes
@app.route("/api/reset_cooldowns", methods=["POST"])
@requires_admin
def reset_cooldowns_endpoint():
    return reset_cooldowns(request.username)


@app.route("/api/edit_tokens", methods=["POST"])
@requires_admin
def edit_tokens_endpoint():
    data = request.get_json()
    username = data.get("username") or request.username
    tokens = data.get("tokens")

    return edit_tokens(username, tokens)


@app.route("/api/edit_exp", methods=["POST"])
@requires_admin
def edit_exp_endpoint():
    data = request.get_json()
    username = data.get("username") or request.username
    exp = data.get("exp")

    return edit_exp(username, exp)


@app.route("/api/edit_level", methods=["POST"])
@requires_admin
def edit_level_endpoint():
    data = request.get_json()
    username = data.get("username") or request.username
    level = data.get("level")

    return edit_level(username, level)


@app.route("/api/add_admin", methods=["POST"])
@requires_admin
def add_admin_endpoint():
    data = request.get_json()
    username = data.get("username")

    return add_admin(username)


@app.route("/api/remove_admin", methods=["POST"])
@requires_admin
def remove_admin_endpoint():
    data = request.get_json()
    username = data.get("username")

    return remove_admin(username)


@app.route("/api/add_mod", methods=["POST"])
@requires_admin
def add_mod_endpoint():
    data = request.get_json()
    username = data.get("username")

    return add_mod(username)


@app.route("/api/remove_mod", methods=["POST"])
@requires_admin
def remove_mod_endpoint():
    data = request.get_json()
    username = data.get("username")

    return remove_mod(username)


@app.route("/api/edit_item", methods=["POST"])
@requires_admin
def edit_item_endpoint():
    data = request.get_json()
    item_id = data.get("item_id")
    new_name = data.get("new_name")
    new_icon = data.get("new_icon")
    new_rarity = data.get("new_rarity")

    return edit_item(item_id, new_name, new_icon, new_rarity)


@app.route("/api/delete_item", methods=["POST"])
@requires_admin
def delete_item_endpoint():
    data = request.get_json()
    item_id = data.get("item_id")

    return delete_item(item_id)


@app.route("/api/ban_user", methods=["POST"])
@requires_admin
def ban_user_endpoint():
    data = request.get_json()
    username = data.get("username")
    length = data.get("length")
    reason = data.get("reason")

    return ban_user(username, length, reason)


@app.route("/api/unban_user", methods=["POST"])
@requires_admin
def unban_user_endpoint():
    data = request.get_json()
    username = data.get("username")

    return unban_user(username)


@app.route("/api/fine_user", methods=["POST"])
@requires_admin
def fine_user_endpoint():
    data = request.get_json()
    username = data.get("username")
    amount = data.get("amount")

    return fine_user(username, amount)


@app.route("/api/mute_user", methods=["POST"])
@requires_mod
def mute_user_endpoint():
    data = request.get_json()
    username = data.get("username")
    length = data.get("length")

    return mute_user(username, length)


@app.route("/api/unmute_user", methods=["POST"])
@requires_mod
def unmute_user_endpoint():
    data = request.get_json()
    username = data.get("username")

    return unmute_user(username)


@app.route("/api/users", methods=["GET"])
@requires_mod
def users_endpoint():
    return get_users()


@app.route("/api/delete_message", methods=["POST"])
@requires_mod
def delete_message_endpoint():
    data = request.get_json()
    message_id = data.get("message_id")

    return delete_message(message_id)


@app.route("/api/set_banner", methods=["POST"])
@requires_admin
def set_banner_endpoint():
    data = request.get_json()
    banner = data.get("banner")

    return set_banner(banner)


# Stripe
@app.route("/api/create_subscription", methods=["POST"])
@requires_unbanned
def create_subscription():
    data = request.get_json()
    price_id = data.get("price_id")

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card", "paypal"],
            line_items=[{"price": price_id, "quantity": 1}],
            mode="subscription",
            success_url=os.environ.get(
                "STRIPE_SUCCESS_URL", "https://economix.proplayer919.dev"
            ),
            cancel_url=os.environ.get(
                "STRIPE_CANCEL_URL", "https://economix.proplayer919.dev"
            ),
            metadata={"username": request.username},
        )
        return jsonify({"sessionId": session.id})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/stripe_webhook", methods=["POST"])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except ValueError as e:
        return jsonify({"error": "Invalid payload"}), 400
    except stripe.error.SignatureVerificationError as e:
        return jsonify({"error": "Invalid signature"}), 400

    # Handle subscription events
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        username = session["metadata"]["username"]
        subscription_id = session["subscription"]

        subscription = stripe.Subscription.retrieve(subscription_id)
        price = stripe.Price.retrieve(subscription["items"]["data"][0]["price"]["id"])
        product = stripe.Product.retrieve(price["product"])

        price_lookup_key = price.lookup_key

        if price_lookup_key == "pro_monthly":
            plan = "pro"
        elif price_lookup_key == "pro_yearly":
            plan = "pro"
        elif price_lookup_key == "proplus_monthly":
            plan = "proplus"
        elif price_lookup_key == "proplus_yearly":
            plan = "proplus"

        users_collection.update_one(
            {"username": username},
            {
                "$push": {
                    "subscriptions": {
                        "subscription_id": subscription_id,
                        "price_id": price["id"],
                        "product": product["name"],
                        "interval": price["recurring"]["interval"],
                        "status": subscription["status"],
                        "current_period_end": subscription["current_period_end"],
                        "plan": plan,
                    }
                }
            },
        )
        
        send_discord_notification(
            f"New Subscription",
            f"{username} has subscribed to the {plan} plan",
        )

    elif event["type"] in [
        "customer.subscription.updated",
        "customer.subscription.deleted",
    ]:
        subscription = event["data"]["object"]
        users_collection.update_one(
            {"subscriptions.subscription_id": subscription["id"]},
            {
                "$set": {
                    "subscriptions.$.status": subscription["status"],
                    "subscriptions.$.current_period_end": subscription[
                        "current_period_end"
                    ],
                }
            },
        )

    return jsonify({"success": True}), 200
