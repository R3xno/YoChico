import asyncio

from telethon import events, Button
from telethon.errors import FloodWaitError, MessageNotModifiedError
from telethon.tl.functions.users import GetFullUserRequest as GetFullUser
from telethon.tl.types import InputUser, User

from bot import (client, config, admins, verified, bid_banned, sub_banned,
                 auction_pokes, auction_channel_id, bot_username, user_db,
                 previous_data, final_logs_id, rejected_pokes)

# ──────────────────────────────────────────────────────────────
#  OWNERS  (full control: /addadmin, /remadmin, /clear_db)
# ──────────────────────────────────────────────────────────────
OWNERS = [8511293134, 1101488645]

# Owners are always admins + verified (re-applied on every start)
for _o in OWNERS:
    if _o not in admins:
        admins.append(_o)
    if _o not in verified:
        verified.append(_o)


# ──────────────────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────────────────
def is_owner(event):
    return event.sender_id in OWNERS


def is_admin(event):
    # checked live on every message, so new admins work immediately
    return event.sender_id in OWNERS or event.sender_id in admins


def cmd(name):
    """Regex for '/name' or '/name@BotUsername', followed by space or end."""
    return rf"(?i)^/{name}(?:@\w+)?(?=\s|$)"


def cmd_on_off(name):
    return rf"(?i)^/{name}(?:@\w+)?\s+(on|off)\b"


def parse_amount(text):
    """'5000' -> 5000, '5k' -> 5000, '1.5k' -> 1500. Returns None if invalid."""
    s = str(text).strip().lower().replace(",", "")
    try:
        value = int(float(s[:-1]) * 1000) if s.endswith("k") else int(s)
    except ValueError:
        return None
    return value if value > 0 else None


async def resolve_target(event):
    """Get a user id from: a reply, a numeric id, or an @username."""
    if event.is_reply:
        try:
            replied = await event.get_reply_message()
        except Exception:
            replied = None
        if replied is not None and replied.sender_id and replied.sender_id > 0:
            return replied.sender_id

    parts = event.raw_text.split(maxsplit=1)
    if len(parts) < 2:
        return None
    arg = parts[1].split()[0]
    if arg.isdigit():
        return int(arg)
    try:
        peer = await client.get_entity(arg.lstrip("@"))
    except Exception:
        return None
    return peer.id if isinstance(peer, User) else None


async def need_target(event):
    uid = await resolve_target(event)
    if uid is None:
        name = event.raw_text.split()[0].split("@")[0]
        await event.reply(f"Reply to a user, or use `{name} <user_id | @username>`.")
    return uid


async def list_add(event, lst, field, already, done="✅ Done."):
    uid = await need_target(event)
    if uid is None:
        return None
    if uid in lst:
        await event.reply(already)
        return None
    lst.append(uid)
    config.update_one({"_id": 0}, {"$addToSet": {field: uid}}, upsert=True)
    await event.reply(done)
    return uid


async def list_remove(event, lst, field, missing, done="✅ Done.", protect=()):
    uid = await need_target(event)
    if uid is None:
        return None
    if uid in protect:
        await event.reply("❌ You can't do that to an owner.")
        return None
    if uid not in lst:
        await event.reply(missing)
        return None
    lst.remove(uid)
    config.update_one({"_id": 0}, {"$pull": {field: uid}})
    await event.reply(done)
    return uid


async def get_first_name(uid):
    try:
        target = user_db.find_one({"_id": uid})
        if target:
            full = await client(GetFullUser(InputUser(user_id=uid, access_hash=target["hash"])))
            name = full.users[0].first_name
            if name:
                return name.replace("[", "").replace("]", "")
    except Exception:
        pass
    return str(uid)


def bid_buttons(item_id):
    return [[Button.inline("Refresh", f"refresh|{item_id}"),
             Button.url("Bid", f"t.me/{bot_username}?start={item_id}")]]


def board_text(amount, uid=None, first_name=None):
    who = f"[{first_name}](tg://user?id={uid})" if uid else "No one right now!"
    return ("╭────────────────╮\n"
            f"    Highest Bid: {amount} Pd\n"
            f"    By: {who}\n"
            "╰────────────────╯")


async def edit_board(doc, text):
    try:
        await client.edit_message(auction_channel_id, doc["bmid"], text,
                                  buttons=bid_buttons(doc["token"]))
    except MessageNotModifiedError:
        pass
    except Exception as e:
        print(f"edit_board failed: {e}")


async def safe_send(chat, text, **kwargs):
    """Send a message; returns True/False. Handles flood-wait once."""
    for attempt in range(2):
        try:
            await client.send_message(chat, text, **kwargs)
            return True
        except FloodWaitError as e:
            await asyncio.sleep(e.seconds + 1)
        except Exception as e:
            print(f"safe_send to {chat} failed: {e}")
            return False
    return False


# ──────────────────────────────────────────────────────────────
#  OWNER COMMANDS
# ──────────────────────────────────────────────────────────────
@client.on(events.NewMessage(pattern=cmd("addadmin"), func=is_owner))
async def addadmin_cmd(event):
    uid = await list_add(event, admins, "admins", "Already admin.", "✅ Admin added.")
    if uid is not None and uid not in verified:
        verified.append(uid)
        config.update_one({"_id": 0}, {"$addToSet": {"verified": uid}}, upsert=True)


@client.on(events.NewMessage(pattern=cmd("remadmin"), func=is_owner))
async def remadmin_cmd(event):
    await list_remove(event, admins, "admins", "User is not admin.",
                      "✅ Admin removed.", protect=OWNERS)


@client.on(events.NewMessage(pattern=cmd("clear_db"), func=is_owner))
async def clear_db_cmd(event):
    parts = event.raw_text.split()
    count = auction_pokes.count_documents({})
    if len(parts) < 2 or parts[1].lower() != "confirm":
        return await event.reply(
            f"⚠️ This deletes ALL {count} active auction items without announcing results.\n"
            "Send `/clear_db confirm` to proceed.")
    auction_pokes.delete_many({})
    await event.reply(f"✅ Deleted {count} item(s).")


# ──────────────────────────────────────────────────────────────
#  ADMIN: switches (entry / bid / auction)
# ──────────────────────────────────────────────────────────────
async def toggle(event, key, label):
    want = event.pattern_match.group(1).lower() == "on"
    res = config.find_one({"_id": 0}) or {}
    if bool(res.get(key, False)) == want:
        return await event.reply(f"{label} is already {'enabled' if want else 'disabled'}.")
    config.update_one({"_id": 0}, {"$set": {key: want}}, upsert=True)
    await event.reply(f"{label} has been {'enabled' if want else 'disabled'}.")


@client.on(events.NewMessage(pattern=cmd_on_off("entry"), func=is_admin))
async def entry_cmd(event):
    await toggle(event, "entry", "Entry (submissions)")


@client.on(events.NewMessage(pattern=cmd_on_off("bid"), func=is_admin))
async def bid_cmd(event):
    await toggle(event, "bid", "Bidding")


@client.on(events.NewMessage(pattern=r"(?i)^/(entry|bid|auction)(?:@\w+)?\s*$", func=is_admin))
async def status_cmd(event):
    res = config.find_one({"_id": 0}) or {}
    flag = lambda k: "🟢 ON" if res.get(k, False) else "🔴 OFF"
    await event.reply(
        f"Entry (submissions): {flag('entry')}\n"
        f"Bidding: {flag('bid')}\n"
        f"Auction: {flag('auction')}\n"
        f"Items in auction: {auction_pokes.count_documents({})}")


# ──────────────────────────────────────────────────────────────
#  ADMIN: /auction on | off
# ──────────────────────────────────────────────────────────────
_settle_lock = asyncio.Lock()


@client.on(events.NewMessage(pattern=cmd_on_off("auction"), func=is_admin))
async def auction_cmd(event):
    action = event.pattern_match.group(1).lower()
    res = config.find_one({"_id": 0}) or {}
    running = bool(res.get("auction", False))

    if action == "on":
        if running:
            return await event.reply("Auction is already ongoing.")
        config.update_one({"_id": 0}, {"$set": {"auction": True}}, upsert=True)
        return await event.reply("✅ Auction started.")

    # action == "off"
    leftover = auction_pokes.count_documents({})
    if not running and leftover == 0:
        return await event.reply("Auction is already disabled.")
    if _settle_lock.locked():
        return await event.reply("⏳ Results are already being sent. Please wait.")

    config.update_one({"_id": 0}, {"$set": {"auction": False}}, upsert=True)
    async with _settle_lock:
        await settle_auction(event)


async def settle_auction(event):
    docs = list(auction_pokes.find())
    if not docs:
        return await event.reply("Auction closed. No items were in the auction.")

    await event.reply(f"Auction closed. Settling {len(docs)} item(s)...")

    # 1) archive a copy (history) before anything is removed
    archive = [{k: v for k, v in d.items() if k != "_id"} for d in docs]
    try:
        previous_data.insert_many(archive)
    except Exception as e:
        return await event.reply(
            f"⚠️ Could not archive items: {e}\nNothing was deleted. "
            "Fix the problem and send /auction off again.")

    sold = unsold = dm_failed = 0

    for doc in docs:
        name = doc.get("pokemon_name", "?")
        nature = doc.get("nature", "-")
        base = doc.get("base", "-")
        token = doc.get("token", "-")
        link = doc.get("link")
        seller = doc.get("user_id")
        bids = doc.get("bids") or []
        bidders = doc.get("bidders") or []

        # 2) remove the Bid/Refresh buttons from the channel post
        if doc.get("bmid"):
            try:
                await client.edit_message(auction_channel_id, doc["bmid"], buttons=Button.clear())
            except MessageNotModifiedError:
                pass
            except Exception as e:
                print(f"clear buttons failed for {token}: {e}")

        body = (f"🔹 **Pokémon:** {name}\n"
                f"🌿 **Nature:** {nature}\n"
                f"📊 **Base:** `{base}`\n"
                f"🆔 **Item ID:** `{token}`\n")
        if link and link != "None":
            body += f"🔗 [View Pokémon]({link})\n"

        await asyncio.sleep(1)

        if bids and bidders:
            sold += 1
            text = body + f"\n💰 **Buyer:** `{bidders[-1]}`\n💵 **Price:** `{bids[-1]}`"
            await safe_send(final_logs_id, f"👤 **Seller:** `{seller}`\n" + text)
            await asyncio.sleep(1)
            if not await safe_send(seller, text):
                dm_failed += 1
            if not await safe_send(bidders[-1], f"You won the bid for\n\n{text}"):
                dm_failed += 1
        else:
            unsold += 1
            text = body + "\n⚪ **No bids — unsold.**"
            await safe_send(final_logs_id, f"👤 **Seller:** `{seller}`\n" + text)
            await asyncio.sleep(1)
            if not await safe_send(seller, f"No bids were placed on this item, so it was not sold.\n\n{text}"):
                dm_failed += 1

    # 3) clear only the items we just settled (new items accepted meanwhile stay safe)
    auction_pokes.delete_many({"_id": {"$in": [d["_id"] for d in docs]}})

    await event.reply(
        "✅ Auction settled.\n"
        f"Sold: {sold}\nUnsold: {unsold}\n"
        f"DMs that couldn't be delivered: {dm_failed}\n"
        "Items cleared from the active list (history saved).")


# ──────────────────────────────────────────────────────────────
#  ADMIN: verify / ban
# ──────────────────────────────────────────────────────────────
@client.on(events.NewMessage(pattern=cmd("verify"), func=is_admin))
async def verify_cmd(event):
    await list_add(event, verified, "verified", "Already verified.", "✅ User verified.")


@client.on(events.NewMessage(pattern=cmd("unverify"), func=is_admin))
async def unverify_cmd(event):
    await list_remove(event, verified, "verified", "User is not verified.",
                      "❌ User has been unverified.", protect=OWNERS)


@client.on(events.NewMessage(pattern=cmd("bban"), func=is_admin))
async def bban_cmd(event):
    uid = await need_target(event)
    if uid is None:
        return
    if uid in OWNERS:
        return await event.reply("❌ You can't ban an owner.")
    if uid in bid_banned:
        return await event.reply("Already banned from bidding.")
    bid_banned.append(uid)
    config.update_one({"_id": 0}, {"$addToSet": {"bid_banned": uid}}, upsert=True)
    await event.reply("✅ User banned from bidding.")


@client.on(events.NewMessage(pattern=cmd("b_unban"), func=is_admin))
async def b_unban_cmd(event):
    await list_remove(event, bid_banned, "bid_banned", "User is not banned from bidding.",
                      "✅ User can bid again.")


@client.on(events.NewMessage(pattern=cmd("sban"), func=is_admin))
async def sban_cmd(event):
    uid = await need_target(event)
    if uid is None:
        return
    if uid in OWNERS:
        return await event.reply("❌ You can't ban an owner.")
    if uid in sub_banned:
        return await event.reply("Already banned from submission.")
    sub_banned.append(uid)
    config.update_one({"_id": 0}, {"$addToSet": {"sub_banned": uid}}, upsert=True)
    await event.reply("✅ User banned from submitting.")


@client.on(events.NewMessage(pattern=cmd("s_unban"), func=is_admin))
async def s_unban_cmd(event):
    await list_remove(event, sub_banned, "sub_banned", "User is not banned from submission.",
                      "✅ User can submit again.")


# ──────────────────────────────────────────────────────────────
#  ADMIN: item management
# ──────────────────────────────────────────────────────────────
@client.on(events.NewMessage(pattern=cmd("remitem"), func=is_admin))
async def remitem_cmd(event):
    parts = event.raw_text.split(maxsplit=2)
    if len(parts) < 2:
        return await event.reply("Usage: `/remitem <item_id> [reason]`")
    reason = parts[2] if len(parts) == 3 else None

    mm = auction_pokes.find_one_and_delete({"token": parts[1]})
    if mm is None:
        return await event.reply("Item not found.")

    for msg_id in (mm.get("bmid"), _msg_id_from_link(mm.get("link"))):
        if msg_id:
            try:
                await client.delete_messages(auction_channel_id, msg_id)
            except Exception:
                pass

    note = f"Admins removed {mm.get('nature', '')} {mm.get('pokemon_name', '')}"
    if reason:
        note += f" because: {reason}"
    await safe_send(mm.get("user_id"), note)
    await event.reply("✅ Item removed.")


def _msg_id_from_link(link):
    try:
        return int(str(link).split("/")[-1])
    except (ValueError, TypeError):
        return None


@client.on(events.NewMessage(pattern=cmd("resetbid"), func=is_admin))
async def resetbid_cmd(event):
    parts = event.raw_text.split()
    if len(parts) != 2:
        return await event.reply("Usage: `/resetbid <item_id>`")
    mm = auction_pokes.find_one_and_update({"token": parts[1]},
                                           {"$set": {"bids": [], "bidders": []}})
    if mm is None:
        return await event.reply("Item not found.")
    await edit_board(mm, board_text(mm.get("base", 0)))
    await event.reply("✅ Bids reset.")


@client.on(events.NewMessage(pattern=cmd("setbid"), func=is_admin))
async def setbid_cmd(event):
    parts = event.raw_text.split()
    if len(parts) != 4 or not parts[2].isdigit():
        return await event.reply("Usage: `/setbid <item_id> <user_id> <amount>`")
    item_id, uid, amount = parts[1], int(parts[2]), parse_amount(parts[3])

    if amount is None:
        return await event.reply("Incorrect bid amount.")
    if user_db.find_one({"_id": uid}) is None:
        return await event.reply("Dunno that user.. (they must have started the bot)")
    mm = auction_pokes.find_one_and_update({"token": item_id},
                                           {"$push": {"bids": amount, "bidders": uid}})
    if mm is None:
        return await event.reply("Auction item not found.")

    await edit_board(mm, board_text(amount, uid, await get_first_name(uid)))
    await event.reply("✅ Bid set.")


@client.on(events.NewMessage(pattern=cmd("rollback"), func=is_admin))
async def rollback_cmd(event):
    parts = event.raw_text.split()
    if len(parts) < 2 or len(parts) > 3:
        return await event.reply("Usage: `/rollback <item_id> [number]`")
    num = 1
    if len(parts) == 3:
        if not parts[2].isdigit() or int(parts[2]) <= 0:
            return await event.reply("Number of bids must be a positive integer.")
        num = int(parts[2])

    doc = auction_pokes.find_one({"token": parts[1]})
    if not doc:
        return await event.reply("Item ID not found.")
    bids = doc.get("bids", [])
    bidders = doc.get("bidders", [])
    if len(bids) < num or len(bidders) < num:
        return await event.reply(f"Cannot roll back {num} bids; only {len(bids)} exist.")

    new_bids, new_bidders = bids[:-num], bidders[:-num]
    auction_pokes.update_one({"token": parts[1]},
                             {"$set": {"bids": new_bids, "bidders": new_bidders}})

    if not new_bids:
        await edit_board(doc, board_text(doc.get("base", 0)))
        return await event.reply(f"Rolled back {num} bid(s). No bids left now.")

    uid = new_bidders[-1]
    first_name = await get_first_name(uid)
    await edit_board(doc, board_text(new_bids[-1], uid, first_name))
    await event.reply(f"Rolled back {num} bid(s).\n"
                      f"Current bid: {new_bids[-1]}\n"
                      f"Current bidder: [{first_name}](tg://user?id={uid})")


# ──────────────────────────────────────────────────────────────
#  ADMIN: messaging
# ──────────────────────────────────────────────────────────────
@client.on(events.NewMessage(pattern=cmd("msg"), func=is_admin))
async def msg_cmd(event):
    parts = event.raw_text.split(maxsplit=2)
    if len(parts) != 3 or not parts[1].isdigit():
        return await event.reply("Usage: `/msg <user_id> <text>`")
    if await safe_send(int(parts[1]), parts[2]):
        await event.reply("✅ Sent.")
    else:
        await event.reply("❌ Could not send (user may not have started the bot).")


@client.on(events.NewMessage(pattern=cmd("broadcast"), func=is_admin))
async def broadcast_cmd(event):
    replied = await event.get_reply_message() if event.is_reply else None
    parts = event.raw_text.split(maxsplit=1)
    if replied is None and len(parts) < 2:
        return await event.reply("Usage: `/broadcast <text>` or reply to a message with /broadcast")

    user_ids = [d["_id"] for d in user_db.find({}, {"_id": 1})]
    await event.reply(f"Starting broadcast to {len(user_ids)} users...")
    success = failed = 0

    for uid in user_ids:
        try:
            if replied is not None:
                await replied.forward_to(uid)
            else:
                await client.send_message(uid, parts[1])
            success += 1
        except FloodWaitError as e:
            await asyncio.sleep(e.seconds + 1)
            failed += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)

    await event.reply(f"Broadcast completed.\n✅ Sent: {success}\n❌ Failed: {failed}")


# ──────────────────────────────────────────────────────────────
#  EVERYONE: /profile
# ──────────────────────────────────────────────────────────────
@client.on(events.NewMessage(pattern=cmd("profile")))
async def profile_cmd(event):
    wants_other = event.is_reply or len(event.raw_text.split()) > 1
    if wants_other:
        uid = await resolve_target(event)
        if uid is None:
            return await event.reply("User not found. Reply to them or use their ID / @username.")
    else:
        uid = event.sender_id

    if uid in OWNERS:
        status = "[👑](https://envs.sh/0ul.jpg) Owner"
    elif uid in admins:
        status = "[👑](https://envs.sh/0ul.jpg) Admin"
    elif uid in verified:
        status = "[✅](https://envs.sh/0ul.jpg) Verified"
    else:
        status = "[❌](https://envs.sh/0ul.jpg) Not verified"

    def approved(tipe=None):
        q = {"user_id": uid}
        if tipe is not None:
            q["tipe"] = tipe
        # current auction + past auctions (history), so stats don't reset
        return auction_pokes.count_documents(q) + previous_data.count_documents(q)

    total_ok = approved()
    total_rej = rejected_pokes.count_documents({"user_id": uid})
    total_sub = total_ok + total_rej
    ratio = f"{(total_ok / total_sub) * 100:.1f}" if total_sub else "0"
    name = await get_first_name(uid)

    await event.reply(
        f"[{name}](tg://user?id={uid}) {status}\n\n"
        "〘 Total Approved 〙\n"
        f"   • ʟᴇɢᴇɴᴅᴀʀʏ : {approved(0)}\n"
        f"   • ɴᴏɴ-ʟᴇɢᴇɴᴅᴀʀʏ : {approved(1)}\n"
        f"   • sʜɪɴʏ : {approved(2)}\n"
        f"   • ᴛᴍs : {approved(3)}\n\n"
        f"📊 Total submitted: {total_sub}\n"
        f"☑️ Total approved: {total_ok}\n"
        f"⬜️ Approve Ratio: {ratio}%")


# ──────────────────────────────────────────────────────────────
#  ADMIN: command list
# ──────────────────────────────────────────────────────────────
@client.on(events.NewMessage(pattern=cmd("admincmds"), func=is_admin))
async def admincmds_cmd(event):
    text = (
        "**Admin commands**\n"
        "/entry on|off – open/close submissions\n"
        "/bid on|off – enable/disable bidding\n"
        "/auction on|off – start / END auction (off = announce winners + clear items)\n"
        "/entry, /bid, /auction – show status\n"
        "/verify, /unverify – reply | id | @user\n"
        "/bban, /b_unban – bid ban / unban\n"
        "/sban, /s_unban – submission ban / unban\n"
        "/remitem <id> [reason] – remove item\n"
        "/resetbid <id> – clear bids\n"
        "/setbid <id> <user_id> <amount>\n"
        "/rollback <id> [n] – undo last n bids\n"
        "/msg <user_id> <text>\n"
        "/broadcast <text> | reply\n")
    if is_owner(event):
        text += ("\n**Owner commands**\n"
                 "/addadmin, /remadmin – reply | id | @user\n"
                 "/clear_db confirm – delete ALL active items\n")
    await event.reply(text)
