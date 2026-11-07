# Assistant

The assistant is a chat with a language model that knows your home. It answers questions about the state of the home and about how Valo works, builds dashboards, sets up rooms and suggests actions. The assistant acts only with your own rights and never goes beyond them.

## What the assistant can do

Reading, runs immediately

- home overview, device list, device state and reading history
- rooms, dashboards, the widget catalog, scenes, automations and automation blocks, extensions
- recent log events
- searching and reading this documentation and extension guides
- for administrators, Zigbee network details and read only access to the core source code

Changes, run immediately and can be reverted with **Undo**

- creating a dashboard, changing a dashboard and adding widgets to it
- for administrators, creating and changing a room, assigning devices to rooms and renaming a device

Actions that need confirmation, run only after **Execute**

- a device command, for example turning on a light or setting a setpoint
- applying a scene, deleting a dashboard
- creating, changing, deleting and manually running an automation
- for administrators, deleting a room, installing an extension from the catalog and opening the Zigbee network for pairing

## How to use it

1. Open **Assistant** in the menu
2. Type a question or task in **Message the assistant** and press **Send** or Enter. Shift and Enter add a new line
3. An empty chat offers ready examples, for example **What is happening at home now?** or **Make a dashboard with a plug voltage chart**
4. While the assistant works you can see that it is thinking and which data it requests, for example Home overview or Devices. **Stop** interrupts the answer

## Action cards

Every change and every action that needs confirmation is shown as a card with a short summary and a status.

- **awaiting confirmation** with the **Decline** and **Execute** buttons
- **done**, revertible actions have an **Undo** button, created dashboards and devices have an **Open** link
- **declined**, **undone** or **failed** with the reason

Undo restores the previous state, for example it deletes a created dashboard or brings back the old device name. Device commands, scenes and automations cannot be undone, which is why they ask for confirmation first.

## Rights

The assistant takes the role and restrictions of the user writing in the chat.

- a guest can only ask questions, the assistant changes nothing on their behalf
- a resident can ask for dashboards, device commands, scenes and manual automation runs
- an administrator can also ask for rooms, device assignment, renaming, creating and changing automations, installing extensions and pairing
- a user limited to some rooms sees only those rooms through the assistant and cannot work with automations

An API token with read scope cannot write to the chat. An administrator can set a daily message limit per user.

## Chat list

Your chats are listed on the left, each user has their own list. **New chat** opens an empty chat, its title comes from the first message. Each chat has **Rename** and **Delete** buttons, delete has to be pressed twice. A chat where the assistant is still replying is marked **answering**.

## Setup

The assistant needs an API key of a model provider. An administrator sets it in System, tab **AI**.

- **Assistant enabled** turns the assistant on and off for everyone
- **API address** points to OpenRouter or a compatible API
- **Model** is picked from the list after **Load model list**
- **API key** is stored encrypted and is not shown after saving
- **Temperature**, **Steps per answer** and **Daily message limit** tune the behavior
- **Test** sends a trial request to the model

Until a key and a model are set, the chat shows **The assistant is not configured** and a **Set up** link for administrators. In the demo environment the assistant runs on a demo model without a key. More about the AI tab in [System](/docs/system).
