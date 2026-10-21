from telethon import events, Button
from telethon.tl.types import PeerUser
from telethon.tl.functions.users import GetFullUserRequest as GetFullUser
from telethon.tl.types import InputUser
from bot import client, config, admins, verified, bid_banned, sub_banned, auction_pokes, auction_channel_id, \
    bot_username, user_db, previous_data, final_logs_id, rejected_pokes
import asyncio

@client.on(events.NewMessage(pattern=r"/clear_db", from_users=[8511293134, 1101488645]))
async def addadmin(event):
    auction_pokes.delete_many({})
    await event.reply("Done")

@client.on(events.NewMessage(pattern=r"/addadmin", from_users=[8511293134, 1101488645]))
async def addadmin(event):
    if event.message.reply_to and event.message.reply_to.reply_to_msg_id:
        replied_msg = await client.get_messages(event.chat_id, ids=event.message.reply_to.reply_to_msg_id)
        if replied_msg.from_id.user_id in admins:
            return await event.reply("Already admin.")
        admins.append(replied_msg.from_id.user_id)
        config.find_one_and_update({"_id": 0}, {"$push": {"admins": replied_msg.from_id.user_id}})
        await event.reply("Done")
    else:
        uid = event.raw_text.split(" ", 1)[1]
        if uid.isdigit():
            uid = int(uid)
            if uid in admins:
                return await event.reply("Already admin.")
            admins.append(uid)
            config.find_one_and_update({"_id": 0}, {"$push": {"admins": uid}})
        elif "@" in uid:
            try:
                peer = await client.get_entity(uid.replace('@', ''))
                target_id = peer.id
                if target_id in admins:
                    return await event.reply("Already verified.")
                admins.append(target_id)
                config.find_one_and_update({"_id": 0}, {"$push": {"admins": target_id}})
            except Exception as e:
                return await event.reply(f"❌ Error getting user {uid}: {e}")
        else:
            return await event.reply("Either reply or use user id")
        await event.reply("Done")

@client.on(events.NewMessage(pattern=r"/remadmin", from_users=[1037179104, 1655924853]))
async def remadmin(event):
    if event.message.reply_to and event.message.reply_to.reply_to_msg_id:
        replied_msg = await client.get_messages(event.chat_id, ids=event.message.reply_to.reply_to_msg_id)
        uid = replied_msg.from_id.user_id
        if uid not in admins:
            return await event.reply("User is not admin.")
        admins.remove(uid)
        config.find_one_and_update({"_id": 0}, {"$pull": {"admins": uid}})
        await event.reply("Done")
    else:
        try:
            uid = event.raw_text.split(" ", 1)[1]
        except IndexError:
            return await event.reply("Please reply to a user or provide a user ID or username.")
        if uid.isdigit():
            uid = int(uid)
        elif "@" in uid:
            try:
                peer = await client.get_entity(uid.replace('@', ''))
                uid = peer.id
            except Exception as e:
                return await event.reply(f"❌ Error getting user {uid}: {e}")
        else:
            return await event.reply("Invalid format. Provide a user ID or @username.")
        if uid not in admins:
            return await event.reply("User is not admin.")
        admins.remove(uid)
        config.find_one_and_update({"_id": 0}, {"$pull": {"admins": uid}})
        await event.reply("Done")

@client.on(events.NewMessage(pattern=r"/entry\s+(on|off)", from_users=admins))
async def entry(event):
    action = event.pattern_match.group(1).lower()
    res = config.find_one({"_id": 0})
    current_state = res.get("entry", False)

    if action == "on":
        if current_state:
            await event.reply("Entry is already enabled.")
        else:
            config.update_one({"_id": 0}, {"$set": {"entry": True}})
            await event.reply("Entry has been enabled.")
    else:
        if not current_state:
            await event.reply("Entry is already disabled.")
        else:
            config.update_one({"_id": 0}, {"$set": {"entry": False}})
            await event.reply("Entry has been disabled.")

@client.on(events.NewMessage(pattern=r"/bid\s+(on|off)", from_users=admins))
async def bid(event):
    action = event.pattern_match.group(1).lower()
    res = config.find_one({"_id": 0})
    current_state = res.get("bid", False)

    if action == "on":
        if current_state:
            await event.reply("Bid is already enabled.")
        else:
            config.update_one({"_id": 0}, {"$set": {"bid": True}})
            await event.reply("Bid has been enabled.")
    else:
        if not current_state:
            await event.reply("Bid is already disabled.")
        else:
            config.update_one({"_id": 0}, {"$set": {"bid": False}})
            await event.reply("Bid has been disabled.")

@client.on(events.NewMessage(pattern=r"/auction\s+(on|off)", from_users=admins))
async def auction(event):
    action = event.pattern_match.group(1).lower()
    res = config.find_one({"_id": 0})
    current_state = res.get("auction", False)

    if action == "on":
        if current_state:
            return await event.reply("Auction is already ongoing.")
        else:
            config.update_one({"_id": 0}, {"$set": {"auction": True}})
            await event.reply("Auction started.")
            for user in verified:
                pass
                #await client.send_message(user, "Auction started. Time to bid")
    else:
        if not current_state:
            return await event.reply("Auction is already disabled.")
        else:
            config.update_one({"_id": 0}, {"$set": {"auction": False}})
            await event.reply("Auction has been disabled.")
        docs = list(auction_pokes.find())
        await event.reply("Spam started")
        for doc in docs:
            doc.pop('_id', None)
        if docs:
            previous_data.insert_many(docs)
        for doc in docs:
            try:
                text = (
                    f"🔹 **Pokémon:** {doc['pokemon_name']}\n"
                    f"🌿 **Nature:** {doc['nature']}\n"
                    f"📊 **Base:** `{doc['base']}`\n"
                    f"🆔 **Item ID:** `{doc['token']}`\n"
                    f"🔗 [View Pokémon]({doc['link']})\n\n"
                    f"💰 **Buyer:** `{doc['bidders'][-1]}`\n"
                    f"💵 **Price:** `{doc['bids'][-1]}`"
                )
            except:
                print("skipping")
                continue
            await asyncio.sleep(1)
            try:
                await client.edit_message(auction_channel_id, doc['bmid'], buttons=Button.clear())
            except:
                pass
            
            try:
                await client.send_message(final_logs_id, f"👤 **Seller:** `{doc['user_id']}`\n"+text)
            except:
                pass
            await asyncio.sleep(1)
            try:
                await client.send_message(doc['user_id'], text)
            except:
                pass
            try:
                await client.send_message(doc['bidders'][-1], f"You won the bid for \n\n{text}")
            except:
                pass
        auction_pokes.delete_many({})
        await event.reply("Spam done")


@client.on(events.NewMessage(pattern=r"/verify", from_users=admins))
async def verify(event):
    if event.message.reply_to and event.message.reply_to.reply_to_msg_id:
        replied_msg = await client.get_messages(event.chat_id, ids=event.message.reply_to.reply_to_msg_id)
        if replied_msg.from_id.user_id in verified:
            return await event.reply("Already verified.")
        verified.append(replied_msg.from_id.user_id)
        config.find_one_and_update({"_id": 0}, {"$push": {"verified": replied_msg.from_id.user_id}})
        await event.reply("Done")
    else:
        uid = event.raw_text.split(" ", 1)[1]

        if uid.isdigit():
            uid = int(uid)
            if uid in verified:
                return await event.reply("Already verified.")
            verified.append(uid)
            config.find_one_and_update({"_id": 0}, {"$push": {"verified": uid}})
        elif "@" in uid:
            try:
                peer = await client.get_entity(uid.replace('@', ''))
                target_id = peer.id
                if target_id in verified:
                    return await event.reply("Already verified.")
                verified.append(target_id)
                config.find_one_and_update({"_id": 0}, {"$push": {"verified": target_id}})
            except Exception as e:
                return await event.reply(f"❌ Error getting user {uid}: {e}")
        else:
            return await event.reply("Either reply or use user id")
        await event.reply("Done")

@client.on(events.NewMessage(pattern=r"/unverify", from_users=admins))
async def unverify(event):
    if event.message.reply_to and event.message.reply_to.reply_to_msg_id:
        replied_msg = await client.get_messages(event.chat_id, ids=event.message.reply_to.reply_to_msg_id)
        uid = replied_msg.from_id.user_id
        if uid not in verified:
            return await event.reply("User is not verified.")
        verified.remove(uid)
        config.find_one_and_update({"_id": 0}, {"$pull": {"verified": uid}})
        await event.reply("❌ User has been unverified.")
    else:
        try:
            uid = event.raw_text.split(" ", 1)[1]
        except IndexError:
            return await event.reply("Please reply to a user or provide a user ID or username.")
        if uid.isdigit():
            uid = int(uid)
        elif "@" in uid:
            try:
                peer = await client.get_entity(uid.replace('@', ''))
                uid = peer.id
            except Exception as e:
                return await event.reply(f"❌ Error getting user {uid}: {e}")
        else:
            return await event.reply("Invalid format. Provide a user ID or @username.")
        if uid not in verified:
            return await event.reply("User is not verified.")
        verified.remove(uid)
        config.find_one_and_update({"_id": 0}, {"$pull": {"verified": uid}})
        await event.reply("❌ User has been unverified.")

@client.on(events.NewMessage(pattern=r"/bban", from_users=admins))
async def ban(event):
    if event.message.reply_to and event.message.reply_to.reply_to_msg_id:
        replied_msg = await client.get_messages(event.chat_id, ids=event.message.reply_to.reply_to_msg_id)
        if replied_msg.from_id.user_id in bid_banned:
            return await event.reply("Already banned from bidding.")
        bid_banned.append(replied_msg.from_id.user_id)
        config.find_one_and_update({"_id": 0}, {"$push": {"bid_banned": replied_msg.from_id.user_id}})
        await event.reply("Done")
    else:
        uid = event.raw_text.split(" ", 1)[1]
        if uid.isdigit():
            uid = int(uid)
            if uid in bid_banned:
                return await event.reply("Already banned from bidding.")
            bid_banned.append(uid)
            config.find_one_and_update({"_id": 0}, {"$push": {"bid_banned": uid}})
        elif "@" in uid:
            try:
                peer = await client.get_entity(uid.replace('@', ''))
                target_id = peer.id
                if target_id in bid_banned:
                    return await event.reply("Already banned from bidding.")
                bid_banned.append(target_id)
                config.find_one_and_update({"_id": 0}, {"$push": {"bid_banned": target_id}})
            except Exception as e:
                return await event.reply(f"❌ Error getting user {uid}: {e}")
        else:
            return await event.reply("Either reply or use user id")
        await event.reply("Done")

@client.on(events.NewMessage(pattern=r"/b_unban", from_users=admins))
async def unban(event):
    if event.message.reply_to and event.message.reply_to.reply_to_msg_id:
        replied_msg = await client.get_messages(event.chat_id, ids=event.message.reply_to.reply_to_msg_id)
        uid = replied_msg.from_id.user_id
        if uid not in bid_banned:
            return await event.reply("User is not banned from bidding.")
        bid_banned.remove(uid)
        config.find_one_and_update({"_id": 0}, {"$pull": {"bid_banned": uid}})
        await event.reply("✅ User has been unbanned.")
    else:
        try:
            uid = event.raw_text.split(" ", 1)[1]
        except IndexError:
            return await event.reply("Please reply to a user or provide a user ID or username.")

        if uid.isdigit():
            uid = int(uid)
        elif "@" in uid:
            try:
                peer = await client.get_entity(uid.replace('@', ''))
                uid = peer.id
            except Exception as e:
                return await event.reply(f"❌ Error getting user {uid}: {e}")
        else:
            return await event.reply("Invalid format. Provide a user ID or @username.")

        if uid not in bid_banned:
            return await event.reply("User is not banned from bidding.")
        bid_banned.remove(uid)
        config.find_one_and_update({"_id": 0}, {"$pull": {"bid_banned": uid}})
        await event.reply("✅ User has been unbanned.")

@client.on(events.NewMessage(pattern=r"/sban", from_users=admins))
async def ban(event):
    if event.message.reply_to and event.message.reply_to.reply_to_msg_id:
        replied_msg = await client.get_messages(event.chat_id, ids=event.message.reply_to.reply_to_msg_id)
        if replied_msg.from_id.user_id in sub_banned:
            return await event.reply("Already banned from submission.")
        sub_banned.append(replied_msg.from_id.user_id)
        config.find_one_and_update({"_id": 0}, {"$push": {"sub_banned": replied_msg.from_id.user_id}})
        await event.reply("Done")
    else:
        uid = event.raw_text.split(" ", 1)[1]
        if uid.isdigit():
            uid = int(uid)
            if uid in sub_banned:
                return await event.reply("Already banned from submission.")
            sub_banned.append(uid)
            config.find_one_and_update({"_id": 0}, {"$push": {"sub_banned": uid}})
        elif "@" in uid:
            try:
                peer = await client.get_entity(uid.replace('@', ''))
                target_id = peer.id
                if target_id in sub_banned:
                    return await event.reply("Already banned from submission.")
                sub_banned.append(target_id)
                config.find_one_and_update({"_id": 0}, {"$push": {"sub_banned": target_id}})
            except Exception as e:
                return await event.reply(f"❌ Error getting user {uid}: {e}")
        else:
            return await event.reply("Either reply or use user id")
        await event.reply("Done")

@client.on(events.NewMessage(pattern=r"/s_unban", from_users=admins))
async def unban(event):
    if event.message.reply_to and event.message.reply_to.reply_to_msg_id:
        replied_msg = await client.get_messages(event.chat_id, ids=event.message.reply_to.reply_to_msg_id)
        uid = replied_msg.from_id.user_id
        if uid not in sub_banned:
            return await event.reply("User is not banned from submission.")
        sub_banned.remove(uid)
        config.find_one_and_update({"_id": 0}, {"$pull": {"sub_banned": uid}})
        await event.reply("✅ User has been unbanned.")
    else:
        try:
            uid = event.raw_text.split(" ", 1)[1]
        except IndexError:
            return await event.reply("Please reply to a user or provide a user ID or username.")

        if uid.isdigit():
            uid = int(uid)
        elif "@" in uid:
            try:
                peer = await client.get_entity(uid.replace('@', ''))
                uid = peer.id
            except Exception as e:
                return await event.reply(f"❌ Error getting user {uid}: {e}")
        else:
            return await event.reply("Invalid format. Provide a user ID or @username.")

        if uid not in sub_banned:
            return await event.reply("User is not banned.")
        sub_banned.remove(uid)
        config.find_one_and_update({"_id": 0}, {"$pull": {"sub_banned": uid}})
        await event.reply("✅ User has been unbanned.")

@client.on(events.NewMessage(pattern=r"/remitem", from_users=admins))
async def resetbid(event):
    mess_sp = event.raw_text.split(" ", 2)
    if len(mess_sp) < 2:
        return await event.reply("Please put item id for which it is to be removed.")
    item_id = mess_sp[1]
    mm = auction_pokes.find_one_and_delete({"token": item_id})
    try:
        await client.delete_messages(auction_channel_id, mm["bmid"])
    except:
        pass
    try:
        await client.delete_messages(auction_channel_id, int(mm["link"].split("/")[-1]))
    except: pass
    if len(mess_sp) != 3:
        await client.send_message(mm["user_id"], f"Admins Removed {mm['nature']} {mm['pokemon_name']}")
    else:
        await client.send_message(mm["user_id"], f"Admins Removed {mm['nature']} {mm['pokemon_name']} cause {mess_sp[2]}")
    await event.reply("Done")


@client.on(events.NewMessage(pattern=r"/resetbid", from_users=admins))
async def resetbid(event):
    mess_sp = event.raw_text.split(" ")
    if len(mess_sp) != 2:
        return await event.reply("Please put item id for which it is to be reset.")
    item_id = mess_sp[1]
    mm = auction_pokes.find_one_and_update({"token": item_id}, {"$set": {"bids": [], "bidders":[]}})
    await client.edit_message(auction_channel_id, mm["bmid"], f"""╭────────────────╮
    Highest Bid: {mm['base']} Pd
    By: No one right now!
╰────────────────╯""", buttons=[[Button.inline("Refresh", f"refresh|{item_id}"), Button.url("Bid", f"t.me/{bot_username}?start={item_id}")]] )

def validate_base(base):
    try:
        m = int(base)
        return m
    except ValueError:
        if base.lower().endswith("k"):
            return int(float(base[:-1]) * 1000)
    return False

@client.on(events.NewMessage(pattern=r"/setbid", from_users=admins))
async def setbid(event):
    mess_sp = event.raw_text.split(" ", 3)
    if len(mess_sp) != 4:
        return await event.reply("Invalid use like /setbid item_id user_id bid")

    target = user_db.find_one({"_id": int(mess_sp[2])})
    if target is None:
        return await event.reply("Dunno that user..")

    mm = auction_pokes.find_one({"token": mess_sp[1]})
    if mm is None:
        return await event.reply("Auction item not found.")

    if not validate_base(mess_sp[-1]):
        return await event.reply("Incorrect bid amount.")

    mm = auction_pokes.find_one_and_update({"token": mess_sp[1]},
                                          {"$push": {"bids": validate_base(mess_sp[-1]), "bidders": int(mess_sp[2])}})
    try:
        user = await client(GetFullUser(InputUser(user_id=target["_id"], access_hash=target["hash"])))
        first_name = user.users[0].first_name
    except Exception as e:
        first_name = mess_sp[2]
    text = f"""╭────────────────╮
    Highest Bid: {validate_base(mess_sp[-1])} Pd
    By: [{first_name}](tg://user?id={mess_sp[2]})
╰────────────────╯"""
    await client.edit_message(auction_channel_id, mm["bmid"], text,
                              buttons=[[Button.inline("Refresh", f"refresh|{mess_sp[1]}"),
                                        Button.url("Bid", f"t.me/{bot_username}?start={mess_sp[1]}")]])


    await event.reply("Done")


@client.on(events.NewMessage(pattern=r"/rollback", from_users=admins))
async def rollback(event):
    mess_sp = event.raw_text.split(" ")
    if len(mess_sp) < 2:
        return await event.reply("Please provide the item id.")

    item_id = mess_sp[1]
    num = 1  # default rollback count

    if len(mess_sp) == 3:
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

    # Remove last num bids and bidders
    new_bids = bids[:-num]
    new_bidders = bidders[:-num]

    auction_pokes.find_one_and_update(
        {"token": item_id},
        {"$set": {"bids": new_bids, "bidders": new_bidders}}
    )

    if len(new_bids) == 0:
        await event.reply(f"Rolled back {num} bids. No bids left now.")
        await client.edit_message(auction_channel_id, doc["bmid"], f"""╭────────────────╮
            Highest Bid: {doc['base']} Pd
            By: No one right now!
        ╰────────────────╯""", buttons=[[Button.inline("Refresh", f"refresh|{item_id}"),
                                         Button.url("Bid", f"t.me/{bot_username}?start={item_id}")]])
    else:
        try:
            target =  user_db.find_one({"_id": int(new_bidders[-1])})
            user = await client(GetFullUser(InputUser(user_id=target["_id"], access_hash=target["hash"])))
            first_name = user.users[0].first_name
        except  Exception as e:
            first_name = new_bidders[-1]
        text = f"""╭────────────────╮
    Highest Bid: {validate_base(new_bids[-1])} Pd
    By: [{first_name}](tg://user?id={new_bidders[-1]})
╰────────────────╯"""
        await client.edit_message(auction_channel_id, doc["bmid"], text,
                              buttons=[[Button.inline("Refresh", f"refresh|{item_id}"),
                                        Button.url("Bid", f"t.me/{bot_username}?start={item_id}")]])
        await event.reply(f"Rolled back {num} bids.\n"
                          f"Current last bid: {new_bids[-1]}\n"
                          f"Current last bidder: [{first_name}](tg://user?id={new_bidders[-1]})")

@client.on(events.NewMessage(pattern=r"/msg", from_users=admins))
async def snipe(event):
    mess_sp = event.raw_text.split(" ", 2)
    if len(mess_sp) != 3:
        return await event.reply("Invalid use like /msg user_id msg")
    await client.send_message(int(mess_sp[1]), mess_sp[2])
    await event.reply("Done")

@client.on(events.NewMessage(pattern=r"/broadcast", from_users=admins))
async def bcast(event):
    if event.message.reply_to and event.message.reply_to.reply_to_msg_id:
        replied_msg = await event.get_reply_message()
        await event.reply("Starting broadcast...")
        user_ids = [doc["_id"] for doc in user_db.find({}, {"_id": 1})]
        success = 0
        failed = 0

        for uid in user_ids:
            try:
                await replied_msg.forward_to(uid)
                success += 1
            except Exception as e:
                failed += 1
        await event.reply(f"Broadcast completed.\n✅ Sent: {success}\n❌ Failed: {failed}")
        return
    else:
        msg = event.raw_text.split(" ", 1)[1]
        user_ids = [doc["_id"] for doc in user_db.find({}, {"_id": 1})]
        success = 0
        failed = 0

        for uid in user_ids:
            try:
                await client.send_message(uid, msg)
                success += 1
            except Exception as e:
                failed += 1
        await event.reply(f"Broadcast completed.\n✅ Sent: {success}\n❌ Failed: {failed}")
        return
        
@client.on(events.NewMessage(pattern=r"/profile"))
async def unverify(event):
    if event.message.reply_to and event.message.reply_to.reply_to_msg_id:
        replied_msg = await client.get_messages(event.chat_id, ids=event.message.reply_to.reply_to_msg_id)
        uid = replied_msg.from_id.user_id
        username = uid
        return
    elif len(event.raw_text.split(" ")) == 2:
        try:
            uid = event.raw_text.split(" ", 1)[1]
        except IndexError:
            return await event.reply("Please reply to a user or provide a user ID or username.")
        if uid.isdigit():
            uid = int(uid)
            target = user_db.find_one({"_id": uid})
            user = await client(GetFullUser(InputUser(user_id=target["_id"], access_hash=target["hash"])))
            username = uid
            return
        elif "@" in uid:
            username = uid
            try:
                peer = await client.get_entity(uid.replace('@', ''))
                uid = peer.id
                
            except Exception as e:
                return await event.reply(f"❌ Error getting user {uid}: {e}")
        else:
            return await event.reply("Invalid format. Provide a user ID or @username.")
    else:
        uid = event.sender_id
        username = event.sender_id
    post = "[❌](https://envs.sh/0ul.jpg) Not verified"
    if uid in verified:
        post = "[✅](https://envs.sh/0ul.jpg) Verified"
    if uid in admins:
        post = "[👑](https://envs.sh/0ul.jpg) Admin"
    total_auc_count = auction_pokes.count_documents({"user_id":uid})
    rejected_auc_count = rejected_pokes.count_documents({"user_id":uid})
    l_count = auction_pokes.count_documents({'tipe': 0, "user_id":uid})
    ol_count = auction_pokes.count_documents({'tipe': 1, "user_id":uid})
    s_count = auction_pokes.count_documents({'tipe': 2, "user_id":uid})
    t_count = auction_pokes.count_documents({'tipe': 3, "user_id":uid})
    try:
        kak_value = (total_auc_count/(total_auc_count+rejected_auc_count))*100
    except ZeroDivisionError:
        kak_value = "0"
    #user_line = 
    format_m = f"""{username} {post}

〘 Total Approved 〙
   • ʟᴇɢᴇɴᴅᴀʀʏ : {l_count}
   • ɴᴏɴ-ʟᴇɢᴇɴᴅᴀʀʏ : {ol_count}
   • sʜɪɴʏ : {s_count}
   • ᴛᴍs : {t_count}

📊 Total submitted: {total_auc_count+rejected_auc_count}
☑️ Total approved: {total_auc_count}
⬜️ Approve Ratio: {kak_value}%"""
    await event.reply(format_m)

