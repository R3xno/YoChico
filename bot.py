from telethon import TelegramClient
from pymongo import MongoClient

api_id = 3344739
api_hash = '88d43ee045dd90660b4360ba59fe3c48'
bot_token = "8254395927:AAHwL61XSmJ4kNlTwjyOZSkZDT0b68xUw_Q"

client = TelegramClient('zaaasuctionbot', api_id, api_hash).start(bot_token=bot_token)

# MongoDB setup
url = "mongodb+srv://adsbroone_db_user:<njRUYBVrNE0o1a2D>@cluster0.tf0jrql.mongodb.net/"
mongo_client = MongoClient(url)
db = mongo_client["auction_db"]
pending_pokes = db["pending_pokes"]
rejected_pokes = db["rejected_pokes"]
config = db["config"]
auction_pokes = db["kekz"]
previous_data = db["previous_data"]
user_db = db["user"]
x = config.find_one({"_id": 0})
admins = x.get("admins", [])
sub_banned = x.get("sub_banned", [])
bid_banned = x.get("bid_banned", [])
verified = x.get("verified", [])
admins.append(8511293134)
for i in admins:
    verified.append(i)
auction_channel_id = -1001450650460
admin_grp_id = -1004367307888
bid_logs_id = -1004367307888
final_logs_id = -1004367307888
bot_username = "HexaAuctionRobot"
user_cache = {}

