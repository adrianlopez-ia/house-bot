# Skill: Add New Telegram Command

Follow these steps to add a new command to the House Bot.

## 1. Define the handler in `notifier/service.py`
Add a new `async` method to the `NotifierService` class starting with `_h_`.
```python
async def _h_my_command(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    # Logic here
    await self._reply(update, "My response")
```

## 2. Register the handler
In the `_register_handlers` method, add the handler to the application:
```python
h(CommandHandler("my_command", self._h_my_command))
```

## 3. Update the `_COMMANDS` constant
Add the command to the `_COMMANDS` tuple at the top of the file so it shows up in the Telegram menu:
```python
BotCommand("my_command", "Description of my command"),
```

## 4. Update `_HELP_TEXT`
Add the command description to the `_HELP_TEXT` string.

## 5. Verify
Run the bot and send `/my_command` in Telegram to test.
