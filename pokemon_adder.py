import os, random, string, uuid, time, html

import telethon
from telethon import events, Button
from bot import client, config, pending_pokes, auction_pokes, admin_grp_id, auction_channel_id, user_cache, \
    bot_username, verified, bid_banned, sub_banned, user_db, bid_logs_id, admins, rejected_pokes
from imagekitio import ImageKit
import requests
import traceback

from admin_funcs import (
    AUCTION_CHANNEL, TRADE_GROUP, BID_GROUP_ID, fmt, parse_amount, item_link, bid_url, ref_link, bid_box,
    post_buttons, check_can_bid, place_bid, announce_bid, md_link, ensure_user, get_points, referral_count,
    approved_items, approved_row, min_increase, get_auction_state,
)

imagekit =ImageKit(
    private_key='private_Vs/dcHjiR+ckec+n2izKPqzrTo0=',
    public_key='public_yeK8u/vouKfLmcyMbwJ72fxBWUc=',
    url_endpoint='https://ik.imagekit.io/HEXAAUCTION'
)

def upload_file_imagekit(file_path):
    try:
        with open(file_path, 'rb') as file:
            upload_response = imagekit.upload(
                file=file,
                file_name=str(uuid.uuid4()),
            )
        return (vars(upload_response))["url"]
    except Exception as e:
        return "None"
    finally:
        os.remove(file_path)


GAME_BOT_ID = 572621020   # the game bot whose messages must be forwarded when submitting


def esc(s):
    """Escape user-supplied text for HTML parse mode."""
    return html.escape(str(s if s is not None else ""))


def user_link(user):
    """HTML deep link to the user's profile, shown by name (never the raw id)."""
    name = html.escape(user.first_name or "User")
    return f'<a href="tg://user?id={user.id}">{name}</a>'


async def md_mention(user_id):
    """Markdown deep link by name for a user id."""
    try:
        u = await client.get_entity(user_id)
        name = (u.first_name or "User").replace("[", "(").replace("]", ")")
    except Exception:
        name = "User"
    return f"[{name}](tg://user?id={user_id})"


def _from_game_bot(resp):
    """True only if the message was forwarded from the game bot (never raises)."""
    fwd = getattr(resp, "fwd_from", None)
    return bool(fwd and getattr(fwd.from_id, "user_id", None) == GAME_BOT_ID)


# ---------------------------------------------------------------------------
# Channel / group config  (AUCTION_CHANNEL, TRADE_GROUP + bid group id live in admin_funcs.py)
# ---------------------------------------------------------------------------
def already_handled(event, name):
    """True if this exact message was already handled (stops double replies,
    even if the handler got registered twice)."""
    seen = getattr(client, "_seen_cmds", None)
    if seen is None:
        seen = client._seen_cmds = {}
    now = time.time()
    for k, t in list(seen.items()):
        if now - t > 120:
            seen.pop(k, None)
    key = (name, event.chat_id, event.id)
    if key in seen:
        return True
    seen[key] = now
    return False


@client.on(events.NewMessage(pattern=r"^/add(@\w+)?$"))
async def yescb(event):
    sender = await event.get_sender()
    kekz = user_db.find_one({"_id": sender.id})
    if kekz is None:
        user_db.insert_one({"_id": sender.id, "hash": sender.access_hash})
    res = config.find_one({"_id": 0}) or {}
    current_state = res.get("entry", False)
    if not current_state:
        return await event.reply("🔒 Submissions are currently closed.")
    if not event.is_private:
        return await event.reply("❌ Please use this command in a private chat with the bot.")
    if event.sender_id in sub_banned:
        return await event.reply("🚫 You are restricted from submitting items.")
    await event.reply(
        "**What would you like to sell?**\nChoose a category below.",
        buttons=[
            [Button.inline('🌟 Legendary', 'legendary')],
            [Button.inline('🐉 Non-Legendary', '0L')],
            [Button.inline('✨ Shiny', 'shiny')],
            [Button.inline('📚 TMs', 'tms')],
        ]
    )


WELCOME_IMG = None
try:
    _r = requests.get("https://ik.imagekit.io/cocogoat/1037179104-10000035_hAj39hAZg", timeout=15)
    # only keep it if it is really an image (not an error page)
    if _r.status_code == 200 and _r.headers.get("content-type", "").startswith("image/"):
        with open("temp.jpg", "wb") as handler:
            handler.write(_r.content)
        WELCOME_IMG = "temp.jpg"
    else:
        print("Welcome image download failed:", _r.status_code, _r.headers.get("content-type"))
except Exception as _e:
    print("Welcome image download error:", _e)

@client.on(events.NewMessage(pattern=r"^/start\b"))
async def start(event):
    sender = await event.get_sender()
    _parts = event.raw_text.split()
    param = _parts[1] if len(_parts) > 1 else None

    # ---- register user (+ referral point, only for brand-new users) ----
    if user_db.find_one({"_id": sender.id}) is None:
        new_user = {"_id": sender.id, "hash": sender.access_hash}
        referrer = None
        if param and param.startswith("ref_") and param[4:].isdigit():
            rid = int(param[4:])
            if rid != sender.id and user_db.find_one({"_id": rid}) is not None:
                referrer = rid
                new_user["referred_by"] = rid
        user_db.insert_one(new_user)
        if referrer:
            user_db.update_one({"_id": referrer}, {"$inc": {"auction_points": 1}})
            try:
                await client.send_message(
                    referrer,
                    f"🎉 **New Referral**\n\n"
                    f"{md_link(sender.id, sender.first_name)} joined using your link.\n"
                    f"⭐ +1 Auction Point")
            except Exception as e:
                print("referral notify failed:", e)

    if param is None or param.startswith("ref_"):
        welcome_text = (
            "👋 **Welcome to HeXa Auction Bot**\n\n"
            f"This bot runs the slow auctions held in @{AUCTION_CHANNEL}.\n\n"
            "**Before you start**\n"
            "Please join both:\n"
            f"• Auction Channel — @{AUCTION_CHANNEL}\n"
            f"• Trade Group — @{TRADE_GROUP}\n\n"
            "**Commands**\n"
            "• /add — submit an item for auction\n"
            "• /item — browse items in auction\n"
            "• /myitem — your listed items\n"
            "• /mybids — items you are leading\n"
            "• /profile — your stats and points\n"
            "• /referral — invite friends, earn points"
        )
        welcome_buttons = [[Button.url("Auction Channel", f"https://t.me/{AUCTION_CHANNEL}"),
                            Button.url("Trade Group", f"https://t.me/{TRADE_GROUP}")]]
        try:
            if WELCOME_IMG:
                await event.reply(welcome_text, file=WELCOME_IMG, buttons=welcome_buttons)
            else:
                await event.reply(welcome_text, buttons=welcome_buttons)
        except Exception as e:
            print("Welcome image send failed:", e)
            await event.reply(welcome_text, buttons=welcome_buttons)
    else:
        doc, err = check_can_bid(event.sender_id, param)
        if err:
            return await event.reply(err)
        last_bid = doc["bids"][-1] if doc["bids"] else doc["base"]
        async with client.conversation(event.sender_id) as conv:
            await conv.send_message(
                f"💰 **Place Your Bid**\n\n"
                f"🔹 {doc['pokemon_name']}\n"
                f"📈 Current bid: **{fmt(last_bid)}**\n"
                f"💡 Minimum next bid: **{fmt(last_bid + min_increase(last_bid))}**\n\n"
                f"Send your amount, for example `25000` or `25k`.")
            response = await conv.get_response(timeout=90000)
            amount = parse_amount(response.text)
            if not amount:
                return await client.send_message(
                    event.sender_id,
                    "❌ Invalid amount. Please send a number such as `25000` or `25k`.",
                    buttons=[[Button.url("Bid Again", bid_url(param))]])
            # re-checked against the live item, so a bid placed meanwhile by someone else is respected
            err, doc, last_bid, last_bidder = await place_bid(param, event.sender_id, amount)
            if err:
                return await conv.send_message(err)
            await event.reply(f"✅ **Bid Placed**\n\n🔹 {doc['pokemon_name']}\n💰 Your bid: **{fmt(amount)}**")
            await announce_bid(doc, sender, amount, last_bid, last_bidder)


@client.on(events.NewMessage(chats=BID_GROUP_ID, pattern=r"^/bid(?:@\w+)?\s+(\S+)\s*$"))
async def group_bid(event):
    """Reply /bid 1k  (or /bid 1000) to an item post in the group."""
    arg = event.pattern_match.group(1)
    if arg.lower() in ("on", "off"):      # admin toggle, handled in admin_funcs
        return
    if already_handled(event, "gbid") or not event.sender_id:
        return
    if not event.is_reply:
        return await event.reply("ℹ️ Reply to an item's post with `/bid 1k` to place a bid.")
    post = await event.get_reply_message()
    doc = await item_from_post(post)
    if doc is None:
        return await event.reply("❌ Please reply directly to an auction item's post.")
    amount = parse_amount(arg)
    if not amount:
        return await event.reply("❌ Invalid amount. Example: `/bid 1k` or `/bid 1000`.")
    err, doc, last_bid, last_bidder = await place_bid(doc["token"], event.sender_id, amount)
    if err:
        return await event.reply(err)
    sender = await event.get_sender()
    await event.reply(f"✅ **Bid Placed**\n💰 {fmt(amount)}")
    await announce_bid(doc, sender, amount, last_bid, last_bidder)


async def item_from_post(msg):
    """The group shows channel posts as auto-forwards -> map it back to the auction item."""
    fwd = getattr(msg, "fwd_from", None)
    if not fwd or not fwd.channel_post:
        return None
    try:   # make sure it is OUR auction channel (lenient if it can't be resolved)
        if fwd.from_id and telethon.utils.get_peer_id(fwd.from_id) != await client.get_peer_id(auction_channel_id):
            return None
    except Exception:
        pass
    return auction_pokes.find_one({"msg_id": fwd.channel_post})


@client.on(events.NewMessage(pattern=r"^/referral(@\w+)?$"))
async def referral(event):
    if already_handled(event, "referral"):
        return
    sender = await event.get_sender()
    ensure_user(sender)
    link = ref_link(sender.id)
    await event.reply(
        "🎁 **Your Referral Link**\n"
        f"`{link}`\n\n"
        "Earn **1 Auction Point** for every new user who joins the bot through your link.\n\n"
        f"👥 Referrals: **{referral_count(sender.id)}**\n"
        f"⭐ Auction Points: **{get_points(sender.id)}**",
        buttons=[[Button.url("📤 Share Link", f"https://t.me/share/url?url={link}")]],
        link_preview=False)


@client.on(events.CallbackQuery(func=lambda e: (
    e.data in [b"legendary", b"shiny", b"0L", b"tms", b"delete"] or (isinstance(e.data, bytes) and (e.data.startswith(b"submit|") or e.data.startswith(b"delete|"))))))
async def handle_specific_callbacks(event):

    data = event.data.decode("utf-8")

    if data == "legendary":
        await event.delete()
        await event.answer("Legendary selected", alert=False)
        await add_pokemon(event, 0)
    elif data == "shiny":
        await event.delete()
        await event.answer("Shiny selected", alert=False)
        await add_pokemon(event, 2)
    elif data == "0L":
        await event.delete()
        await event.answer("Non-Legendary selected", alert=False)
        await add_pokemon(event, 1)
    elif data == "tms":
        await event.delete()
        await event.answer("TMs selected", alert=False)
        await add_tms(event, 3)
    elif "submit" in data:
        damn = data.split("|")[1]
        if damn not in user_cache:
            await event.answer("This submission has expired. Please start again with /add.", alert=True)
            return
        await event.edit(buttons=Button.clear())
        if user_cache[damn]["tipe"] < 3:
            pending_pokes.insert_one({k: v for k, v in user_cache[damn].items() if k != 'image'})
        else:
            pending_pokes.insert_one(user_cache[damn])
        buttons = [[
            Button.inline("Accept", f"accept|{damn}"),
            Button.inline("Bad IVS", f"rej|ivs|{damn}")
        ],
            [
                Button.inline("Wrong info", f"rej|info|{damn}"),
                Button.inline("Bad Nature", f"rej|nature|{damn}")
            ], [
                Button.inline("Missing Moves", f"rej|moves|{damn}"),
                Button.inline("Over priced", f"rej|base|{damn}")
            ]]
        if user_cache[damn]["tipe"] <3:
            await client.send_file(admin_grp_id, file=user_cache[damn]["image"], caption=user_cache[damn]["text"],
                               parse_mode="html", buttons = buttons)
        else:
            await client.send_message(admin_grp_id, user_cache[damn]["text"],parse_mode="html", buttons=buttons)
        await event.answer("Submitted for admin review.", alert=False)
    elif data == "delete":
        await event.delete()


@client.on(events.CallbackQuery(func=lambda e: isinstance(e.data, bytes) and e.data.startswith(b"rej|")))
async def handle_rejection_reasons(event):
    if event.sender_id not in admins:
        await event.answer("You are not authorized to do this.", alert=True)
        return
    data_str = event.data.decode()  # convert bytes to string
    parts = data_str.split("|")
    if len(parts) < 3:
        await event.answer("Invalid request.", alert=True)
        return
    reason = parts[1]  # e.g., "ivs", "info", etc.
    ref_id = parts[2]  # e.g., the value of `damn`
    reason_map = {
        "ivs": "Bad IVs",
        "info": "Wrong info",
        "nature": "Bad Nature",
        "moves": "Missing Moves",
        "base": "Overpriced",
    }
    res = pending_pokes.find_one_and_delete({"token":ref_id})

    readable_reason = reason_map.get(reason, "Unknown reason")
    if res is None:
        await event.answer("This item has already been processed.", alert=True)
        return
    res["reason"] = readable_reason
    rejected_pokes.insert_one(res)
    text = (f"❌ **Submission Rejected**\n\n"
            f"🔹 {res['nature']} {res['pokemon_name']}\n"
            f"📝 **Reason:** {readable_reason}\n\n"
            f"You can fix the issue and submit again with /add.")
    try:
        await client.send_message(entity = res["user_id"], message=text)
    except Exception as e:
        print("reject dm failed:", e)
    await event.edit(buttons=Button.clear())
    await event.reply(f"❌ Rejected by {await md_mention(event.sender_id)}")
    user_cache.pop(ref_id, None)

@client.on(events.CallbackQuery(func=lambda e: isinstance(e.data, bytes) and e.data.startswith(b"accept|")))
async def handle_accept(event):
    if event.sender_id not in admins:
        await event.answer("You are not authorized to do this.", alert=True)
        return
    ref_id = event.data.decode().split("|", 1)[1]
    hmm = pending_pokes.find_one_and_delete({"token": ref_id})
    if not hmm or not isinstance(hmm, dict):
        await event.answer("This item is invalid or has already been processed.", alert=True)
        return
    auction_pokes.insert_one(hmm)
    kekz = await event.get_message()
    try:
        lulz = await client.get_entity(auction_channel_id)
    except:
        lulz = auction_channel_id

    post_text = f"{hmm['text']}\n\n{bid_box(hmm['base'])}"
    if hmm['tipe'] <3:
        media = telethon.utils.get_input_media(kekz.media)
        media.spoiler = True if hmm['tipe'] == 2 else False
        m = await client.send_file(lulz, caption=post_text, file=media, parse_mode="html",
                                   spoiler=True if hmm['tipe'] == 2 else False,
                                   buttons=post_buttons(ref_id))
    else:
        m = await client.send_message(lulz, post_text, parse_mode="html",
                                      buttons=post_buttons(ref_id))
    auction_pokes.find_one_and_update({"token": ref_id}, {"$set": {"link": f"https://t.me/{AUCTION_CHANNEL}/{m.id}", "msg_id": m.id, "bmid": m.id}})
    approved_items.insert_one(approved_row(hmm, event.sender_id))
    await event.edit(buttons=Button.clear())
    await event.reply(f"✅ Approved by {await md_mention(event.sender_id)}")
    user_cache.pop(ref_id, None)


def generate_alphanumeric_string(length=5):
    characters = string.ascii_letters + string.digits  # a-zA-Z0-9
    return ''.join(random.choices(characters, k=length))


CANCEL_HINT = "\n\nSend /cancel at any time to stop."


def _make_asker(conv):
    """Returns ask(prompt, validate, error): sends the prompt once, then keeps listening until the
    reply is valid. Returns None if the user sends /cancel."""
    async def ask(prompt, validate, error):
        await conv.send_message(prompt + CANCEL_HINT)
        while True:
            resp = await conv.get_response(timeout=900000)
            if (resp.text or "").strip().lower().startswith("/cancel"):
                await conv.send_message("🚫 Submission cancelled.")
                return None
            if validate(resp):
                return resp
            await conv.send_message(error)
    return ask


ERR_FORWARD = "❌ That is not the expected message. Please forward it directly from the game bot, or send /cancel to stop."
ERR_PRICE = "❌ Invalid price. Send a number such as `5000` or `5k`."


async def add_tms(event, tipe):
    entry = (config.find_one({"_id": 0}) or {}).get("entry", False)
    if not event.is_private:
        return
    if not entry:
        return await event.respond("🔒 Submissions are currently closed.")

    user_id = event.sender_id
    user_data = {"user_id": user_id, "bids": [], "bidders": []}

    async with client.conversation(user_id) as conv:
        try:
            ask = _make_asker(conv)

            def validate_tm(resp):
                return (_from_game_bot(resp) and
                        "Power" in resp.raw_text and "Accuracy" in resp.raw_text and "💿" in resp.raw_text)
            nature_resp = await ask("**Step 1/2 · TM**\nForward the TM from the game bot.", validate_tm, ERR_FORWARD)
            if nature_resp is None:
                return
            user_data["info"] = nature_resp.raw_text.split("\n")[3]
            user_data["nature"] = nature_resp.raw_text.split("\n")[2]
            user_data["pokemon_name"] = nature_resp.raw_text.split("\n")[0]

            base_resp = await ask("**Step 2/2 · Base Price**\nSend the base price, for example `5000` or `5k`.",
                                  lambda r: bool(parse_amount(r.text)), ERR_PRICE)
            if base_resp is None:
                return
            user_data["base"] = parse_amount(base_resp.text)
            token = generate_alphanumeric_string()
            username_line = f"<b>Username:</b> @{esc(event.sender.username)}\n" if event.sender.username else ""
            summary = (
                f"<blockquote><b>TMs</b></blockquote>\n"
                f"<blockquote>{esc(user_data['pokemon_name'])}\n"
                f"{esc(user_data['nature'])}\n"
                f"{esc(user_data['info'])}</blockquote>\n"
                f"<blockquote><b>Seller:</b> {user_link(event.sender)}\n"
                f"{username_line}"
                f"<b>Base:</b> {fmt(user_data['base'])} Pd</blockquote>\n"
                f"<b>Item ID:</b> <code>{token}</code>"
            )
            user_data["text"] = summary
            user_data["tipe"] = 3
            user_data["token"] = token
            user_cache[token] = user_data
            await conv.send_message(summary, parse_mode="html",
                                 buttons=[[Button.inline('✅ Submit', f'submit|{token}')],
                                          [Button.inline('🗑 Delete', 'delete')]])
        except Exception:
            traceback.print_exc()
            await conv.send_message("⚠️ Something went wrong while processing your submission. Please try again with /add.")


async def add_pokemon(event, tipe):
    entry = (config.find_one({"_id": 0}) or {}).get("entry", False)
    if not event.is_private:
        return
    if not entry:
        return await event.respond("🔒 Submissions are currently closed.")

    user_id = event.sender_id
    user_data = {"user_id": user_id, "bids":[], "bidders":[]}

    async with client.conversation(user_id) as conv:
        try:
            ask = _make_asker(conv)

            name_resp = await ask("**Step 1/6 · Pokémon Name**\nSend the name of your Pokémon.",
                                  lambda r: len((r.text or "").strip()) >= 2,
                                  "❌ Please send a valid name (at least 2 characters).")
            if name_resp is None:
                return
            user_data["pokemon_name"] = name_resp.text.strip()

            def validate_nature(resp):
                return bool(resp.media and _from_game_bot(resp) and "| Nature:" in resp.raw_text)
            nature_resp = await ask("**Step 2/6 · Nature**\nForward the Pokémon's nature screen from the game bot.",
                                    validate_nature, ERR_FORWARD)
            if nature_resp is None:
                return
            user_data["nature"] = nature_resp.raw_text.split("Exp.")[0].split("\n")[0].split("Nature: ")[1]
            user_data["level"] = nature_resp.raw_text.split("Exp.")[0].split("Lv. ")[1].split("|")[0]

            def validate_evs(resp):
                return bool(resp.media and "Points" in resp.raw_text and "IV" in resp.raw_text and _from_game_bot(resp))
            evs_resp = await ask("**Step 3/6 · EVs & IVs**\nForward the EVs & IVs screen from the game bot.",
                                 validate_evs, ERR_FORWARD)
            if evs_resp is None:
                return
            user_data["evs"] = evs_resp.raw_text
            user_data["image"] = evs_resp.media

            def validate_moveset(resp):
                return bool(resp.media and "Power" in resp.raw_text and "Accuracy" in resp.raw_text and _from_game_bot(resp))
            moveset_resp = await ask("**Step 4/6 · Moveset**\nForward the moveset screen from the game bot.",
                                     validate_moveset, ERR_FORWARD)
            if moveset_resp is None:
                return
            user_data["moveset"] = moveset_resp.raw_text

            boosted_resp = await ask("**Step 5/6 · Boosted Stats**\nSend all boosted stats in one message, or send `None`.",
                                     lambda r: len((r.text or "").strip()) > 0,
                                     "❌ Please send the boosted stats, or `None`.")
            if boosted_resp is None:
                return
            user_data["boosted"] = boosted_resp.text.strip()

            base_resp = await ask("**Step 6/6 · Base Price**\nSend the base price, for example `5000` or `5k`.",
                                  lambda r: bool(parse_amount(r.text)), ERR_PRICE)
            if base_resp is None:
                return
            user_data["base"] = parse_amount(base_resp.text)

            poke_tipe = {0:"LEGENDARY", 2:"SHINY", 1:"NON-LEGENDARY"}
            token = generate_alphanumeric_string()
            user_data["token"] = token

            username_line = f"<b>Username:</b> @{esc(event.sender.username)}\n" if event.sender.username else ""
            summary = (
                f"<blockquote><b>{poke_tipe[tipe]}</b></blockquote>\n"
                f"<blockquote><b>Pokémon:</b> {esc(user_data['pokemon_name'])}\n"
                f"<b>Level:</b> {esc(user_data['level'])}\n"
                f"<b>Nature:</b> {esc(user_data['nature'])}</blockquote>\n"
                f"<code>{esc(user_data['evs'])}</code>\n\n"
                f"{esc(user_data['moveset'])}\n"
                f"<blockquote><b>Seller:</b> {user_link(event.sender)}\n"
                f"{username_line}"
                f"<b>Boosted:</b> {esc(user_data['boosted'])}\n"
                f"<b>Base:</b> {fmt(user_data['base'])} Pd</blockquote>\n"
                f"<b>Item ID:</b> <code>{token}</code>"
            )
            user_data["text"] = summary
            user_data["tipe"] = tipe
            user_cache[token] = user_data
            await conv.send_file(file=user_data['image'], caption=summary, parse_mode="html",
                                 buttons=[[Button.inline('✅ Submit', f'submit|{token}')],
                                          [Button.inline('🗑 Delete', 'delete')]])
        except Exception:
            traceback.print_exc()
            await conv.send_message("⚠️ Something went wrong while processing your submission. Please try again with /add.")

MAX_LEN = 3900
TYPE_ORDER = [
    (0, "🌟 Legendary"),
    (1, "🐉 Non-Legendary"),
    (2, "✨ Shiny"),
    (3, "📚 TMs"),
]


def _clean(s):
    return str(s).replace("[", "").replace("]", "")


def _current_bid(poke):
    bids = poke.get("bids") or []
    return bids[-1] if bids else poke.get("base", 0)


def _item_line(poke):
    return (f"🔹 [{_clean(poke['pokemon_name'])} - {_clean(poke['nature'])}]({item_link(poke)})"
            f" · `{fmt(_current_bid(poke))}`\n")


def _ended_note():
    """Shown above lists while the auction is off (the data is kept until the next auction starts)."""
    return "" if get_auction_state() else "🔒 The auction has ended. Showing final results.\n\n"


def _build_list(header, items):
    """Build the list text and keep it under Telegram's message limit."""
    text = header
    shown = 0
    for poke in items:
        try:
            line = _item_line(poke)
        except Exception as e:
            print(e)
            continue
        if len(text) + len(line) > MAX_LEN:
            text += f"\n…and {len(items) - shown} more"
            break
        text += line
        shown += 1
    return text


def _type_buttons():
    return [
        [Button.inline("🌟 Legendary", data="klegend")],
        [Button.inline("🐉 Non-Legendary", data="knonlegend")],
        [Button.inline("✨ Shiny", data="kshiny")],
        [Button.inline("📚 TMs", data="ktms")],
    ]


# /myitem, /myitems, /myid and /myids all do the same thing
@client.on(events.NewMessage(pattern=r"^/(?:myitems?|my\s?ids?)(?:@\w+)?\s*$"))
async def myitems(event):
    if already_handled(event, "myitem"):
        return
    items = list(auction_pokes.find({"user_id": event.sender_id}))
    if not items:
        return await event.reply("📭 You have no items in the auction.")
    header = f"📦 **Your Items** · {len(items)}\n\n{_ended_note()}"
    await event.reply(_build_list(header, items), link_preview=False)


# /mybid and /mybids do the same thing
@client.on(events.NewMessage(pattern=r"^/mybids?(?:@\w+)?\s*$"))
async def mybids(event):
    if already_handled(event, "mybids"):
        return
    mine = []
    for poke in auction_pokes.find({}):
        try:
            if poke["bidders"][-1] == event.sender_id:
                mine.append(poke)
        except Exception:
            pass
    if not mine:
        return await event.reply("📭 You have no active bids.")
    header = f"💰 **Your Bids** · {len(mine)}\nItems where you hold the highest bid.\n\n{_ended_note()}"
    await event.reply(_build_list(header, mine), link_preview=False)


@client.on(events.NewMessage(pattern=r"^/items?(@\w+)?$"))
async def show_items(event):
    if already_handled(event, "item"):
        return
    for tipe, title in TYPE_ORDER:
        items = list(auction_pokes.find({"tipe": tipe}))
        if items:
            return await send_items(event, items, title)
    await event.reply("📭 No items are currently listed.")


# Callback handlers for each type
@client.on(events.CallbackQuery(data=b"klegend"))
async def show_legend(event):
    await send_items(event, list(auction_pokes.find({"tipe": 0})), "🌟 Legendary")

@client.on(events.CallbackQuery(data=b"knonlegend"))
async def show_nonlegend(event):
    await send_items(event, list(auction_pokes.find({"tipe": 1})), "🐉 Non-Legendary")

@client.on(events.CallbackQuery(data=b"kshiny"))
async def show_shiny(event):
    await send_items(event, list(auction_pokes.find({"tipe": 2})), "✨ Shiny")

@client.on(events.CallbackQuery(data=b"ktms"))
async def show_tms(event):
    await send_items(event, list(auction_pokes.find({"tipe": 3})), "📚 TMs")


# Shared response sender
# - from /item (a normal message)  -> reply ONCE
# - from a category button         -> edit the same message
async def send_items(event, items, title):
    is_callback = isinstance(event, events.CallbackQuery.Event)

    if items:
        text = _build_list(f"**{title}** · {len(items)}\n\n{_ended_note()}", items)
    else:
        text = f"📭 No items listed in {title}."

    if not is_callback:
        return await event.reply(text, buttons=_type_buttons(), link_preview=False)

    try:
        await event.edit(text, buttons=_type_buttons(), link_preview=False)
    except telethon.errors.rpcerrorlist.MessageNotModifiedError:
        pass
    except Exception as e:
        print("send_items edit failed:", e)
        await event.respond(text, buttons=_type_buttons(), link_preview=False)
    try:
        await event.answer()
    except Exception:
        pass
