# Changelog

## 0.2.0

Built for Claude Code to run the whole move, after the official transfer.

- A Claude Code skill (`iphone2android skill`) with the full procedure, from what to do before the iPhone is wiped to a final audit
- `--json` on every command that reports something
- `suggest` and `find-app` find the Android version of each iPhone app through Apple's lookup and the Play Store search
- `audit` compares the iPhone with the phone (messages, calls, contacts, calendar, camera roll, apps)
- `appdata` finds the apps that keep data locally, copies it out, and reads account names from their settings
- `wallpaper` extracts the iPhone wallpaper (PosterBoard images, or cpbitmap converted to PNG) and opens Set as on the phone
- Widgets and App Library apps are read from the home screen, and the builder lists the widgets to place
- `screenshot` and `screen` show what is on the phone

## 0.1.0

First release.

- Open an encrypted iPhone backup, list its apps, extract the useful databases and an inventory
- Convert messages, call history, contacts, calendars and Safari bookmarks for Android and Google, with repair of a damaged message database
- Copy the camera roll, iMessage attachments and photo edits to the phone in batches
- Check app mappings against the Play Store, install free apps, remove preinstalled apps
- Read the iPhone home screen and rebuild it on the Android launcher (tested on ColorOS 16)
