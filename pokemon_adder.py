import os, random, string, uuid

import telethon
from telethon import events, Button
from bot import client, config, pending_pokes, auction_pokes, admin_grp_id, auction_channel_id, user_cache, \
    bot_username, verified, bid_banned, sub_banned, user_db, bid_logs_id, admins, rejected_pokes
from imagekitio import ImageKit
import requests
import traceback

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


def user_link(user):
    """HTML deep link to the user's profile, shown by name (never the raw id)."""
    import html
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


@client.on(events.NewMessage(pattern=r"^/add(@\w+)?$"))
async def yescb(event):
    sender = await event.get_sender()
    kekz = user_db.find_one({"_id": sender.id})
    if kekz is None:
        pass
        user_db.insert_one({"_id": sender.id, "hash": sender.access_hash})
    res = config.find_one({"_id": 0})
    current_state = res.get("entry", False)
    if not current_state:
        return await event.reply("Submission is turned off")
    if not event.is_private:
        return await event.reply("Use in dm")
    if event.sender_id in sub_banned:
        return await event.reply("You are banned from submission...")
    await event.reply("So what would you like to sell?"
        ,
        buttons=[
        [
            Button.inline('LEGENDARY', 'legendary')
        ],
        [
            Button.inline('0L/NON LEGENDARY', '0L')
        ],
        [
            Button.inline('SHINY', 'shiny')
        ],
        [
            Button.inline('TMS', 'tms')
        ]
     ]
    )


def validate_base(base):
    base = base.text
    try:
        m = int(base)
        return m
    except ValueError:
        try:
            if base.lower().endswith("k"):
                return int(float(base[:-1]) * 1000)
        except:
            return False
    return False

notacc = """Bid Not Accepted !
⁉️ | Reasons:
❖ Don't send an amount lower than the highest bid
❖ Don't send the same amount as the highest bid
❖ Follow Minimum Increase Bid Rule:
+1k if highest is under 50k
+2k if highest is 50k-100k
+5k if highest is over 100k"""
img_data = requests.get("https://ik.imagekit.io/cocogoat/1037179104-10000035_hAj39hAZg").content
with open("temp.jpg", "wb") as handler:
    handler.write(img_data)

@client.on(events.NewMessage(pattern=r"^/start\b"))
async def start(event):
    sender = await event.get_sender()
    kekz = user_db.find_one({"_id": sender.id})
    if kekz is None:
        pass
        user_db.insert_one({"_id": sender.id, "hash": sender.access_hash})
    _parts = event.raw_text.split()
    if len(_parts) < 2:
        await event.reply("""Welcome to HeXa Auction Bot
This bot is used to manage auctions in @HexaAuction ( Based on Slow Auctions )

⚠️ Must join Both Channel & Groups
Auction Group
               ╰┈➤ @HexaAuction

Auction Trade Group
               ╰➤ @HexaAuctionGc

Use /add to add your items for auction.""", file="temp.jpg", buttons=[[Button.url("Auction Channel", "https://t.me/Shadow_Auction"), Button.url("Trade Grp", "https://t.me/ShadowHeXaGroup")]])
    else:
        res = config.find_one({"_id": 0})
        current_state = res.get("bid", False)
        if not current_state:
            return await event.reply("Bid disbaled right now.")
        if event.sender_id not in verified:
            return await event.reply("Not verified. Please get yourself verifed by admins")
        if event.sender_id in bid_banned:
            return await event.reply("You are banned from bidding")
        hmm = auction_pokes.find_one({"token": _parts[1]})
        if hmm is None:
            return await event.reply("This item is no longer available.")
        if event.sender_id == hmm["user_id"]:
            return await event.reply("Seller isnt allowed to bid")
        last_bid =hmm["bids"]
        last_bidder = hmm["bidders"]
        if last_bid == []:
            last_bid = hmm["base"]
            last_bidder = None
        else:
            last_bid = last_bid[-1]
            last_bidder = last_bidder[-1]
        async with client.conversation(event.sender_id) as conv:
            await conv.send_message(f'Enter bid for {hmm["pokemon_name"]}.\nLast bid: {last_bid}')
            response = await conv.get_response(timeout = 90000)
            if validate_base(response):
                if last_bid < validate_base(response):
                    if (last_bid <=  50000 and validate_base(response)-last_bid >= 1000) or (last_bid <=  100000 and validate_base(response)-last_bid >= 2000) or (last_bid >  100000 and validate_base(response)-last_bid >= 5000):
                        pass
                    else:
                        await conv.send_message(notacc)
                        return
                else:
                    await conv.send_message(notacc)
                    return
                auction_pokes.find_one_and_update({"token": _parts[1]}, {"$push": {"bids": validate_base(response), "bidders": event.sender_id}})
                text = f"""╭────────────────╮
    Highest Bid: {validate_base(response)} Pd
    By: [{event.sender.first_name}](tg://user?id={event.sender.id})
╰────────────────╯"""
                await client.edit_message(auction_channel_id, hmm["bmid"], text=text,
                                          buttons=[[Button.inline("Refresh", f"refresh|{_parts[1]}"),
                                                    Button.url("Bid", f"t.me/{bot_username}?start={_parts[1]}")]])
                await event.reply("Bid placed successfully.")
                if hmm["tipe"] < 3:
                    lala = (
                    f"🎉 [{event.sender.first_name}](tg://user?id={event.sender.id}) just bid\n\n"
                    f"🔹 **Pokemon:** {hmm['pokemon_name']} [🔗🔗🔗]({hmm['link']})\n"
                    f"🌿 **Nature:** {hmm['nature']}\n\n"
                    f"📈 **Current Bid:** {validate_base(response)}\n"
                    f"💸 **Last Bid:** {last_bid}\n"
                    f"📊 **Outbid By:** {validate_base(response) - last_bid}\n\n"
                   )
                else:
                    lala = (
                        f"🎉 [{event.sender.first_name}](tg://user?id={event.sender.id}) just bid\n\n"
                        f"🔹 {hmm['pokemon_name']} [🔗🔗🔗]({hmm['link']})\n"
                        f"🌿 {hmm['nature']}\n\n"
                        f"📈 **Current Bid:** {validate_base(response)}\n"
                        f"💸 **Last Bid:** {last_bid}\n"
                        f"📊 **Outbid By:** {validate_base(response) - last_bid}\n\n"
                    )

                await client.send_message(bid_logs_id, lala)

                if last_bidder:
                    if hmm["tipe"] < 3:
                        await client.send_message(
                        last_bidder,
                        f"🎉 [{event.sender.first_name}](tg://user?id={event.sender.id}) just outbid you!\n\n"
                        f"🔹 **Pokemon:** {hmm['pokemon_name']} [🔗🔗🔗]({hmm['link']})\n "
                        f"🌿 **Nature:** {hmm['nature']}\n\n"
                        f"💸 **Your Bid:** {last_bid}\n"
                        f"📈 **Current Bid:** {validate_base(response)}\n"
                        f"📊 **Outbid By:** {validate_base(response) - last_bid}\n\n"
                        f"🔥 Hurry and place a higher bid to stay in the game!",
                        buttons=[
                            [Button.url("🛒 Bid Now", f"t.me/{bot_username}?start={_parts[1]}")]
                        ]
                        )
                    else:
                        await client.send_message(
                            last_bidder,
                            f"🎉 [{event.sender.first_name}](tg://user?id={event.sender.id}) just outbid you!\n\n"
                            f"🔹 {hmm['pokemon_name']} [🔗🔗🔗]({hmm['link']})\n "
                            f"🌿 {hmm['nature']}\n\n"
                            f"💸 **Your Bid:** {last_bid}\n"
                            f"📈 **Current Bid:** {validate_base(response)}\n"
                            f"📊 **Outbid By:** {validate_base(response) - last_bid}\n\n"
                            f"🔥 Hurry and place a higher bid to stay in the game!",
                            buttons=[
                                [Button.url("🛒 Bid Now", f"t.me/{bot_username}?start={_parts[1]}")]
                            ]
                        )
            else:
                await client.send_message(event.sender_id, f'Wrong bid format', buttons=[[Button.url("Bid Again", f"t.me/{bot_username}?start={_parts[1]}")]])

@client.on(events.CallbackQuery(func=lambda e: (
    e.data in [b"legendary", b"shiny", b"0L", b"tms"] or(isinstance(e.data, bytes) and (e.data.startswith(b"submit|") or e.data.startswith(b"delete|"))))))
async def handle_specific_callbacks(event):

    data = event.data.decode("utf-8")

    if data == "legendary":
        await event.delete()
        await event.answer("⚝ Legendary selected!", alert=False)
        await add_pokemon(event, 0)
    elif data == "shiny":
        await event.delete()
        await event.answer("✨ Shiny selected!", alert=False)
        await add_pokemon(event, 2)
    elif data == "0L":
        await event.delete()
        await event.answer("⭕ 0L selected!", alert=False)
        await add_pokemon(event, 1)
    elif data == "tms":
        await event.delete()
        await event.answer("⭕ TMs", alert=False)
        await add_tms(event, 3)
    elif "submit" in data:
        await event.edit(buttons=Button.clear())
        damn = data.split("|")[1]
        print(user_cache[damn])
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
        await event.answer("Done!", alert=False)
    elif data == "delete":
        await event.delete()

from telethon import events, Button

@client.on(events.CallbackQuery(func=lambda e: isinstance(e.data, bytes) and e.data.startswith(b"rej|")))
async def handle_rejection_reasons(event):
    if event.sender_id not in admins:
        await event.answer("You're not allowed to do this.", alert=True)
        return
    data_str = event.data.decode()  # convert bytes to string
    parts = data_str.split("|")
    if len(parts) < 3:
        await event.answer("Invalid rejection data!", alert=True)
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
    if res is not None:
        res["reason"] = readable_reason
        rejected_pokes.insert_one(res)
    text = f"Rejected {res['nature']} {res['pokemon_name']} cause {readable_reason}"
    await client.send_message(entity = res["user_id"], message=text)
    await event.edit(buttons=Button.clear())
    await event.reply(f"Rejected by {await md_mention(event.sender_id)}")
    user_cache.pop(ref_id)

@client.on(events.CallbackQuery(func=lambda e: isinstance(e.data, bytes) and e.data.startswith(b"accept|")))
async def handle_accept(event):
    if event.sender_id not in admins:
        await event.answer("You're not allowed to do this.", alert=True)
        return
    ref_id = event.data.decode().split("|", 1)[1]
    hmm = pending_pokes.find_one_and_delete({"token": ref_id})
    if not hmm or not isinstance(hmm, dict):
        await event.answer("This token is invalid or already processed.", alert=True)
        return
    auction_pokes.insert_one(hmm)
    kekz = await event.get_message()
    try:
        lulz = await client.get_entity(auction_channel_id)
    except:
        lulz = auction_channel_id

    if hmm['tipe'] <3:
        media = telethon.utils.get_input_media(kekz.media)
        media.spoiler = True if hmm['tipe'] == 2 else False
        m = await client.send_file(lulz, caption=hmm["text"], file=media, parse_mode="html", spoiler=True if hmm['tipe'] == 2 else False)
    else:
        m = await client.send_message(lulz, hmm["text"],parse_mode="html")
    bm =await m.reply(f"""╭────────────────╮
    Highest Bid: {hmm['base']} Pd
    By: No one right now!
╰────────────────╯""", buttons=[[Button.inline("Refresh", f"refresh|{ref_id}"), Button.url("Bid", f"t.me/{bot_username}?start={ref_id}")]])
    auction_pokes.find_one_and_update({"token": ref_id}, {"$set": {"link": f"https://t.me/Shadow_Auction/{m.id}", "bmid":bm.id}})
    await event.edit(buttons=Button.clear())
    await event.reply(f"Approved by {await md_mention(event.sender_id)}")
    user_cache.pop(ref_id)


def generate_alphanumeric_string(length=5):
    characters = string.ascii_letters + string.digits  # a-zA-Z0-9
    return ''.join(random.choices(characters, k=length))

async def add_tms(event, tipe):
    entry = config.find_one({"_id": 0}).get("entry", False)
    if not event.is_private or not entry:
        return

    user_id = event.sender_id
    user_data = {"user_id": user_id, "bids": [], "bidders": []}
    cancelled = False

    async with client.conversation(user_id) as conv:
        try:
            async def get_valid_response(prompt, validate):
                nonlocal cancelled
                while True:
                    await conv.send_message(prompt)
                    resp = await conv.get_response(timeout=900000)
                    if resp.text.lower() == "/cancel":
                        await conv.send_message("❌ Operation cancelled.")
                        cancelled = True
                        return None
                    if validate(resp):
                        return resp
                    await conv.send_message("❗ Invalid input. Try again or type /cancel to abort.")

            def validate_tm(resp):
                return (resp.fwd_from and
                        resp.fwd_from.from_id.user_id == 572621020 and
                        "Power" in resp.raw_text and "Accuracy" in resp.raw_text and "💿" in resp.raw_text)
            nature_resp = await get_valid_response("Forward Tm from bot", validate_tm)
            if cancelled: return
            user_data["info"] = nature_resp.raw_text.split("\n")[3]
            user_data["nature"] = nature_resp.raw_text.split("\n")[2]
            user_data["pokemon_name"] = nature_resp.raw_text.split("\n")[0]

            def validate_base(base):
                base = base.text
                try:
                    m = int(base)
                    return m
                except ValueError:
                    if base.lower().endswith("k"):
                        return int(float(base[:-1]) * 1000)
                return False

            base_resp = await get_valid_response("Set base:", validate_base)
            if cancelled: return
            user_data["base"] = validate_base(base_resp)
            token = generate_alphanumeric_string()
            username_line = f"<b>Username</b>- @{event.sender.username}\n" if event.sender.username else ""
            summary = (
                f"<blockquote>TMs</blockquote>\n"
                f"<blockquote>{user_data['pokemon_name']}\n"
                f"{user_data['nature']}\n"
                f"{user_data['info']}</blockquote>\n"
                f"<blockquote><b>User</b> - {user_link(event.sender)}\n"
                f"{username_line}"
                f"Base - {user_data['base']}</blockquote>\n"
                f"Item ID - <code>{token}</code>"
            )
            user_data["text"] = summary
            user_data["tipe"] = 3
            user_data["token"] = token
            user_cache[token] = user_data
            await conv.send_message(summary, parse_mode="html",
                                 buttons=[[Button.inline('SUMBIT', f'submit|{token}')],
                                          [Button.inline('DELETE', 'delete')]])
        except Exception as e:
            await conv.send_message("❌ An unexpected error occurred: " + str(e))


async def add_pokemon(event, tipe):
    entry = config.find_one({"_id": 0}).get("entry", False)
    if not event.is_private or not entry:
        return

    user_id = event.sender_id
    user_data = {"user_id": user_id, "bids":[], "bidders":[]}
    cancelled = False

    async with client.conversation(user_id) as conv:
        try:
            async def get_valid_response(prompt, validate):
                nonlocal cancelled
                while True:
                    await conv.send_message(prompt)
                    resp = await conv.get_response(timeout=900000)
                    if resp.text.lower() == "/cancel":
                        await conv.send_message("❌ Operation cancelled.")
                        cancelled = True
                        return None
                    if validate(resp):
                        return resp
                    await conv.send_message("❗ Invalid input. Try again or type /cancel to abort.")

            name_resp = await get_valid_response("Enter Pokémon name:", lambda r: len(r.text) >= 2)
            if cancelled: return
            user_data["pokemon_name"] = name_resp.text

            def validate_nature(resp):
                return (resp.media and
                        resp.fwd_from and
                        resp.fwd_from.from_id.user_id == 572621020 and
                        "| Nature:" in resp.raw_text)
            nature_resp = await get_valid_response("Forward Nature Pic of Pokémon:", validate_nature)
            if cancelled: return
            user_data["nature"] = nature_resp.raw_text.split("Exp.")[0].split("\n")[0].split("Nature: ")[1]
            user_data["level"] = nature_resp.raw_text.split("Exp.")[0].split("Lv. ")[1].split("|")[0]

            # Step 3: EVs
            def validate_evs(resp):
                return resp.media and "Points" in resp.raw_text and "IV" in resp.raw_text and resp.fwd_from.from_id.user_id == 572621020
            evs_resp = await get_valid_response("Forward EVs Pic of Pokémon:", validate_evs)
            if cancelled: return
            user_data["evs"] = evs_resp.raw_text
            user_data["image"] = evs_resp.media
            #downloaded_path = await evs_resp.download_media()
            """link = upload_file_imagekit(downloaded_path)
            user_data["im_link"] = link"""

            def validate_moveset(resp):
                return resp.media and "Power" in resp.raw_text and "Accuracy" in resp.raw_text and resp.fwd_from.from_id.user_id == 572621020
            moveset_resp = await get_valid_response("Forward Moveset Pic:", validate_moveset)
            if cancelled: return
            user_data["moveset"] = moveset_resp.raw_text

            # Step 5: Boosted
            boosted_resp = await get_valid_response("Is any stat boosted? (If Yes, mention all in one message)", lambda r: len(r.text.strip()) > 0)
            if cancelled: return
            user_data["boosted"] = boosted_resp.text

            # Step 6: Base
            def validate_base(base):
                base = base.text
                try:
                    m = int(base)
                    return m
                except ValueError:
                    if base.lower().endswith("k"):
                        return int(float(base[:-1]) * 1000)
                return False
            base_resp = await get_valid_response("Set base:", validate_base)
            if cancelled: return
            user_data["base"] = validate_base(base_resp)

            poke_tipe = {0:"LEGENDARY", 2:"SHINY", 1:"0L"}
            token = generate_alphanumeric_string()
            user_data["token"] = token

            username_line = f"<b>Username</b>- @{event.sender.username}\n" if event.sender.username else ""
            summary = (
                f"<blockquote>{poke_tipe[tipe]}</blockquote>\n"
                f"<blockquote>Pokemon Name - {user_data['pokemon_name']}\n"
                f"Level - {user_data['level']}\n"
                f"Nature - {user_data['nature']}</blockquote>\n"
                f"<code>{user_data['evs']}</code>\n\n"
                f"{user_data['moveset']}\n"
                f"<blockquote><b>User</b> - {user_link(event.sender)}\n"
                f"{username_line}"
                f"Boosted - {user_data['boosted']}\n"
                f"Base - {user_data['base']}</blockquote>\n"
                f"Item ID - <code>{token}</code>"
            )
            user_data["text"] = summary
            user_data["tipe"] = tipe
            user_cache[token] = user_data
            await conv.send_file(file=user_data['image'], caption=summary, parse_mode="html",
                                 buttons=[[Button.inline('SUMBIT', f'submit|{token}')],
                                          [Button.inline('DELETE', 'delete')]])
        except Exception as e:
            await conv.send_message("❌ An unexpected error occurred: " + str(e))

@client.on(events.NewMessage(pattern="/myitem"))
async def myitems(event):
    items = list(auction_pokes.find({"user_id": event.sender_id}))
    text = f"**Your Items in Auction:**\n\n"
    for poke in items:
        try:
            text += f"🔹 [{poke['pokemon_name'].replace('[', '').replace(']', '')} - {poke['nature'].replace('[', '').replace(']', '')}]({poke['link']})\n"
        except Exception as e:
            print(e)
    if items:
        await event.reply(text,link_preview=False)

@client.on(events.NewMessage(pattern="/mybids"))
async def mybids(event):
    items = list(auction_pokes.find({}))
    text = f"**Your Bids on Items:**\n\n"
    for poke in items:
        try:
            if poke["bidders"][-1] == event.sender_id:
                text += f"🔹 [{poke['pokemon_name'].replace('[', '').replace(']', '')} - {poke['nature'].replace('[', '').replace(']', '')}]({poke['link']})\n"
        except Exception as e:
            print(e)
    await event.reply(text,link_preview=False)

@client.on(events.NewMessage(pattern="/item"))
async def show_items(event):
    print(event)
    type_order = [
        (0, "🌟 Legendary"),
        (1, "🐉 Non-Legendary"),
        (2, "✨ Shiny"),
        (3, "📚 TMs")
    ]

    for tipe, title in type_order:
        items = list(auction_pokes.find({"tipe": tipe}))
        if items:
            return await send_items(event, items, title)

    await event.reply("❌ No Pokémon found in auction.")



# Callback handlers for each type
@client.on(events.CallbackQuery(data=b"klegend"))
async def show_legend(event):
    items = list(auction_pokes.find({"tipe": 0}))
    await send_items(event, items, "🌟 Legendary")

@client.on(events.CallbackQuery(data=b"knonlegend"))
async def show_nonlegend(event):
    items = list(auction_pokes.find({"tipe": 1}))
    await send_items(event, items, "🐉 Non-Legendary")

@client.on(events.CallbackQuery(data=b"kshiny"))
async def show_shiny(event):
    items = list(auction_pokes.find({"tipe": 2}))
    await send_items(event, items, "✨ Shiny")

@client.on(events.CallbackQuery(data=b"ktms"))
async def show_tms(event):
    items = list(auction_pokes.find({"tipe": 3}))
    await send_items(event, items, "📚 TMs")

# Shared response sender
async def send_items(event, items, title):
    if not items:
        return await event.edit(f"❌ No {title.lower()} found.", buttons=[
                [Button.inline("🌟 Legendary", data="klegend")],
                [Button.inline("🐉 Non-Legendary", data="knonlegend")],
                [Button.inline("✨ Shiny", data="kshiny")],
                [Button.inline("📚 TMs", data="ktms")]
            ])

    text = f"**{title} Pokémon in Auction:**\n\n"
    for poke in items:
        try:
            text += f"🔹 [{poke['pokemon_name'].replace('[', '').replace(']', '')} - {poke['nature'].replace('[', '').replace(']', '')}]({poke['link']})\n"
        except Exception as e:
            print(e)

    try:
        await event.edit(
            text,
            buttons=[
                [Button.inline("🌟 Legendary", data="klegend")],
                [Button.inline("🐉 Non-Legendary", data="knonlegend")],
                [Button.inline("✨ Shiny", data="kshiny")],
                [Button.inline("📚 TMs", data="ktms")]
            ],
            link_preview=False
        )
    except telethon.errors.rpcerrorlist.MessageNotModifiedError:
        pass
    except Exception as e:
        #traceback.print_exc()
        await event.reply(
            text,
            buttons=[
                [Button.inline("🌟 Legendary", data="klegend")],
                [Button.inline("🐉 Non-Legendary", data="knonlegend")],
                [Button.inline("✨ Shiny", data="kshiny")],
                [Button.inline("📚 TMs", data="ktms")]
            ],
            link_preview=False
        )
