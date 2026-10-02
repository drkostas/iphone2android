---
name: iphone2android
description: Move someone from an iPhone to an Android phone so nothing is left behind. Use after (or instead of) the official transfer, when the user wants their messages, photos, contacts, apps, app data, accounts, wallpaper and exact home screen on the new phone. Drives the iphone2android command line and the phone over adb, checking every step, and calibrates itself to launchers it has not seen.
---

# Moving from an iPhone to Android with iphone2android

You run the whole move. `iphone2android` does the work and prints JSON with `--json`. You decide, check, and fix. The user does only what needs their hands or their consent, and you say exactly what and why.

This skill comes from a real migration (iPhone 14 Pro on iOS 26 to an OPPO Find X9 Pro on ColorOS 16) that took two days, most of them on the home screen. Every rule below exists because breaking it cost hours. Read the whole file before starting, and read `android/profiles/coloros-16.json` in the package, which holds the exact gesture recipes and the evidence for each.

Work in one folder for the whole move (for example `~/iphone-move`) and keep every file there.

## How to work

- Check every step against the source of truth before the next one. After each phase run `iphone2android --json audit`. After anything that changes the screen, take `iphone2android screenshot step.png` and read the image. A command saying "done" is not evidence.
- An empty screen dump means the phone is asleep, locked or disconnected. It never means the page is empty. If dumps come back empty, stop and reconnect (`adb kill-server; adb start-server`, or `adb connect` again for wireless). The original run lost an hour to an audit that read "missing" for every folder while the cable was loose.
- A black screenshot means the screen is off or locked. `screenshot` exits with code 5 and says so. Ask the user to wake the phone and enter their own PIN. Never type a PIN or a password, and never try to bypass the lock.
- Before any tap or drag, make sure the launcher is in front and nothing is drawn over it. `iphone2android --json launcher probe` reports `launcher_in_front` and `overlay`. The notification shade, a dialog or a keyboard over the launcher shows up in the screen dump, and its tiles are not icons.
- Never run two adb UI commands at once. A second `uiautomator dump` while a build runs breaks the gesture in flight. Wait for the build's log or exit, not on adb.
- The user's consent is needed for each of these, and you ask in plain words first. Accepting terms or a "Statement of Use", choosing a default app (SMS, launcher), changing the default SMS app through `cmd role`, signing in to any account, uninstalling anything that is not on the agreed list, and anything that costs money.
- Settings mined from app data (`appdata settings`) and the account list (`accounts`) contain the user's addresses. Keep that output on the computer. Never paste it anywhere else.

## Phase 0. Before the iPhone is wiped

These cannot come back from any backup, so do them while the iPhone works, and confirm each with the user.

- Authenticator codes (Google Authenticator has Transfer accounts, Microsoft Authenticator uses its cloud backup). Duo Mobile accounts are device-bound and must be reactivated through each organisation's Duo self-service or Duo Restore. Check every account opens on Android before going on.
- Passwords. The iCloud Keychain in a backup cannot be decrypted (every item is in a "ThisDeviceOnly" protection class and also sealed with the iPhone's Secure Enclave key, which never leaves the phone). The route that works is the Passwords app on a Mac signed in to the same Apple ID (File, Export All Passwords). The user does this themselves because it needs Touch ID. The CSV has the columns `Title,URL,Username,Password,Notes,OTPAuth`, which Google Password Manager imports as is (passwords.google.com, Settings, Import). In the real run 848 logins exported out of 8,492 keychain items. The rest are app tokens, Wi-Fi keys, certificates and device-bound items that Android cannot use anyway. Never print or read the passwords. Count rows and check the header only.
- Tickets and passes bound to the device (transit, ski passes, event tickets). Move them through each provider's account.
- Media that lives only inside an app (action cameras, video editors). Export it to the camera roll or to the provider's cloud.

## Phase 1. The official transfer

Run the official tool first. It moves a lot for little effort. In the setup wizard it is "Copy apps and data" (cable or the Switch to Android app on the iPhone). Some makers ship their own (OPPO and OnePlus Clone Phone, Samsung Smart Switch). In the real run it brought about two thirds of the apps and only part of the camera roll, so everything after this phase fills its gaps.

On ColorOS the backup and restore app (`com.coloros.backuprestore`) only offers Clone Phone. Its own backup screen fails with "Error type 3" and `adb backup` is removed in current platform tools, so there is no second official route.

## Phase 2. Connect, back up, extract

Enable developer options on the phone (Settings, About device, Version, tap Build number seven times), then USB debugging. Wireless debugging also works and survives the cable moving. If `adb devices` is empty while the phone shows in `system_profiler SPUSBDataType`, USB debugging is off.

The user makes an encrypted backup in Finder (or iTunes on Windows) with "Encrypt local backup" ticked. Only an encrypted backup has messages, call history, accounts and app data. The user types the backup password at the prompt, or sets `IPHONE_BACKUP_PASSWORD` in their own shell. Never store it in a file inside a repository.

```bash
iphone2android --json backups
iphone2android --json apps --names
iphone2android --json extract --inventory
iphone2android --json accounts
```

`extract` copies messages, call history, contacts, calendars, Safari bookmarks, Notes, WhatsApp, the home screen layout and the accounts database into `extracted/`. Apple sometimes saves the message database in the middle of a write, so the copy is a few kilobytes shorter than its header says and SQLite calls it malformed. `convert` repairs it.

## Phase 3. Audit what the official transfer missed

```bash
iphone2android --json audit --photos
```

- Messages. The phone's count is SMS plus MMS, because iMessages are restored as MMS. The original run first compared SMS alone (23,304) with the backup (25,645) and wrongly reported 91 percent. The real total was 50,685 (23,304 SMS and 27,381 MMS, about 1 percent duplicates).
- Calls. Android keeps at most 6,000 calls, so `calls_capped` true is the limit, not a gap.
- A null count means the phone refused the query, not zero.
- Photos are compared by file name. The official transfer renames some, so treat `missing_by_name` as an upper bound and look at the examples.

## Phase 4. Apps

```bash
iphone2android --json suggest --country <two letter country>
```

`suggest` names each iPhone app through Apple's lookup and searches the Play Store for it. A pick is made only when the Play Store title matches. For every app in `to_review`, read the candidates in `mapping.draft.json`, try `find-app` with other wordings (the brand name alone, the company name, the local spelling), open the candidate's Play Store page if unsure, and add the right package to `mapping.json` with the name the app has in the Android app drawer as `label`. In the real run about a quarter of the first guesses were wrong. Banks and local services rarely keep their iOS bundle id, some apps were renamed (NotebookLM became Gemini Notebook), and some have no Android version (keep a list with the closest alternative).

```bash
iphone2android --json verify mapping.json
iphone2android --json audit --mapping mapping.json
iphone2android --json install --mapping mapping.json
```

`install` opens each page in the Play Store app (named explicitly, because `market://` can open the phone maker's own store), waits for the Install button, presses it, and waits until `pm list packages` shows the app. Each install took 11 to 35 seconds. When the store is busy the button can take more than 25 seconds to appear and the app is reported `no-button`. Run `install` again for those before treating them as unavailable. Paid apps and apps that need a choice stay with the user.

Some apps have no launcher icon on Android (Gboard). Its icon activity is disabled by default and the shell is not allowed to enable it (`Shell cannot change component state`). The user enables it in Gboard's own settings, or it stays off the home screen.

Removing preinstalled apps the user does not want:

```bash
iphone2android --json debloat list.txt --keep-mapping mapping.json --dry-run
iphone2android --json debloat list.txt --keep-mapping mapping.json
```

Show the dry run to the user first. Removal is for the current user only and reversible with `adb shell cmd package install-existing <package>`. Some system parts refuse with `DELETE_FAILED_INTERNAL_ERROR` and fall back to being disabled. ColorOS ships some apps (Instagram, Temu, AliExpress) that the user may want to keep, so ask. In any shell loop over packages, add `</dev/null` to every adb command, or the first command reads the rest of the list and the loop runs once.

## Phase 5. Messages, calls, contacts, calendars

```bash
iphone2android --json convert --out android-import
```

Messages and calls go in with the free SMS Backup & Restore app (`com.riteshsahu.SMSBackupRestore`). The exact flow that worked on ColorOS 16:

1. Install it with `install`. Push the two XML files into a subfolder of shared storage, for example `adb shell mkdir -p /sdcard/SMSBackupRestore` and `adb push android-import/sms_backup.xml android-import/calls_backup.xml /sdcard/SMSBackupRestore/`.
2. Open the app. On first start it shows GET STARTED and then permission dialogs. Tapping Allow on them through the screen works, even though `pm grant` is blocked on ColorOS.
3. RESTORE, then YES to "Do you have existing backups", then LOCAL BACKUP LOCATION. The app looks in its default folder first and may say it found nothing. Choose the folder yourself. The system folder picker refuses the root of storage ("Can't use this folder"), so open the SMSBackupRestore folder, USE THIS FOLDER, ALLOW.
4. Turn on Messages and Call logs and press RESTORE. The app asks to become the default SMS app. That dialog ignores injected taps. With the user's consent, run `adb shell cmd role add-role-holder android.app.role.SMS com.riteshsahu.SMSBackupRestore`, then press RESTORE again.
5. Watch progress with `adb shell "content query --uri content://sms --projection _id | grep -c Row:"` every minute. 25,000 messages took about 22 minutes. The screen dump is empty while the progress dialog is up, which is normal.
6. Give the role back to the user's messaging app with `adb shell cmd role add-role-holder android.app.role.SMS com.google.android.apps.messaging` (or the app they use), and check with `adb shell cmd role get-role-holders android.app.role.SMS`.

Running the restore a second time skips most existing messages but adds a few duplicates (about 1 percent in the real run), so run it once.

Contacts. Check first whether Google already has them (the audit's contacts count). Otherwise import `contacts.vcf` in Google Contacts on the web.

Calendars. If the user's calendar accounts are already on the phone (Google, Exchange), the events come with them, and importing `calendar.ics` would duplicate them. Import only the calendars that were local to the iPhone.

## Phase 6. Photos and media

Ask whether the camera roll is already in Google Photos (or another cloud) before copying 50 GB. Ask about RAW files separately (DNG and CR2 were most of the size in the real run and the user had them elsewhere).

```bash
iphone2android --json media message-attachments photo-edits
iphone2android --json media camera-roll
```

iMessage attachments and edited versions of photos are never in Google Photos. File names that Android storage refuses (with `:` and similar) are renamed, because `adb push` otherwise fails for the folder while reporting success for the rest. Check the count on the phone afterwards with `adb shell "find /sdcard/Pictures/iPhone_Messages -type f | wc -l"`.

## Phase 7. App data and accounts

```bash
iphone2android --json appdata survey
iphone2android --json appdata settings <bundle> ...
iphone2android --json appdata extract <bundle> ... --push
```

Android apps cannot read their iPhone version's files, and without root nothing can be written into another app's private storage. So for each app with real local data, decide with the user between the app's own export and import, a dedicated migrator (WhatsApp chats need one), signing in when the data is in an account, and keeping a copy in `/sdcard/iPhoneMigration/AppData`. In the real run every app's data except caches (30,000 files, 3 GB) was pushed in 8 minutes as an archive for later.

Accounts. `accounts` lists what the iPhone was signed in to. Open the add-account screen for each Google account with `adb shell am start -a android.settings.ADD_ACCOUNT_SETTINGS --esa account_types com.google`, and let the user type and pass 2FA. Do not build the list from email addresses found in app data, which includes other people's addresses and typos.

## Phase 8. The home screen

This is the hard part. Read it all before touching the launcher.

### What the launcher allows

On ColorOS the launcher database, its content provider (`com.android.launcher.settings`, writes silently ignored), `pm clear`, shortcut pinning and the install-shortcut broadcast are all closed to adb without root, and the bootloader cannot be unlocked. So the home screen is changed through the screen only, the way a person does it, and every gesture has exact timings. Other launchers are similar or worse. Do not spend time on database or provider routes on a locked phone.

### 8.1 Read the target

```bash
iphone2android --json layout extracted/IconState.plist --mapping mapping.json > layout.json
iphone2android --json wallpaper extract --out wallpaper
```

`layout.json` has pages of apps, folders (`{"folder", "apps"}`) and widgets (`{"widget", "size"}`), the dock, and App Library apps under `library`. Each name is the app's name in the Android drawer, which can differ from its store name (Garmin Connect is "Connect", Google Fit is "Fit", myOdos is "My Odos"). Fix the labels before building, with `iphone2android launcher drawer <term>`. Show the layout and the wallpaper images to the user and agree on it.

### 8.2 Know the launcher

```bash
iphone2android --json launcher probe
```

If `profile` is `coloros-16`, the measured profile applies. If it says `generic` with `uncalibrated` true, calibrate first (section 8.7). `build` refuses an uncalibrated profile unless you pass `--force`.

### 8.3 Prepare

- Clear the pages. The real run removed icons one by one through long-press and Remove, at 13 to 22 seconds each, and the user found it far faster to do it himself (long-press an empty spot opens edit mode, where apps can be selected together and removed). Offer the user that choice.
- Remove widgets that are not in the target. A widget occupies cells, and a drop onto an occupied cell is moved to the next free cell, so folders silently fail to form. Long-press the widget (one-shell long press, 1.4 s), choose "Remove widget", then confirm. The confirm dialog appears up to a second later. Poll for it, and never press HOME before confirming, which cancels it.
- Turn Icon autofill OFF (`iphone2android autofill off`). With it on, the grid reflows the moment an icon is picked up, so merges and swaps become unpredictable.

### 8.4 Build

```bash
iphone2android --json build layout.json --state build.json --autofill
```

What it does, and why each step is shaped this way:

1. Pages are built from the last to the first.
2. Every app is dragged from the drawer search to the home screen. Such a drop always lands on the first page's first free cell, whatever page is showing, so everything is made on the first page and then carried.
3. Folders are made by dropping the second app onto the first, renamed (tap the folder, tap its name field, select all with `input keycombination 113 29`, type, BACK, because ENTER does not commit and any key event before typing closes the folder), and filled by dropping each further app from the drawer onto the folder.
4. A new folder is found by its position next to the seed icon. The launcher names new folders from their apps' category, and two folders can get the same name, so finding a folder by name picks the wrong one.
5. Each folder is opened again with a fresh navigation (HOME, then swipe to its page) and its contents compared with the target. After a folder closes, the launcher can jump to the first page, so reading folders in a row without navigating reads the wrong page. Extra apps (often apps the phone shipped with) are removed from inside the open folder, because no gesture can drag an app out of a folder.
6. Finished items are carried to their page. Carrying is a one-shell gesture. Press and hold 0.8 s, move to 70 percent of the width, move to the very edge and hold 0.9 s for each page to move, move back to the target cell, release. One hold is one page, and a longer hold overshoots. The drop is always on an empty cell, because a folder dropped onto a folder merges the two. This happened in the real run and mixed the Smart and Editing folders into Travel and Sports.
7. Each page is ordered by a selection sort that swaps one pair and then reads the screen again. With autofill off, dropping an icon on another icon's cell with a 2,000 ms drag swaps them. Several swaps from one reading never converged, because every move shifts the grid. If a swap creates a folder, the sort stops.
8. With `--autofill`, autofill is turned on at the end to close the gaps, and the result is checked again. In the real run this packed one page correctly and scrambled another, so always check after.

Progress is saved to `build.json` after every step. After an interruption, run the same command and it continues.

### 8.5 Check and fix

```bash
iphone2android --json check layout.json
iphone2android --json snapshot
```

Take a screenshot of every page and compare with the iPhone layout. Fixes for what the build reports:

- `not in the drawer`. Search the drawer with a shorter term (`iphone2android launcher drawer <term>` lists what the drawer shows), fix the label in `layout.json`, and run `build` again (finished steps are skipped).
- A folder missing an app. The build drops from the drawer onto the folder. If that keeps failing, carry the loose app to the folder's page and merge it with the hover gesture. Press and hold 0.9 s, move a little at 0.2 s, move halfway at 0.3 s, move over the folder and wait 0.5 s, stay 0.8 s more, release. This merged on the first try where 1,600 to 2,200 ms drags swapped instead. If the hover fails too, a 600 ms `draganddrop` onto the folder merged once. Open the folder afterwards to confirm, because a merge can be reported while the icon is still loose.
- A swap created a folder. Long-press the folder, Ungroup, confirm, then run `order`.
- An app in the wrong folder. Remove it inside the folder and add it to the right one.
- A carry failed. The build retries twice. If it still fails, check that the target page has a free cell and that nothing is drawn over the launcher.
- Order wrong after autofill. Turn autofill off, run `order`, turn it on, and check again.

### 8.6 Widgets, dock, wallpaper

Widgets are listed in `widgets_to_place`. The launcher's widget picker is reached by long-pressing an empty spot and choosing Widgets. The first time, ColorOS showed an OPPO "Shelf" Statement of Use, which is the user's to accept or decline. The picker lists apps A to Z with their widget counts. Its search field sent the text to the app drawer instead in the real run, so scroll the list. Pick the size closest to the iPhone one (small 2x2, medium 4x2, large 4x4) and drag it to its place, then screenshot. The original run never finished this step, so go slowly and verify each one.

The dock is changed by dragging an icon to the far right of the dock row (it appends) after removing what does not belong. Dropping onto an existing dock icon makes a folder in the dock. Dock icons recentre after every change, so read positions again before each drag.

Wallpaper. `wallpaper set wallpaper/<image>` copies the image and opens the phone's "Set as" screen. The user chooses the wallpaper app and home screen, lock screen or both. The parallax effect setting was not found on ColorOS 16, and its wallpaper app does not start from adb.

### 8.7 Calibrating a launcher that has no profile

Every launcher differs in timings, gestures and menu labels. Measure, never guess, and write the numbers into a profile.

Safety first. Run `snapshot` and keep the JSON, so the user's layout can be restored. Do the experiments on a new empty last page with throwaway icons (Calculator and Clock from the drawer), never on the user's folders.

Copy `android/profiles/generic.json` from the package to a new file, give it a `name` and a `match` (`launcher_package` from `probe`, and a ROM property and prefix if the maker sets one), then measure each item below. After each gesture read the screen (`screen` or `snapshot`) and a screenshot to see what really happened.

1. Grid. With a page holding at least one full row and one full column, `launcher probe` gives the icon centres (`icon_x`, `icon_y`). Write `first_col_x`, `col_step`, `first_row_y` and `row_step` as fractions of the screen, and the number of columns and rows. Some launchers state them in settings (`grid_setting` in the probe). Note the dock row (`dock_y`) and where the dock starts (`dock_top`).
2. Page swipe. Try a 250 ms horizontal swipe through the middle of the screen. The page changed if the dump differs. If not, try 200 and 300 ms. Avoid the bottom, where a search pill or the dock catches the swipe, and note what swiping right from the first page opens (on ColorOS the Discover feed).
3. HOME. Check that HOME always returns to the first page and closes folders and the drawer.
4. Drawer. Find the swipe that opens it and where its search field is. Check whether the field keeps the last query.
5. Long press. Try 1.0, 1.4 and 2.0 s with DOWN, sleep, UP in one `adb shell`. Separate adb calls and `input swipe x y x y` usually do not open the menu. Write down the menu labels for an app, an app inside a folder, a folder and a widget, and the confirm dialog's button labels and delay.
6. Drawer to home. Drop a drawer result on the home screen and see where it lands (ColorOS uses the first page's first free cell).
7. Making a folder. Drop a drawer result onto an icon at 1,200 and 1,800 ms. Note the folder's content description (ColorOS uses `Folder:<name>`) and how it is auto-named.
8. Renaming. Try BACK and ENTER to commit the name.
9. Merging a loose icon into a folder. Try the hover recipe and `draganddrop` at 600 and 1,800 ms, and open the folder each time to see which one really merged.
10. Swapping. With autofill off (or its equivalent), drop an icon onto another at 2,000 ms and see whether they swap, insert or merge.
11. Carrying to another page. Find the hold per page flip (start at 0.9 s) and check that a drop on an empty cell of the target page works.
12. Autofill. Find the setting's name and place (ColorOS has it in Home screen settings as Icon autofill) and what it does to order.
13. Widgets. How to reach the picker and how to place one.

Fill the profile, save it with `iphone2android launcher save-profile my-launcher.json`, and test it with a small layout (two loose apps and one folder of three) before the real build. If you can, contribute the profile back to the project.

## Phase 9. Final check

Run `iphone2android --json audit --mapping mapping.json --photos`, `check`, and a screenshot of every home screen page. Give the user a short list of what moved, what did not and why, and what is theirs to finish (sign-ins, 2FA, the default SMS app choice, any widgets left).

## Timings from the real run

| Step | Time |
|---|---|
| Installing 27 apps through the Play Store | about 10 minutes |
| Restoring 25,000 messages | about 22 minutes |
| Pushing 3 GB of app data | about 8 minutes |
| Media outside the photo library (5,400 files, 9.6 GB) | about 10 minutes |
| One screen dump | about 2 seconds (dump and read in one adb shell) |
| Removing one icon through its menu | 13 to 22 seconds |
