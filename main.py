from bot import client
import gate            # must be imported FIRST so the join check runs before every command
import admin_funcs
import pokemon_adder
print("Bot is running...")
client.run_until_disconnected()
