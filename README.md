# .ascii bot

Архивная версия Telegram-бота, который превращает видео в ASCII-анимацию.

Актуальная версия находится в репозитории [ascii video studio](https://github.com/dayanegosha/ascii-video-studio). Этот репозиторий сохранён для истории.

Бот умеет делать цветное и монохромное видео, менять детализацию и показывать прогресс. Для работы нужны Python 3.10+, FFmpeg и токен Telegram-бота.

## запуск

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export BOT_TOKEN="token-from-botfather"
python bot.py
```

Видео ограничено тремя минутами. Команда `/stop` отменяет текущую обработку.

## лицензия

[MIT](LICENSE)
