# Changelog

## 0.3.0

The home screen builder rebuilt from what a real migration on ColorOS 16 learned, and a much more detailed skill.

- Launcher profiles as data (`android/profiles`), with every timing, gesture recipe, label and hazard, and the evidence for each. The ColorOS 16 profile is measured. Other launchers start from an uncalibrated generic profile, and `build` refuses to run on it without `--force`
- The builder now makes everything on the first page (where drawer drops land), carries items with an edge hold onto empty cells, finds new folders by position, checks every folder by opening it, removes extras from inside folders, and resumes after interruptions
- `launcher probe`, `launcher drawer`, `launcher profiles` and `launcher save-profile` for calibrating a new launcher
- `check` and `snapshot` compare and read the whole home screen
- `accounts` lists what the iPhone was signed in to
- Screen reading ignores the notification shade and dialogs drawn over the launcher, and an empty dump is an error, not an empty page
- `screenshot` reports a black picture (screen off or locked) instead of returning it
- The audit counts SMS plus MMS (iMessages restore as MMS) and recognises the 6,000-call limit
- File names Android storage refuses are renamed before pushing

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
