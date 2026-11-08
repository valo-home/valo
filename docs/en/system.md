# System

The **System** section gathers home settings, users, API tokens, backups, the error log, assistant settings and the hub status. The set of tabs depends on the role. An administrator and the owner see all tabs, a resident and a guest only **API tokens** and **Hub status**.

## Home

- **Home name**
- **Latitude** and **Longitude**. They are used to compute sunrise and sunset for automations, extensions take the weather for them as well
- **Time zone**. Automation schedules run in it and today's usage is counted in it
- **Currency** for energy cost
- The home **Language**. Notification texts are built in it, including external ones, and the names of new extension devices
- **Days of detailed history**. Older device values are deleted
- **Levels sent to external delivery**. Notifications of these levels go to external channels, for example Telegram. By default only critical. A **Notification** block with **Send externally** ticked is sent regardless of this setting
- **Daily backup**. Turns on an automatic backup once a day at night. If the hub was off at night and there has been no backup for more than 26 hours, it is created within an hour after the hub starts

Press **Save** to apply the changes.

## Users

A table of users with name, username, role, accessible rooms and the time of the last sign in.

1. Press **Add user**
2. Fill in **Name**, **Username**, a **Password** of at least six characters, **Role** and **Language**
3. In **Room access** tick rooms if the user should see only them. If no rooms are selected, access is not restricted
4. **Save**

Pressing a name opens the user for editing. An empty password field keeps the previous password. Untick **Account active** to block sign in temporarily, or delete the user with the **Delete** button and a confirmation. You cannot delete yourself. The last owner cannot be demoted, disabled or deleted.

## Roles

- **Guest** only views the home, dashboards, devices, automations, the log and extension pages
- **Resident** additionally controls devices, applies scenes, runs and tests automations, creates and changes dashboards, creates own API tokens
- **Administrator** additionally sets up rooms and devices, adds Zigbee and MQTT devices, creates automations and scenes, installs and configures extensions, manages users except owners, changes home settings, creates backups, sees errors and configures the assistant
- **Owner** can do everything, including restoring the hub from a backup, uploading backups, changing the Zigbee channel and appointing other owners

The room restriction applies to any role. A restricted user sees and changes only the devices of their rooms.

The assistant acts with the permissions of the person talking to it, see [Assistant](/docs/assistant).

## API tokens

A token gives an external program access to the Valo API on your behalf.

1. In the **New token** block enter a **Name**
2. Choose the **Scope**. **read** only views, **control** also controls devices, scenes and automations at the resident level
3. Set **Valid for, days**, 0 or an empty field means never expires
4. Restrict the token to rooms if needed
5. Press **Create** and copy the token right away with the **Copy** button. It is shown once

The program passes the token in the `Authorization: Bearer <token>` header, the API address is `/api/v1`, for example `http://<hub address>:3100/api/v1/devices`. A token never gives more permissions than your role has. The table shows when the token was last used and until when it is valid. Delete an unneeded token with the **Delete** button. An administrator sees the tokens of all users, others only their own. Tokens can be created by a resident and above.

## Backups

A backup contains the home database (devices, rooms, dashboards, automations, scenes, settings), the list and settings of extensions and the Zigbee2MQTT data.

- **Back up now** starts a backup immediately. The daily backup is created automatically if it is turned on in the Home tab
- The table shows the time, the kind of backup (manual, scheduled, uploaded), the state and the size
- **Download** saves a `.tar.gz` file. Keep the backup outside the home
- **Delete** deletes the backup, the press must be confirmed
- The mark "second disk copy failed" means the duplicate of the backup on the second disk of the hub was not created

Restoring is available only to the owner.
1. If the backup is not in the list, press **Upload backup** and select the file. The archive is checked and appears in the list with the kind uploaded
2. Next to the backup press **Restore**, then **Confirm restore**
3. The database is replaced entirely in one transaction, then the core reads the retained broker messages again

The current state is lost on restore. If it may be needed, first create a fresh backup with the **Back up now** button.

The Zigbee2MQTT data from a backup is not brought back automatically on restore. It is needed only when replacing the hub or the stick, which is handled by the hub administrator.

## Errors

The log of errors of the core, its processes, Zigbee, extensions, the web server and users' browsers. Identical errors are grouped into one entry with a counter and the times of first and last occurrence. Expand an entry to see the source, details and the trace. New errors are highlighted, their number is shown by the **Errors** line at the bottom of the menu. **Refresh** reloads the list, **Clear** deletes all entries after a confirmation. Error data does not leave the hub.

## AI

Assistant settings.
- **Assistant enabled**
- **API address** of an OpenAI compatible service, OpenRouter by default
- **Model**. The **Load model list** button suggests names while typing
- **API key**. After saving the key is stored encrypted and is not shown, **Remove API key** erases it
- **Temperature**, **Steps per answer**, **Daily message limit** per user, 0 for no limit

**Save** applies the settings, **Test** sends the model a trial request and shows the answer or the error. How to use the assistant is described in [Assistant](/docs/assistant).

## Hub status

- **Versions** of the core, web client, Python, Mosquitto and Zigbee2MQTT
- **Services** with the state of the database, Redis, the MQTT and WebSocket processes, background tasks, the extension supervisor and Zigbee2MQTT. A red dot means the service does not respond
- **Resources** for an administrator. CPU load, memory, disk, database size and uptime
- **Core update** for an administrator. The installed version and whether a new one is available
