## What it does

Sends Valo messages to Telegram. Forwards notifications (leak, smoke, carbon monoxide, device not responding, low battery), adds the flow block "Telegram message" with event variables and action buttons, and answers `/status`, `/devices`, `/help`.

## One-time setup

1. In Telegram message @BotFather, run `/newbot` and keep the token `123456:ABC...`
2. Send `/start` to your bot. For a family chat add the bot to the group and send `/start` there. The bot replies with the chat id
3. In Valo: Extensions, Catalog, Telegram, Install. Open the extension and paste the token
4. Open the Telegram page in the menu. Copy lines like `Family=-100123` from "Chats that messaged the bot" into **Recipients**, one per line or separated by `;`. A name like `@user` does not work, Telegram does not let a bot write by name, a numeric chat id is needed. The Telegram page shows such lines as not accepted. The delivery error "chat not found" means the bot is not in the chat or the chat number has changed, for example a group became a supergroup with a number like `-100...`
5. Optionally list Telegram user ids allowed to press buttons and send commands in **Admins**. Empty means every member of the recipient chats
6. Save and press "Send test" on the Telegram page

One bot cannot serve two Valo environments (demo and live) at the same time.

## How to use

**Without flows.** System, Home, "Levels sent to external delivery": choose the levels. Critical notifications go to all recipients with sound.

**In flows.** The "Telegram message" block: recipients by name (empty means all), text with `{device}`, `{room}`, `{cap}`, `{value}`, `{old}`, `{unit}`, `{time}`, `{date}`, `{flow}`, `{home}`, `{low_battery}`, `{offline}`, `{alarms}`, a silent flag and up to two action buttons (device, label, values). A button works once within a day.

Ready templates: alarm to everyone, leak of a chosen sensor, device offline for 30 minutes, daily low battery, plug power above a threshold with a "Turn off" button.

**Camera snapshot or clip.** The «Snapshot or clip to Telegram» block sends a photo or video with a caption:

- **Recipients** and **Text** as in a message, the text also accepts `{label}`, the camera event type (motion, person)
- **Camera**: empty means the camera from the «Camera event» trigger
- **What to send**: a camera snapshot now, the snapshot or clip from the flow (after the «Camera snapshot» action), the latest camera recording, or record a clip of a given number of seconds
- **Silent**: the message arrives without sound

The file is sent in the background, the flow does not wait for it. A clip is sent when the recording is ready, usually after the clip length plus a few seconds. Telegram accepts photos up to 10 MB and videos up to 50 MB. If a file is larger or sending fails, a text with the reason and a link to the recording arrives instead. For the link set **Valo address for links** in the extension settings, for example `http://192.168.0.10:3100`. The block needs permissions to read and write media, they are confirmed when the extension is updated.

**Bot commands** (recipient chats only): `/status`, `/devices`, `/help`.

Identical messages are not repeated more often than every N minutes. During quiet hours messages are silent except critical ones. Delivery errors appear in System, Errors.
