# Advanced File Store Bot  (build: latest, all features included)

Files: bot.py, config.py, database.py, helpers.py, smallcaps.py, stream.py, weblinks.py, plugins/{start,files,admin,premium}.py

## Features
- /genlink (single), /batch, /custom_batch (Stop button) - Base64 links, saves any message type
- Force-sub (public / private / request) managed from /settings -> Force-Sub
- 1/2-step verification with gap time, /testverify
- Auto-delete, protect content, "please wait" message with Cancel button
- Premium: /addpremium /removepremium /premiums /plans /myplan
- Premium-only streaming (web player 0.5x-3x, MX Player / PLAYit / VLC buttons)
- Sponsor button, welcome photo + buttons, Settings button for admin/owner
- Log channel: #NewUser (once per new user) and #BotRestarted, /setlog, /restart (owner)
- Permanent website links (/f/<code>), toggle in /settings -> Website, /revoke
- All text in English + small caps, command menu set automatically

## Render env vars
API_ID, API_HASH, BOT_TOKEN, MONGO_URI, OWNER_ID, DB_CHANNEL (optional), LOG_CHANNEL (optional), BASE_URL (optional)
Start command: python bot.py
