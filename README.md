# Bass + 8D Bot (Pro)

pip install pyTelegramBotAPI telethon
python bot.py            # background: nohup python bot.py > out.log 2>&1 &

- TOKEN / ADMIN / API_ID / API_HASH are set at the top of bot.py (env vars override).
- On start the bot validates API_ID/API_HASH (format + real login). If invalid, it explains why
  (admin message + /admin > server status > "re-check") and keeps working with the 20MB limit.
- Admin panel: /admin  -  Backup: panel > backup (download / upload).
- Big files use ffmpeg + Telethon; ffmpeg must be installed (or: pip install imageio-ffmpeg).
