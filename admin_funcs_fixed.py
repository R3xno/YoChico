import asyncio

from telethon import events, Button
from telethon.tl.functions.users import GetFullUserRequest as GetFullUser
from telethon.tl.types import InputUser

from bot import client, config, admins, verified, bid_banned, sub_banned, auction_pokes, auction_channel_id, \
    bot_username, user_db, previous_data, final_logs_id, rejected_pokes

# Bot owners (always allowed, can add/remove admins)
OWNERS = [8511293134, 1101488645]


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
        return None, "Couldn't read the user from the replied message."

    parts = event.raw_text.split(maxsplit=1)
    if len(parts) < 2:
        return None, "Reply to a user or provide a user ID or @username."

    arg = parts[1].strip()
    if arg.lstrip("-").isdigit():
        return int(arg), None
    try:
        peer = await client.get_entity(arg.lstrip("@"))
        return peer.id, None
    except Exception as e:
        return None, f"❌ Error getting user {arg}: {e}"


async def add_user(event, lst, field, already_msg, done_msg="Done"):
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
            f"🔒 Auction is off, so {label} is locked.\n"
            f"Start the auction with /auction on to open it."
        )

    res = config.find_one({"_id": 0}) or {}
    current_state = res.get(key, False)

    if action == "on":
        if current_state:
            return await event.reply(f"{label} is already enabled.")
        config.update_one({"_id": 0}, {"$set": {key: True}}, upsert=True)
        await event.reply(f"{label} has been enabled.")
    else:
        if not current_state:
            return await event.reply(f"{label} is already disabled.")
        config.update_one({"_id": 0}, {"$set": {key: False}}, upsert=True)
        await event.reply(f"{label} has been disabled.")


def bid_text(amount, by):
    return f"""╭────────────────╮
    Highest Bid: {amount} Pd
    By: {by}
╰────────────────╯"""


def bid_buttons(item_id):
    return [[Button.inline("Refresh", f"refresh|{item_id}"),
             Button.url("Bid", f"t.me/{bot_username}?start={item_id}")]]


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
    await event.reply("Done")


@client.on(events.NewMessage(pattern=r"^/addadmin\b", func=owner_only))
async def addadmin(event):
    await add_user(event, admins, "admins", "Already admin.")


@client.on(events.NewMessage(pattern=r"^/remadmin\b", func=owner_only))
async def remadmin(event):
    await remove_user(event, admins, "admins", "User is not admin.", "Done")


# ---------------------------------------------------------------------------
# Admin commands
# ---------------------------------------------------------------------------
@client.on(events.NewMessage(pattern=r"^/entry\s+(on|off)\b", func=admin_only))
async def entry(event):
    await toggle_setting(event, "entry", "Entry")


@client.on(events.NewMessage(pattern=r"^/bid\s+(on|off)\b", func=admin_only))
async def bid(event):
    await toggle_setting(event, "bid", "Bid")


@client.on(events.NewMessage(pattern=r"^/auction\s+(on|off)\b", func=admin_only))
async def auction(event):
    action = event.pattern_match.group(1).lower()
    current_state = get_auction_state()

    if action == "on":
        if current_state:
            return await event.reply("Auction is already ongoing.")
        # Auction on -> submission (entry) and bidding open automatically
        config.update_one({"_id": 0},
                          {"$set": {"auction": True, "entry": True, "bid": True}},
                          upsert=True)
        return await event.reply("Auction started.\n✅ Submission and bidding are now open.")

    # action == "off"
    if not current_state:
        return await event.reply("Auction is already disabled.")
    # Auction off -> submission (entry) and bidding locked automatically
    config.update_one({"_id": 0},
                      {"$set": {"auction": False, "entry": False, "bid": False}},
                      upsert=True)
    await event.reply("Auction has been disabled.\n🔒 Submission and bidding are now locked.")

    docs = list(auction_pokes.find())
    await event.reply("Spam started")
    for doc in docs:
        doc.pop('_id', None)
    if docs:
        previous_data.insert_many(docs)

    for doc in docs:
        try:
            seller = await get_mention(doc['user_id'])
            buyer = await get_mention(doc['bidders'][-1])
            text = (
                f"🔹 **Pokémon:** {doc['pokemon_name']}\n"
                f"🌿 **Nature:** {doc['nature']}\n"
                f"📊 **Base:** `{doc['base']}`\n"
                f"🆔 **Item ID:** `{doc['token']}`\n"
                f"🔗 [View Pokémon]({doc['link']})\n\n"
                f"💰 **Buyer:** {buyer}\n"
                f"💵 **Price:** `{doc['bids'][-1]}`"
            )
        except Exception:
            print("skipping")
            continue
        await asyncio.sleep(1)
        try:
            await client.edit_message(auction_channel_id, doc['bmid'], buttons=Button.clear())
        except Exception:
            pass
        try:
            await client.send_message(final_logs_id, f"👤 **Seller:** {seller}\n" + text)
        except Exception:
            pass
        await asyncio.sleep(1)
        try:
            await client.send_message(doc['user_id'], text)
        except Exception:
            pass
        try:
            await client.send_message(doc['bidders'][-1], f"You won the bid for \n\n{text}")
        except Exception:
            pass

    auction_pokes.delete_many({})
    await event.reply("Spam done")


@client.on(events.NewMessage(pattern=r"^/verify\b", func=admin_only))
async def verify(event):
    await add_user(event, verified, "verified", "Already verified.")


@client.on(events.NewMessage(pattern=r"^/unverify\b", func=admin_only))
async def unverify(event):
    await remove_user(event, verified, "verified", "User is not verified.", "❌ User has been unverified.")


@client.on(events.NewMessage(pattern=r"^/bban\b", func=admin_only))
async def bid_ban(event):
    await add_user(event, bid_banned, "bid_banned", "Already banned from bidding.")


@client.on(events.NewMessage(pattern=r"^/b_unban\b", func=admin_only))
async def bid_unban(event):
    await remove_user(event, bid_banned, "bid_banned", "User is not banned from bidding.",
                      "✅ User has been unbanned.")


@client.on(events.NewMessage(pattern=r"^/sban\b", func=admin_only))
async def sub_ban(event):
    await add_user(event, sub_banned, "sub_banned", "Already banned from submission.")


@client.on(events.NewMessage(pattern=r"^/s_unban\b", func=admin_only))
async def sub_unban(event):
    await remove_user(event, sub_banned, "sub_banned", "User is not banned.", "✅ User has been unbanned.")


@client.on(events.NewMessage(pattern=r"^/remitem\b", func=admin_only))
async def remitem(event):
    mess_sp = event.raw_text.split(" ", 2)
    if len(mess_sp) < 2:
        return await event.reply("Please put item id for which it is to be removed.")
    item_id = mess_sp[1]
    mm = auction_pokes.find_one_and_delete({"token": item_id})
    if mm is None:
        return await event.reply("Auction item not found.")
    try:
        await client.delete_messages(auction_channel_id, mm["bmid"])
    except Exception:
        pass
    try:
        await client.delete_messages(auction_channel_id, int(mm["link"].split("/")[-1]))
    except Exception:
        pass
    try:
        if len(mess_sp) != 3:
            await client.send_message(mm["user_id"], f"Admins Removed {mm['nature']} {mm['pokemon_name']}")
        else:
            await client.send_message(mm["user_id"],
                                      f"Admins Removed {mm['nature']} {mm['pokemon_name']} cause {mess_sp[2]}")
    except Exception:
        pass
    await event.reply("Done")


@client.on(events.NewMessage(pattern=r"^/resetbid\b", func=admin_only))
async def resetbid(event):
    mess_sp = event.raw_text.split(" ")
    if len(mess_sp) != 2:
        return await event.reply("Please put item id for which it is to be reset.")
    item_id = mess_sp[1]
    mm = auction_pokes.find_one_and_update({"token": item_id}, {"$set": {"bids": [], "bidders": []}})
    if mm is None:
        return await event.reply("Auction item not found.")
    await client.edit_message(auction_channel_id, mm["bmid"],
                              bid_text(mm['base'], "No one right now!"),
                              buttons=bid_buttons(item_id))
    await event.reply("Done")


@client.on(events.NewMessage(pattern=r"^/setbid\b", func=admin_only))
async def setbid(event):
    mess_sp = event.raw_text.split(" ", 3)
    if len(mess_sp) != 4:
        return await event.reply("Invalid use like /setbid item_id user_id bid")

    item_id, user_str, amount_str = mess_sp[1], mess_sp[2], mess_sp[3].strip()
    if not user_str.isdigit():
        return await event.reply("User id must be a number.")
    user_id = int(user_str)

    target = user_db.find_one({"_id": user_id})
    if target is None:
        return await event.reply("Dunno that user..")

    if auction_pokes.find_one({"token": item_id}) is None:
        return await event.reply("Auction item not found.")

    amount = validate_base(amount_str)
    if not amount:
        return await event.reply("Incorrect bid amount.")

    mm = auction_pokes.find_one_and_update({"token": item_id},
                                           {"$push": {"bids": amount, "bidders": user_id}})
    mention = await get_mention(user_id)
    text = bid_text(amount, mention)
    await client.edit_message(auction_channel_id, mm["bmid"], text, buttons=bid_buttons(item_id))
    await event.reply("Done")


@client.on(events.NewMessage(pattern=r"^/rollback\b", func=admin_only))
async def rollback(event):
    mess_sp = event.raw_text.split(" ")
    if len(mess_sp) < 2:
        return await event.reply("Please provide the item id.")

    item_id = mess_sp[1]
    num = 1  # default rollback count

    if len(mess_sp) >= 3:
        if not mess_sp[2].isdigit():
            return await event.reply("Number of bids to rollback must be an integer.")
        num = int(mess_sp[2])
        if num <= 0:
            return await event.reply("Rollback number must be positive.")

    doc = auction_pokes.find_one({"token": item_id})
    if not doc:
        return await event.reply("Item ID not found.")

    bids = doc.get("bids", [])
    bidders = doc.get("bidders", [])

    if len(bids) < num or len(bidders) < num:
        return await event.reply(f"Cannot rollback {num} bids; only {len(bids)} bids exist.")

    new_bids = bids[:-num]
    new_bidders = bidders[:-num]

    auction_pokes.find_one_and_update(
        {"token": item_id},
        {"$set": {"bids": new_bids, "bidders": new_bidders}}
    )

    if len(new_bids) == 0:
        await client.edit_message(auction_channel_id, doc["bmid"],
                                  bid_text(doc['base'], "No one right now!"),
                                  buttons=bid_buttons(item_id))
        await event.reply(f"Rolled back {num} bids. No bids left now.")
    else:
        mention = await get_mention(new_bidders[-1])
        await client.edit_message(auction_channel_id, doc["bmid"],
                                  bid_text(validate_base(new_bids[-1]), mention),
                                  buttons=bid_buttons(item_id))
        await event.reply(f"Rolled back {num} bids.\n"
                          f"Current last bid: {new_bids[-1]}\n"
                          f"Current last bidder: {mention}")


@client.on(events.NewMessage(pattern=r"^/msg\b", func=admin_only))
async def snipe(event):
    mess_sp = event.raw_text.split(" ", 2)
    if len(mess_sp) != 3 or not mess_sp[1].isdigit():
        return await event.reply("Invalid use like /msg user_id msg")
    try:
        await client.send_message(int(mess_sp[1]), mess_sp[2])
    except Exception as e:
        return await event.reply(f"❌ Failed: {e}")
    await event.reply("Done")


@client.on(events.NewMessage(pattern=r"^/broadcast\b", func=admin_only))
async def bcast(event):
    replied_msg = None
    msg = None
    if event.is_reply:
        replied_msg = await event.get_reply_message()
    else:
        parts = event.raw_text.split(" ", 1)
        if len(parts) < 2:
            return await event.reply("Reply to a message or use /broadcast your message")
        msg = parts[1]

    await event.reply("Starting broadcast...")
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

    await event.reply(f"Broadcast completed.\n✅ Sent: {success}\n❌ Failed: {failed}")


# ---------------------------------------------------------------------------
# Public command
# ---------------------------------------------------------------------------
@client.on(events.NewMessage(pattern=r"^/profile\b"))
async def profile(event):
    parts = event.raw_text.split()
    if event.is_reply or len(parts) >= 2:
        uid, err = await get_target(event)
        if err:
            return await event.reply(err)
    else:
        uid = event.sender_id

    # Always show the user's name as a deep link, never the raw ID
    username = await get_mention(uid)

    post = "[❌](https://envs.sh/0ul.jpg) Not verified"
    if uid in verified:
        post = "[✅](https://envs.sh/0ul.jpg) Verified"
    if uid in admins or uid in OWNERS:
        post = "[👑](https://envs.sh/0ul.jpg) Admin"

    total_auc_count = auction_pokes.count_documents({"user_id": uid})
    rejected_auc_count = rejected_pokes.count_documents({"user_id": uid})
    l_count = auction_pokes.count_documents({'tipe': 0, "user_id": uid})
    ol_count = auction_pokes.count_documents({'tipe': 1, "user_id": uid})
    s_count = auction_pokes.count_documents({'tipe': 2, "user_id": uid})
    t_count = auction_pokes.count_documents({'tipe': 3, "user_id": uid})

    submitted = total_auc_count + rejected_auc_count
    kak_value = round((total_auc_count / submitted) * 100, 2) if submitted else 0

    format_m = f"""{username} {post}

〘 Total Approved 〙
   • ʟᴇɢᴇɴᴅᴀʀʏ : {l_count}
   • ɴᴏɴ-ʟᴇɢᴇɴᴅᴀʀʏ : {ol_count}
   • sʜɪɴʏ : {s_count}
   • ᴛᴍs : {t_count}

📊 Total submitted: {submitted}
☑️ Total approved: {total_auc_count}
⬜️ Approve Ratio: {kak_value}%"""
    await event.reply(format_m)
