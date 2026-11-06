"""
Join gate.

Nobody can use ANY command / button of the bot unless they have joined:
  - @HexaAuction (channel)
  - the private group

This file must be imported before admin_funcs / pokemon_adder (see main.py):
Telethon runs handlers in registration order, and the handlers here raise
StopPropagation for users who have not joined, so no later handler runs.

Owners are never blocked (so the bot can always be managed).
"""
import re
import time
import traceback

from telethon import events, Button
from telethon.errors import UserNotParticipantError
from telethon.tl.functions.channels import GetParticipantRequest
from telethon.tl.types import ChannelParticipantLeft, ChannelParticipantBanned

from bot import client, bot_username, OWNERS, REQUIRED_CHATS

CACHE_TTL = 120          # seconds a "joined" result is remembered (saves API calls)
_joined_cache = {}       # user_id -> timestamp of last successful check


class CheckError(Exception):
    """Membership could not be checked (bot not admin / chat not reachable)."""


async def _resolve(refs):
    last = None
    for ref in refs:
        try:
            return await client.get_input_entity(ref)
        except Exception as e:  # not cached / wrong ref -> try the next one
            last = e
    raise CheckError(f"cannot resolve {refs}: {last}")


async def _is_in(chat, input_user):
    inp = await _resolve(chat["refs"])
    try:
        res = await client(GetParticipantRequest(inp, input_user))
    except UserNotParticipantError:
        return False
    except Exception as e:
        raise CheckError(f"{chat['name']}: {e}")
    return not isinstance(res.participant, (ChannelParticipantLeft, ChannelParticipantBanned))


async def missing_chats(user_id, input_user, force=False):
    """Return the list of required chats the user has NOT joined ([] = all joined)."""
    if not force and time.time() - _joined_cache.get(user_id, 0) < CACHE_TTL:
        return []
    missing = []
    for chat in REQUIRED_CHATS:
        if not await _is_in(chat, input_user):
            missing.append(chat)
    if not missing:
        _joined_cache[user_id] = time.time()
    else:
        _joined_cache.pop(user_id, None)
    return missing


def join_buttons():
    rows = [[Button.url(c["button"], c["url"])] for c in REQUIRED_CHATS]
    rows.append([Button.inline("✅ I've joined", b"chkjoin")])
    return rows


def join_text(missing):
    lines = "\n".join(f"• {c['name']}" for c in missing)
    return ("🚫 You must join the following to use this bot:\n\n"
            f"{lines}\n\n"
            "Join, then tap “✅ I've joined” (or send the command again).")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
@client.on(events.NewMessage(pattern=r"^/"))
async def gate_commands(event):
    if event.out or not event.sender_id or event.sender_id in OWNERS:
        return
    if event.is_channel and not event.is_group:      # channel posts, not users
        return
    # "/cmd@SomeOtherBot" is not meant for us
    m = re.match(r"^/\w+@(\w+)", event.raw_text or "")
    if m and m.group(1).lower() != str(bot_username).lstrip("@").lower():
        return

    try:
        missing = await missing_chats(event.sender_id, await event.get_input_sender())
    except Exception:
        traceback.print_exc()
        await event.reply("⚠️ Couldn't verify your membership right now. Please try again in a moment.")
        raise events.StopPropagation
    if not missing:
        return
    await event.reply(join_text(missing), buttons=join_buttons(), link_preview=False)
    raise events.StopPropagation


# ---------------------------------------------------------------------------
# Buttons
# ---------------------------------------------------------------------------
@client.on(events.CallbackQuery())
async def gate_buttons(event):
    if event.data == b"chkjoin" or event.sender_id in OWNERS:
        return
    try:
        missing = await missing_chats(event.sender_id, await event.get_input_sender())
    except Exception:
        traceback.print_exc()
        await event.answer("Couldn't verify your membership right now. Try again later.", alert=True)
        raise events.StopPropagation
    if not missing:
        return
    names = ", ".join(c["button"] for c in missing)
    await event.answer(f"Join first: {names}. Then send /start.", alert=True)
    raise events.StopPropagation


@client.on(events.CallbackQuery(data=b"chkjoin"))
async def check_joined(event):
    try:
        missing = await missing_chats(event.sender_id, await event.get_input_sender(), force=True)
    except Exception:
        traceback.print_exc()
        return await event.answer("Couldn't verify right now. Try again later.", alert=True)
    if missing:
        names = ", ".join(c["button"] for c in missing)
        return await event.answer(f"❌ You still haven't joined: {names}", alert=True)
    await event.answer("✅ Verified! You can use the bot now.", alert=True)
    try:
        await event.delete()
    except Exception:
        pass
