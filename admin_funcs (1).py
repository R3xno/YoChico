import asyncio
import html
import time
from decimal import Decimal

from telethon import events, Button
from telethon.errors import MessageNotModifiedError
from telethon.tl.functions.users import GetFullUserRequest as GetFullUser
from telethon.tl.types import InputUser

from bot import client, config, admins, verified, bid_banned, sub_banned, auction_pokes, auction_channel_id, \
    bot_username, bid_logs_id, user_db, previous_data, final_logs_id, rejected_pokes
from profile_card import render_profile

# Bot owners (always allowed, can add/remove admins)
OWNERS = [8511293134, 1101488645]


# ===========================================================================
# SHARED AUCTION HELPERS (used by pokemon_adder.py too)
# ===========================================================================
# ---------------------------------------------------------------------------
# Config  (change here if names change again)
# ---------------------------------------------------------------------------
AUCTION_CHANNEL = "HexaAuction"     # auction channel username (no @)
TRADE_GROUP = "HexaAuctionGc"       # trade / support group username (no @)
BID_GROUP_ID = -1001207853384       # group where people reply "/bid 1k" to an item post

# Permanent stats live in the same database as auction_pokes,
# so nothing has to be added to bot.py.
_db = auction_pokes.database
approved_items = _db["approved_items"]   # every item an admin ever approved
bought_items = _db["bought_items"]       # every item that was ever won in an auction


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def fmt(n):
    """1000 -> '1,000'"""
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return str(n)


def parse_amount(text):
    """'1000', '1,000', '1k', '1.5k' -> int.  Returns False if invalid."""
    text = (text or "").strip().lower().replace(",", "")
    try:
        if text.endswith("k"):
            value = int(Decimal(text[:-1]) * 1000)
        else:
            value = int(text)
    except (ValueError, OverflowError, ArithmeticError):
        return False
    return value if value > 0 else False


def md_link(user_id, name):
    name = str(name or "User").replace("[", "(").replace("]", ")")
    return f"[{name}](tg://user?id={user_id})"


def html_link(user_id, name):
    return f'<a href="tg://user?id={user_id}">{html.escape(str(name or "User"))}</a>'


def item_link(poke):
    """Always build the post link with the CURRENT channel username.
    Old items saved with the old channel name get fixed automatically
    because only the message id is taken from the stored link."""
    mid = poke.get("msg_id")
    if mid is None:
        try:
            mid = int(str(poke.get("link", "")).rstrip("/").split("/")[-1])
        except (ValueError, TypeError):
            return f"https://t.me/{AUCTION_CHANNEL}"
    return f"https://t.me/{AUCTION_CHANNEL}/{mid}"


def bid_url(token):
    """Deep link that opens the bot to bid on an item."""
    return f"https://t.me/{str(bot_username).lstrip('@')}?start={token}"


def ref_link(user_id):
    return f"https://t.me/{str(bot_username).lstrip('@')}?start=ref_{user_id}"


# ---------------------------------------------------------------------------
# Bid rules
# ---------------------------------------------------------------------------
def min_increase(last_bid):
    if last_bid <= 50000:
        return 500
    if last_bid <= 100000:
        return 1000
    return 2000


def min_increase_ok(last_bid, new_bid):
    return new_bid - last_bid >= min_increase(last_bid)


def not_accepted_text(last_bid):
    """Short, clear 'bid rejected' message that tells the user exactly what to bid."""
    return (
        "❌ **Bid Not Accepted**\n\n"
        f"Current highest bid: **{fmt(last_bid)}**\n"
        f"Minimum next bid: **{fmt(last_bid + min_increase(last_bid))}**\n\n"
        "**Minimum increase**\n"
        "• Up to 50,000 → +500\n"
        "• 50,001 – 100,000 → +1,000\n"
        "• Above 100,000 → +2,000"
    )


def check_can_bid(user_id, token):
    """-> (item_doc, error_text).  error_text is None when the user may bid."""
    res = config.find_one({"_id": 0}) or {}
    if not res.get("bid", False):
        return None, "🔒 Bidding is currently closed."
    if user_id not in verified:
        return None, (f"⚠️ **Verification Required**\n\n"
                      f"Only verified members can bid. Please ask an admin in @{TRADE_GROUP} to verify you.")
    if user_id in bid_banned:
        return None, "🚫 You are restricted from bidding."
    doc = auction_pokes.find_one({"token": token})
    if doc is None:
        return None, "❌ This item is no longer available."
    if doc.get("ended"):
        return None, "🔒 This auction has ended."
    if user_id == doc["user_id"]:
        return None, "❌ You cannot bid on your own item."
    return doc, None


_locks = {}


async def place_bid(token, user_id, amount):
    """Validate against the LIVE item (not what the user saw earlier) and save.
    -> (error, doc, last_bid, last_bidder).  error is None when the bid counted."""
    lock = _locks.setdefault(token, asyncio.Lock())
    async with lock:
        doc, err = check_can_bid(user_id, token)
        if err:
            return err, None, None, None
        if doc["bids"]:
            last_bid, last_bidder = doc["bids"][-1], doc["bidders"][-1]
        else:
            last_bid, last_bidder = doc["base"], None
        if not min_increase_ok(last_bid, amount):
            return not_accepted_text(last_bid), None, None, None
        auction_pokes.update_one({"token": token},
                                 {"$push": {"bids": amount, "bidders": user_id}})
    return None, doc, last_bid, last_bidder


# ---------------------------------------------------------------------------
# Item post (channel message) -> carries the bid box + Bid button
# ---------------------------------------------------------------------------
def bid_box(amount, user_id=None, name=None):
    """Boxed 'Highest Bid / By' block shown at the bottom of every item post:

    ╭──────────────────────╮
        Highest Bid: 171,000 Pd
        By: Enryu
    ╰──────────────────────╯
    """
    who = " ".join(str(name or "User").split())
    if len(who) > 28:
        who = who[:27] + "…"
    line1 = f"Highest Bid: {fmt(amount)} Pd"
    line2 = f"By: {who}" if user_id else "By: No bids yet"
    inner = max(len(line1), len(line2)) + 8
    return ("<pre>"
            f"╭{'─' * inner}╮\n"
            f"    {html.escape(line1)}\n"
            f"    {html.escape(line2)}\n"
            f"╰{'─' * inner}╯"
            "</pre>")


def post_buttons(token):
    return [[Button.url("Bid", bid_url(token))]]


async def refresh_post(doc, amount=None, bidder_id=None, name=None):
    """Rewrite the item's own channel post: original text + bid box + Bid button.
    No amount/bidder = base price, 'No bids yet'."""
    mid = doc.get("msg_id")
    if mid is None:
        return
    if amount is None:
        amount = doc["base"]
    if bidder_id and not name:
        try:
            name = (await client.get_entity(bidder_id)).first_name
        except Exception:
            name = None
    text = f"{doc['text']}\n\n{bid_box(amount, bidder_id, name)}"
    try:
        await client.edit_message(auction_channel_id, mid, text, parse_mode="html",
                                  link_preview=False, buttons=post_buttons(doc["token"]))
    except MessageNotModifiedError:
        pass
    # Items posted before this update have a separate bid message -> remove it
    old = doc.get("bmid")
    if old and old != mid:
        try:
            await client.delete_messages(auction_channel_id, old)
        except Exception:
            pass
        auction_pokes.update_one({"token": doc["token"]}, {"$set": {"bmid": mid}})


def _item_head(doc):
    link = item_link(doc)
    if doc.get("tipe", 0) < 3:
        return (f"🔹 **Pokémon:** {doc['pokemon_name']} [🔗]({link})\n"
                f"🌿 **Nature:** {doc['nature']}\n\n")
    return (f"🔹 **TM:** {doc['pokemon_name']} [🔗]({link})\n"
            f"🌿 **Nature:** {doc['nature']}\n\n")


async def announce_bid(doc, sender, amount, last_bid, last_bidder):
    """After a bid counted: update the post, write the bid log, DM the outbid user."""
    name = sender.first_name or "User"
    who = md_link(sender.id, name)
    head = _item_head(doc)

    try:
        await refresh_post(doc, amount, sender.id, name)
    except Exception as e:
        print("post refresh failed:", e)

    try:
        await client.send_message(
            bid_logs_id,
            f"🔔 **New Bid**\n"
            f"👤 **Bidder:** {who}\n\n"
            f"{head}"
            f"📈 **Current Bid:** {fmt(amount)}\n"
            f"💸 **Previous Bid:** {fmt(last_bid)}\n"
            f"📊 **Increase:** +{fmt(amount - last_bid)}")
    except Exception as e:
        print("bid log failed:", e)

    if last_bidder:
        try:
            await client.send_message(
                last_bidder,
                f"⚠️ **You Have Been Outbid**\n\n"
                f"{who} placed a higher bid on:\n\n"
                f"{head}"
                f"💸 **Your Bid:** {fmt(last_bid)}\n"
                f"📈 **Current Bid:** {fmt(amount)}\n"
                f"📊 **Difference:** +{fmt(amount - last_bid)}\n\n"
                f"Place a higher bid to take the lead again.",
                buttons=[[Button.url("🛒 Bid Again", bid_url(doc["token"]))]])
        except Exception as e:
            print("outbid dm failed:", e)


# ---------------------------------------------------------------------------
# Referral / auction points
# ---------------------------------------------------------------------------
def ensure_user(sender):
    if user_db.find_one({"_id": sender.id}) is None:
        user_db.insert_one({"_id": sender.id, "hash": sender.access_hash})


def get_points(user_id):
    return (user_db.find_one({"_id": user_id}) or {}).get("auction_points", 0)


def referral_count(user_id):
    return user_db.count_documents({"referred_by": user_id})


# ---------------------------------------------------------------------------
# Permanent stats (shown in /profile)
# ---------------------------------------------------------------------------
def approved_row(doc, admin_id=None):
    return {"token": doc.get("token"), "user_id": doc.get("user_id"),
            "tipe": doc.get("tipe"), "pokemon_name": doc.get("pokemon_name"),
            "nature": doc.get("nature"), "base": doc.get("base"),
            "link": doc.get("link"), "approved_by": admin_id,
            "approved_at": time.time()}


def sold_row(doc):
    return {"token": doc.get("token"), "tipe": doc.get("tipe"),
            "pokemon_name": doc.get("pokemon_name"), "nature": doc.get("nature"),
            "seller_id": doc.get("user_id"), "buyer_id": doc["bidders"][-1],
            "price": doc["bids"][-1], "link": doc.get("link"),
            "bought_at": time.time()}


def record_sold(docs):
    """Store every item that got at least one bid (= it was won)."""
    rows = [sold_row(d) for d in docs if d.get("bids") and d.get("bidders")]
    if rows:
        bought_items.insert_many(rows)
    return len(rows)


def type_counts(coll, **flt):
    """[legendary, non-legendary, shiny, tms] counts"""
    return [coll.count_documents({**flt, "tipe": t}) for t in range(4)]


# ---------------------------------------------------------------------------
# Permission checks
# NOTE: Telethon freezes `from_users=admins` when the handler is registered,
# so admins added later (via /addadmin) were NOT recognised until a restart.
# Using `func=` checks the live `admins` list on every message instead.
# ---------------------------------------------------------------------------
def owner_only(event):
    return event.sender_id in OWNERS


def admin_only(event):
    return event.sender_id in admins or event.sender_id in OWNERS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def get_target(event):
    """Return (user_id, error). Works with reply, numeric id, @username or username."""
    if event.is_reply:
        replied = await event.get_reply_message()
        if replied and replied.sender_id:
            return replied.sender_id, None
        return None, "❌ Could not identify the user from the replied message."

    parts = event.raw_text.split(maxsplit=1)
    if len(parts) < 2:
        return None, "❌ Reply to a user, or provide a user ID or @username."

    arg = parts[1].strip()
    if arg.lstrip("-").isdigit():
        return int(arg), None
    try:
        peer = await client.get_entity(arg.lstrip("@"))
        return peer.id, None
    except Exception:
        return None, f"❌ Could not find the user `{arg}`."


async def add_user(event, lst, field, already_msg, done_msg="✅ Done."):
    uid, err = await get_target(event)
    if err:
        return await event.reply(err)
    if uid in lst:
        return await event.reply(already_msg)
    lst.append(uid)
    config.update_one({"_id": 0}, {"$addToSet": {field: uid}}, upsert=True)
    await event.reply(done_msg)


async def remove_user(event, lst, field, not_in_msg, done_msg):
    uid, err = await get_target(event)
    if err:
        return await event.reply(err)
    if uid not in lst:
        return await event.reply(not_in_msg)
    lst.remove(uid)
    config.update_one({"_id": 0}, {"$pull": {field: uid}}, upsert=True)
    await event.reply(done_msg)


def get_auction_state():
    res = config.find_one({"_id": 0}) or {}
    return res.get("auction", False)


async def toggle_setting(event, key, label):
    """Toggle entry/bid. Locked (cannot be changed) while the auction is off."""
    action = event.pattern_match.group(1).lower()

    if not get_auction_state():
        return await event.reply(
            f"🔒 **{label} is locked**\n"
            f"The auction is currently off. Use /auction on to open it."
        )

    res = config.find_one({"_id": 0}) or {}
    current_state = res.get(key, False)

    if action == "on":
        if current_state:
            return await event.reply(f"ℹ️ {label} is already enabled.")
        config.update_one({"_id": 0}, {"$set": {key: True}}, upsert=True)
        await event.reply(f"✅ {label} has been enabled.")
    else:
        if not current_state:
            return await event.reply(f"ℹ️ {label} is already disabled.")
        config.update_one({"_id": 0}, {"$set": {key: False}}, upsert=True)
        await event.reply(f"🔒 {label} has been disabled.")


async def get_first_name(user_id):
    """Best-effort lookup of a user's first name."""
    user_id = int(user_id)
    # 1) Using the stored access hash
    try:
        target = user_db.find_one({"_id": user_id})
        if target:
            user = await client(GetFullUser(InputUser(user_id=target["_id"], access_hash=target["hash"])))
            return user.users[0].first_name
    except Exception:
        pass
    # 2) Fallback to Telethon's entity cache / lookup
    try:
        entity = await client.get_entity(user_id)
        return entity.first_name or "User"
    except Exception:
        return "User"


async def get_mention(user_id):
    """Return a markdown mention: [Name](tg://user?id=ID) - no raw IDs shown."""
    name = await get_first_name(user_id)
    name = str(name).replace("[", "(").replace("]", ")")
    return f"[{name}](tg://user?id={int(user_id)})"


def validate_base(base):
    try:
        return int(base)
    except (ValueError, TypeError):
        try:
            if str(base).lower().endswith("k"):
                return int(float(str(base)[:-1]) * 1000)
        except ValueError:
            pass
    return False


# ---------------------------------------------------------------------------
# Owner commands
# ---------------------------------------------------------------------------
@client.on(events.NewMessage(pattern=r"^/clear_db\b", func=owner_only))
async def clear_db(event):
    auction_pokes.delete_many({})
    await event.reply("✅ All auction items have been cleared.")


@client.on(events.NewMessage(pattern=r"^/addadmin\b", func=owner_only))
async def addadmin(event):
    await add_user(event, admins, "admins", "ℹ️ This user is already an admin.", "✅ Admin added.")


@client.on(events.NewMessage(pattern=r"^/remadmin\b", func=owner_only))
async def remadmin(event):
    await remove_user(event, admins, "admins", "ℹ️ This user is not an admin.", "✅ Admin removed.")


# ---------------------------------------------------------------------------
# Admin commands
# ---------------------------------------------------------------------------
@client.on(events.NewMessage(pattern=r"^/entry\s+(on|off)\b", func=admin_only))
async def entry(event):
    await toggle_setting(event, "entry", "Submissions")


@client.on(events.NewMessage(pattern=r"^/bid\s+(on|off)\b", func=admin_only))
async def bid(event):
    await toggle_setting(event, "bid", "Bidding")


@client.on(events.NewMessage(pattern=r"^/auction\s+(on|off)\b", func=admin_only))
async def auction(event):
    action = event.pattern_match.group(1).lower()
    current_state = get_auction_state()

    if action == "on":
        if current_state:
            return await event.reply("ℹ️ The auction is already running.")
        # New auction -> only NOW the previous auction's items are cleared.
        # (They stay visible in /myitem, /mybids and /item while the auction is off.)
        auction_pokes.delete_many({"ended": True})
        # Auction on -> submission (entry) and bidding open automatically
        config.update_one({"_id": 0},
                          {"$set": {"auction": True, "entry": True, "bid": True}},
                          upsert=True)
        return await event.reply("✅ **Auction Started**\nSubmissions and bidding are now open.")

    # action == "off"
    if not current_state:
        return await event.reply("ℹ️ The auction is already off.")
    # Auction off -> submission (entry) and bidding locked automatically
    config.update_one({"_id": 0},
                      {"$set": {"auction": False, "entry": False, "bid": False}},
                      upsert=True)
    await event.reply("🔒 **Auction Ended**\n"
                      "Submissions and bidding are now closed.\n"
                      "Items and bids stay available until the next auction starts.")

    # Items are KEPT (marked as ended). They are only removed when /auction on is used again.
    docs = list(auction_pokes.find({"ended": {"$ne": True}}))
    await event.reply("📨 Sending final results to sellers and buyers…")
    if docs:
        archive = [{k: v for k, v in d.items() if k != "_id"} for d in docs]
        previous_data.insert_many(archive)
        record_sold(archive)   # permanent "sold" history for /profile
        auction_pokes.update_many({"token": {"$in": [d["token"] for d in docs]}},
                                  {"$set": {"ended": True}})

    for doc in docs:
        # remove the Bid button from every post (sold or unsold)
        try:
            await client.edit_message(auction_channel_id, doc.get("msg_id") or doc.get("bmid"),
                                      buttons=Button.clear())
        except Exception:
            pass
        if not doc.get("bids") or not doc.get("bidders"):
            continue   # unsold item, nothing to announce
        try:
            seller = await get_mention(doc['user_id'])
            buyer = await get_mention(doc['bidders'][-1])
            text = (
                f"🔹 **Pokémon:** {doc['pokemon_name']}\n"
                f"🌿 **Nature:** {doc['nature']}\n"
                f"📊 **Base:** `{fmt(doc['base'])}`\n"
                f"🆔 **Item ID:** `{doc['token']}`\n"
                f"🔗 [View Pokémon]({item_link(doc)})\n\n"
                f"👤 **Buyer:** {buyer}\n"
                f"💵 **Final Price:** `{fmt(doc['bids'][-1])}`"
            )
        except Exception:
            print("skipping")
            continue
        await asyncio.sleep(1)
        try:
            await client.send_message(final_logs_id, f"🧾 **Auction Result**\n👤 **Seller:** {seller}\n" + text)
        except Exception:
            pass
        await asyncio.sleep(1)
        try:
            await client.send_message(doc['user_id'], f"✅ **Your Item Was Sold**\n\n{text}")
        except Exception:
            pass
        try:
            await client.send_message(doc['bidders'][-1], f"🏆 **You Won This Auction**\n\n{text}")
        except Exception:
            pass

    await event.reply("✅ Final results sent.")


@client.on(events.NewMessage(pattern=r"^/verify\b", func=admin_only))
async def verify(event):
    await add_user(event, verified, "verified", "ℹ️ This user is already verified.", "✅ User verified.")


@client.on(events.NewMessage(pattern=r"^/unverify\b", func=admin_only))
async def unverify(event):
    await remove_user(event, verified, "verified", "ℹ️ This user is not verified.", "✅ User unverified.")


@client.on(events.NewMessage(pattern=r"^/bban\b", func=admin_only))
async def bid_ban(event):
    await add_user(event, bid_banned, "bid_banned", "ℹ️ This user is already banned from bidding.",
                   "✅ User banned from bidding.")


@client.on(events.NewMessage(pattern=r"^/b_unban\b", func=admin_only))
async def bid_unban(event):
    await remove_user(event, bid_banned, "bid_banned", "ℹ️ This user is not banned from bidding.",
                      "✅ User unbanned from bidding.")


@client.on(events.NewMessage(pattern=r"^/sban\b", func=admin_only))
async def sub_ban(event):
    await add_user(event, sub_banned, "sub_banned", "ℹ️ This user is already banned from submissions.",
                   "✅ User banned from submissions.")


@client.on(events.NewMessage(pattern=r"^/s_unban\b", func=admin_only))
async def sub_unban(event):
    await remove_user(event, sub_banned, "sub_banned", "ℹ️ This user is not banned from submissions.",
                      "✅ User unbanned from submissions.")


@client.on(events.NewMessage(pattern=r"^/remitem\b", func=admin_only))
async def remitem(event):
    mess_sp = event.raw_text.split(" ", 2)
    if len(mess_sp) < 2:
        return await event.reply("❌ **Usage:** `/remitem <item_id> [reason]`")
    item_id = mess_sp[1]
    mm = auction_pokes.find_one_and_delete({"token": item_id})
    if mm is None:
        return await event.reply("❌ Item not found.")
    try:
        if mm.get("bmid"):
            await client.delete_messages(auction_channel_id, mm["bmid"])
    except Exception:
        pass
    try:
        await client.delete_messages(auction_channel_id, int(mm["link"].split("/")[-1]))
    except Exception:
        pass
    try:
        note = f"🗑 **Item Removed**\n\n🔹 {mm['nature']} {mm['pokemon_name']}\nIt was removed by the admins."
        if len(mess_sp) == 3:
            note += f"\n📝 **Reason:** {mess_sp[2]}"
        await client.send_message(mm["user_id"], note)
    except Exception:
        pass
    await event.reply("✅ Item removed.")


@client.on(events.NewMessage(pattern=r"^/resetbid\b", func=admin_only))
async def resetbid(event):
    mess_sp = event.raw_text.split(" ")
    if len(mess_sp) != 2:
        return await event.reply("❌ **Usage:** `/resetbid <item_id>`")
    item_id = mess_sp[1]
    mm = auction_pokes.find_one_and_update({"token": item_id}, {"$set": {"bids": [], "bidders": []}})
    if mm is None:
        return await event.reply("❌ Item not found.")
    await refresh_post(mm)
    await event.reply("✅ Bids have been reset.")


@client.on(events.NewMessage(pattern=r"^/setbid\b", func=admin_only))
async def setbid(event):
    mess_sp = event.raw_text.split(" ", 3)
    if len(mess_sp) != 4:
        return await event.reply("❌ **Usage:** `/setbid <item_id> <user_id> <amount>`")

    item_id, user_str, amount_str = mess_sp[1], mess_sp[2], mess_sp[3].strip()
    if not user_str.isdigit():
        return await event.reply("❌ The user ID must be a number.")
    user_id = int(user_str)

    target = user_db.find_one({"_id": user_id})
    if target is None:
        return await event.reply("❌ This user is not in the database.")

    if auction_pokes.find_one({"token": item_id}) is None:
        return await event.reply("❌ Item not found.")

    amount = validate_base(amount_str)
    if not amount:
        return await event.reply("❌ Invalid bid amount.")

    mm = auction_pokes.find_one_and_update({"token": item_id},
                                           {"$push": {"bids": amount, "bidders": user_id}})
    await refresh_post(mm, amount, user_id, await get_first_name(user_id))
    await event.reply("✅ Bid has been set.")


@client.on(events.NewMessage(pattern=r"^/rollback\b", func=admin_only))
async def rollback(event):
    mess_sp = event.raw_text.split(" ")
    if len(mess_sp) < 2:
        return await event.reply("❌ **Usage:** `/rollback <item_id> [count]`")

    item_id = mess_sp[1]
    num = 1  # default rollback count

    if len(mess_sp) >= 3:
        if not mess_sp[2].isdigit():
            return await event.reply("❌ The number of bids to roll back must be a whole number.")
        num = int(mess_sp[2])
        if num <= 0:
            return await event.reply("❌ The number of bids to roll back must be greater than zero.")

    doc = auction_pokes.find_one({"token": item_id})
    if not doc:
        return await event.reply("❌ Item not found.")

    bids = doc.get("bids", [])
    bidders = doc.get("bidders", [])

    if len(bids) < num or len(bidders) < num:
        return await event.reply(f"❌ Cannot roll back {num} bid(s). This item only has {len(bids)}.")

    new_bids = bids[:-num]
    new_bidders = bidders[:-num]

    auction_pokes.find_one_and_update(
        {"token": item_id},
        {"$set": {"bids": new_bids, "bidders": new_bidders}}
    )

    if len(new_bids) == 0:
        await refresh_post(doc)
        await event.reply(f"✅ Rolled back {num} bid(s).\nNo bids remain on this item.")
    else:
        mention = await get_mention(new_bidders[-1])
        await refresh_post(doc, new_bids[-1], new_bidders[-1], await get_first_name(new_bidders[-1]))
        await event.reply(f"✅ Rolled back {num} bid(s).\n\n"
                          f"💰 **Current bid:** {fmt(new_bids[-1])}\n"
                          f"👤 **Current bidder:** {mention}")


@client.on(events.NewMessage(pattern=r"^/msg\b", func=admin_only))
async def snipe(event):
    mess_sp = event.raw_text.split(" ", 2)
    if len(mess_sp) != 3 or not mess_sp[1].isdigit():
        return await event.reply("❌ **Usage:** `/msg <user_id> <message>`")
    try:
        await client.send_message(int(mess_sp[1]), mess_sp[2])
    except Exception:
        return await event.reply("❌ Message could not be delivered. The user may have blocked the bot.")
    await event.reply("✅ Message sent.")


@client.on(events.NewMessage(pattern=r"^/broadcast\b", func=admin_only))
async def bcast(event):
    replied_msg = None
    msg = None
    if event.is_reply:
        replied_msg = await event.get_reply_message()
    else:
        parts = event.raw_text.split(" ", 1)
        if len(parts) < 2:
            return await event.reply("❌ **Usage:** reply to a message, or send `/broadcast <message>`")
        msg = parts[1]

    await event.reply("📢 Broadcast started…")
    user_ids = [doc["_id"] for doc in user_db.find({}, {"_id": 1})]
    success = 0
    failed = 0

    for uid in user_ids:
        try:
            if replied_msg:
                await replied_msg.forward_to(uid)
            else:
                await client.send_message(uid, msg)
            success += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.1)  # avoid flood limits

    await event.reply(f"✅ **Broadcast Complete**\n\n📬 Delivered: {success}\n⚠️ Failed: {failed}")


@client.on(events.NewMessage(pattern=r"^/backfill_stats\b", func=owner_only))
async def backfill_stats(event):
    """One-time: copy items from before this update (past auctions + live auction) into the
    permanent approved/bought history. Safe to run again, duplicates are skipped."""
    added_a = added_b = 0
    for src, ended in ((previous_data, True), (auction_pokes, False)):
        for d in src.find():
            if approved_items.find_one({"token": d.get("token"), "user_id": d.get("user_id")}) is None:
                approved_items.insert_one(approved_row(d))
                added_a += 1
            if ended and d.get("bids") and d.get("bidders") and \
                    bought_items.find_one({"token": d.get("token"), "seller_id": d.get("user_id")}) is None:
                bought_items.insert_one(sold_row(d))
                added_b += 1
    await event.reply(f"✅ **Backfill Complete**\n\n📥 Approved added: {added_a}\n📥 Sold added: {added_b}")


# ---------------------------------------------------------------------------
# Public command
# ---------------------------------------------------------------------------
async def _profile_identity(uid):
    """-> (entity_or_None, first_name, username)"""
    try:
        ent = await client.get_entity(uid)
        return ent, (getattr(ent, "first_name", None) or "User"), getattr(ent, "username", None)
    except Exception:
        return None, await get_first_name(uid), None


async def _avatar_bytes(entity):
    if entity is None:
        return None
    try:
        return await client.download_profile_photo(entity, file=bytes) or None
    except Exception:
        return None


@client.on(events.NewMessage(pattern=r"^/profile\b"))
async def profile(event):
    parts = event.raw_text.split()
    if event.is_reply or len(parts) >= 2:
        uid, err = await get_target(event)
        if err:
            return await event.reply(err)
    else:
        uid = event.sender_id

    if uid in admins or uid in OWNERS:
        status = "admin"
    elif uid in verified:
        status = "verified"
    else:
        status = "unverified"

    approved = type_counts(approved_items, user_id=uid)     # [legendary, non-legendary, shiny, tms]
    sold = type_counts(bought_items, seller_id=uid)
    points = get_points(uid)

    entity, name, username = await _profile_identity(uid)
    avatar = await _avatar_bytes(entity)

    try:
        loop = asyncio.get_running_loop()
        png = await loop.run_in_executor(
            None, lambda: render_profile(name, username, status, approved, sold, points, avatar))
        return await event.reply(file=png)
    except Exception as e:
        print("profile image failed:", e)

    # Text fallback (only used if the image could not be generated)
    label = {"admin": "Admin", "verified": "Verified", "unverified": "Unverified"}[status]
    await event.reply(
        f"👤 **{md_link(uid, name)}** · {label}\n\n"
        f"⭐ **Auction Points:** {points}\n\n"
        f"**Approved**\n"
        f"Legendary: {approved[0]} · Non-Legendary: {approved[1]} · Shiny: {approved[2]} · TMs: {approved[3]}\n\n"
        f"**Sold**\n"
        f"Legendary: {sold[0]} · Non-Legendary: {sold[1]} · Shiny: {sold[2]} · TMs: {sold[3]}")
