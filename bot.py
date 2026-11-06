from telethon import TelegramClient
from pymongo import MongoClient

api_id = 3344739
api_hash = '88d43ee045dd90660b4360ba59fe3c48'
bot_token = "8254395927:AAE2G6zMMQ-7keKBNV1nNxpShKcpY0jejXw"
client = TelegramClient('zaaasuctionbot', api_id, api_hash).start(bot_token=bot_token)

# MongoDB setup
url = "mongodb+srv://adsbroone_db_user:njRUYBVrNE0o1a2D@cluster0.tf0jrql.mongodb.net/"
mongo_client = MongoClient(url)
db = mongo_client["auction_db"]
pending_pokes = db["pending_pokes"]
rejected_pokes = db["rejected_pokes"]
config = db["config"]
auction_pokes = db["kekz"]
previous_data = db["previous_data"]
user_db = db["user"]
x = config.find_one({"_id": 0})
if x is None:
    config.insert_one({
        "_id": 0,
        "admins": [],
        "verify_admins": [],
        "sub_banned": [],
        "bid_banned": [],
        "verified": [],
    })
    x = config.find_one({"_id": 0})

admins = x.get("admins", [])
verify_admins = x.get("verify_admins", [])   # admins allowed to use /verify and /unverify
sub_banned = x.get("sub_banned", [])
bid_banned = x.get("bid_banned", [])
verified = x.get("verified", [])
admins.append(8511293134)
for i in admins:
    verified.append(i)

# Bot owners (always allowed; only they can add/remove admins, verify-admins
# and use /auction on|off)
OWNERS = [8511293134, 1101488645]

auction_channel_id = -1001450650460
admin_grp_id = -1004367307888
bid_logs_id = -1004482113013
final_logs_id = -1004482113013
bot_username = "HexaAuctionRobot"
user_cache = {}

# ---------------------------------------------------------------------------
# Join requirement: users must be in BOTH of these to use the bot at all.
# The bot must be ADMIN in the channel and a member (ideally admin) of the group
# so it can check membership.
# ---------------------------------------------------------------------------
REQUIRED_CHATS = [
    {
        "name": "@HexaAuction (Auction Channel)",
        "button": "Auction Channel",
        "refs": [auction_channel_id, "HexaAuction"],
        "url": "https://t.me/HexaAuction",
    },
    {
        "name": "Private Group",
        "button": "Private Group",
        "refs": [-1001207853384],
        "url": "https://t.me/+XkEYWzNquJFlZTE9",
    },
]
