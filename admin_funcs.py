import asyncio
import html as html_lib

from telethon import events, Button
from telethon.tl.functions.users import GetFullUserRequest as GetFullUser
from telethon.tl.types import InputUser

from collections import Counter

from bot import client, config, admins, verified, bid_banned, sub_banned, auction_pokes, auction_channel_id, \
    bot_username, user_db, previous_data, final_logs_id, rejected_pokes, pending_pokes, verify_admins, OWNERS
from pokemon_adder import item_link, update_bid_post, close_bid_post


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


def verify_admin_only(event):
    """Only 'verify admins' (added with /addadminv) and owners can /verify and /unverify."""
    return event.sender_id in verify_admins or event.sender_id in OWNERS


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


def clean_md(s):
    return str(s).replace("[", "").replace("]", "")


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


@client.on(events.NewMessage(pattern=r"^/addadminv\b", func=owner_only))
async def addadminv(event):
    await add_user(event, verify_admins, "verify_admins", "Already a verify admin.", "✅ Verify admin added.")


@client.on(events.NewMessage(pattern=r"^/remadminv\b", func=owner_only))
async def remadminv(event):
    await remove_user(event, verify_admins, "verify_admins", "User is not a verify admin.",
                      "✅ Verify admin removed.")


# /auction on|off is OWNER ONLY (normal admins can use every other admin command)
@client.on(events.NewMessage(pattern=r"^/auction\s+(on|off)\b", func=owner_only))
async def auction(event):
    await run_auction(event)


# ---------------------------------------------------------------------------
# Admin commands
# ---------------------------------------------------------------------------
@client.on(events.NewMessage(pattern=r"^/entry\s+(on|off)\b", func=admin_only))
async def entry(event):
    await toggle_setting(event, "entry", "Entry")


@client.on(events.NewMessage(pattern=r"^/bid\s+(on|off)\b", func=admin_only))
async def bid(event):
    await toggle_setting(event, "bid", "Bid")


async def run_auction(event):
    action = event.pattern_match.group(1).lower()
    current_state = get_auction_state()

    if action == "on":
        if current_state:
            return await event.reply("Auction is already ongoing.")
        # A NEW auction starts -> only now the previous auction's items are removed
        auction_pokes.delete_many({"ended": True})
        # Auction on -> submission (entry) and bidding open automatically
        config.update_one({"_id": 0},
                          {"$set": {"auction": True, "entry": True, "bid": True},
                           "$inc": {"auctions_held": 1}},
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

    # Items are NOT deleted now (/item /myitem /mybids keep working);
    # they are only marked as ended and cleared when the next auction starts.
    docs = list(auction_pokes.find({"ended": {"$ne": True}}))
    ids = [d["_id"] for d in docs]
    if ids:
        auction_pokes.update_many({"_id": {"$in": ids}}, {"$set": {"ended": True}})
        previous_data.insert_many([{k: v for k, v in d.items() if k != "_id"} for d in docs])
    await event.reply("Spam started")

    for doc in docs:
        await close_bid_post(doc)          # remove the Bid button
        if not doc.get("bidders") or not doc.get("bids"):
            continue                       # unsold
        try:
            seller = await get_mention(doc['user_id'])
            buyer = await get_mention(doc['bidders'][-1])
            pname = clean_md(doc['pokemon_name'])
            text = (
                f"🔹 **Pokémon:** [{pname}]({item_link(doc)})\n"
                f"🌿 **Nature:** {doc['nature']}\n"
                f"📊 **Base:** `{doc['base']}`\n"
                f"🆔 **Item ID:** `{doc['token']}`\n\n"
                f"💰 **Buyer:** {buyer}\n"
                f"💵 **Price:** `{doc['bids'][-1]}`"
            )
        except Exception:
            print("skipping")
            continue
        await asyncio.sleep(1)
        try:
            await client.send_message(
                final_logs_id,
                f"👤 **Seller:** {seller}\n🆔 **Seller ID:** `{doc['user_id']}`\n" + text +
                f"\n🆔 **Buyer ID:** `{doc['bidders'][-1]}`",
                link_preview=False)
        except Exception:
            pass
        await asyncio.sleep(1)
        try:
            await client.send_message(doc['user_id'], text, link_preview=False)
        except Exception:
            pass
        try:
            await client.send_message(doc['bidders'][-1], f"You won the bid for \n\n{text}",
                                      link_preview=False)
        except Exception:
            pass

    await event.reply("Spam done")


@client.on(events.NewMessage(pattern=r"^/verify\b", func=verify_admin_only))
async def verify(event):
    await add_user(event, verified, "verified", "Already verified.")


@client.on(events.NewMessage(pattern=r"^/unverify\b", func=verify_admin_only))
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
    ids = [x for x in (mm.get("bmid"), mm.get("msg_id")) if x]
    if not mm.get("msg_id"):
        try:
            ids.append(int(mm["link"].split("/")[-1]))
        except Exception:
            pass
    try:
        if ids:
            await client.delete_messages(auction_channel_id, ids)
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
    try:
        await update_bid_post(mm, mm['base'], None)
    except Exception as e:
        return await event.reply(f"❌ Failed to update the post: {e}")
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
    try:
        await update_bid_post(mm, amount, user_id, await get_first_name(user_id))
    except Exception as e:
        return await event.reply(f"❌ Failed to update the post: {e}")
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

    try:
        if len(new_bids) == 0:
            await update_bid_post(doc, doc['base'], None)
        else:
            await update_bid_post(doc, validate_base(new_bids[-1]), new_bidders[-1],
                                  await get_first_name(new_bidders[-1]))
    except Exception as e:
        return await event.reply(f"❌ Failed to update the post: {e}")

    if len(new_bids) == 0:
        await event.reply(f"Rolled back {num} bids. No bids left now.")
    else:
        mention = await get_mention(new_bidders[-1])
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
# /botstats  (admins)
# ---------------------------------------------------------------------------
TYPE_NAMES = {0: "Legendary", 1: "Non-Legendary", 2: "Shiny", 3: "TMs"}


def _to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _fmt(n):
    return f"{int(n):,}"


async def _top_lines(counter, unit):
    if not counter:
        return "Nothing yet"
    out = []
    for i, (uid, n) in enumerate(counter.most_common(5), 1):
        name = html_lib.escape(str(await get_first_name(uid)))
        out.append(f'{i}. <a href="tg://user?id={int(uid)}">{name}</a> (<code>{uid}</code>) — {n} {unit}')
    return "\n".join(out)


@client.on(events.NewMessage(pattern=r"^/botstats(@\w+)?\s*$", func=admin_only))
async def botstats(event):
    # Ended items live in previous_data (auction_pokes keeps a copy flagged "ended"
    # until the next auction starts, so only NON-ended ones are counted from there).
    finished = list(previous_data.find({}))
    live = list(auction_pokes.find({"ended": {"$ne": True}}))
    everything = finished + live

    sold = [d for d in finished if d.get("bids") and d.get("bidders")]
    unsold = len(finished) - len(sold)
    revenue = sum(_to_int(d["bids"][-1]) for d in sold)
    sold_by_type = Counter(d.get("tipe") for d in sold)
    listed_by_type = Counter(d.get("tipe") for d in everything)

    adders = Counter(d["user_id"] for d in everything if d.get("user_id"))
    bidders = Counter()          # total bids placed per user
    for d in everything:
        for b in d.get("bidders") or []:
            bidders[b] += 1
    total_bids = sum(bidders.values())

    sellers = len({d["user_id"] for d in sold if d.get("user_id")})
    buyers = len({d["bidders"][-1] for d in sold})

    best = max(sold, key=lambda d: _to_int(d["bids"][-1]), default=None)
    cfg = config.find_one({"_id": 0}) or {}

    type_rows = []
    for t, label in TYPE_NAMES.items():
        if listed_by_type.get(t) or sold_by_type.get(t):
            type_rows.append(f"{label}: {sold_by_type.get(t, 0)} sold / {listed_by_type.get(t, 0)} listed")
    type_text = "\n".join(type_rows) if type_rows else "No data yet"

    best_text = "—"
    if best:
        best_text = (f"{html_lib.escape(str(best['pokemon_name']))} — {_fmt(_to_int(best['bids'][-1]))} "
                     f"(<code>{best.get('token')}</code>)")

    text = (
        "📊 <b>Bot Stats</b>\n\n"
        f"🛒 <b>Pokes sold / bought:</b> {len(sold)}\n"
        f"💰 <b>Total sales value:</b> {_fmt(revenue)}\n"
        f"🏆 <b>Highest sale:</b> {best_text}\n\n"
        "<b>📦 Auction data</b>\n"
        "<blockquote>"
        f"Auctions held: {cfg.get('auctions_held', 0)}\n"
        f"Status: {'ON' if cfg.get('auction') else 'OFF'} | Entry: {'ON' if cfg.get('entry') else 'OFF'} | "
        f"Bid: {'ON' if cfg.get('bid') else 'OFF'}\n"
        f"Items listed (all time): {len(everything)}\n"
        f"Live now: {len(live)}\n"
        f"Finished: {len(finished)} (sold {len(sold)}, unsold {unsold})\n"
        f"Pending approval: {pending_pokes.count_documents({})}\n"
        f"Rejected: {rejected_pokes.count_documents({})}\n"
        f"Total bids placed: {total_bids}\n"
        f"Unique sellers / buyers: {sellers} / {buyers}\n"
        f"Registered users: {user_db.count_documents({})}\n"
        f"Verified: {len(verified)} | Admins: {len(admins)}\n"
        f"Bid banned: {len(bid_banned)} | Sub banned: {len(sub_banned)}"
        "</blockquote>\n\n"
        f"<b>🗂 By type</b>\n<blockquote>{type_text}</blockquote>\n\n"
        f"<b>🔥 Top 5 bidders (most bids)</b>\n{await _top_lines(bidders, 'bids')}\n\n"
        f"<b>➕ Top 5 adders (most items added)</b>\n{await _top_lines(adders, 'items')}"
    )
    await event.reply(text, parse_mode="html", link_preview=False)


# ---------------------------------------------------------------------------
# Public command
# ---------------------------------------------------------------------------
PROFILE_ROWS = (("Legendary", 0), ("Non-Legendary", 1), ("Shiny", 2), ("TMs", 3))


def _profile_section(title, counts):
    """Bold title + total, then a quote with only the types that are not 0."""
    total = sum(counts)
    rows = [f"{label} — {counts[idx]}" for label, idx in PROFILE_ROWS if counts[idx]]
    body = "\n".join(rows) if rows else "Nothing yet"
    return f"<b>{title}</b> · {total}\n<blockquote>{body}</blockquote>"


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
    name = html_lib.escape(str(await get_first_name(uid)))
    username = f'<a href="tg://user?id={int(uid)}">{name}</a>'

    if uid in OWNERS:
        post = "👑 Owner"
    elif uid in verify_admins:
        post = "🛡 Verify Admin"
    elif uid in admins:
        post = "👑 Admin"
    elif uid in verified:
        post = "✅ Verified"
    else:
        post = "❌ Not verified"

    # Currently listed in the live auction
    listed = [0, 0, 0, 0]
    for d in auction_pokes.find({"user_id": uid, "ended": {"$ne": True}}, {"tipe": 1}):
        t = d.get("tipe")
        if t in (0, 1, 2, 3):
            listed[t] += 1

    # Bought = won in past auctions (the user was the last/highest bidder)
    bought = [0, 0, 0, 0]
    for d in previous_data.find({"bidders": uid}, {"tipe": 1, "bidders": 1}):
        bidders = d.get("bidders") or []
        t = d.get("tipe")
        if bidders and bidders[-1] == uid and t in (0, 1, 2, 3):
            bought[t] += 1

    text = (f"{username} {post}\n\n"
            f"{_profile_section('Bought', bought)}\n\n"
            f"{_profile_section('Listed', listed)}")
    await event.reply(text, parse_mode="html", link_preview=False)
    
