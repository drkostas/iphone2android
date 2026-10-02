---
name: iphone2android
description: Move someone from an iPhone to an Android phone so nothing is left behind. Use after (or instead of) the official transfer, when the user wants their messages, photos, contacts, apps, app data, wallpaper and exact home screen on the new phone. Drives the iphone2android command line and the phone over adb, checking every step.
---

# Moving from an iPhone to Android with iphone2android

You run the whole move for the user. The `iphone2android` command does the work and prints JSON with `--json`. You decide, check and fix. The user only does what needs their hands or their consent, and you say exactly what and why.

Work in one folder for the whole move, for example `~/iphone-move`, and keep every file there.

## Rules

- Check every step against the source of truth before moving on. Run `iphone2android --json audit` after each phase, and take a screenshot (`iphone2android screenshot out.png`, then read the image) after anything that changes the phone's screen.
- Never press "Agree", "Accept", "Set as default" or a paid "Buy" button for the user. Show them the screen and let them choose.
- Never type a password. The backup password comes from the user (they type it at the prompt, or set `IPHONE_BACKUP_PASSWORD` themselves).
- Settings mined from app data (`appdata settings`) can hold email addresses and account names. Keep that output on the computer.
- Before any tap or drag, bring the right app to the front and confirm it with `adb shell dumpsys activity activities | grep topResumedActivity`. A notification or a sleeping screen changes what a tap hits.
- Do not run two adb UI commands at once. A second `uiautomator dump` during a build breaks the build.

## Phase 0. Before the iPhone is wiped

Ask the user to do these while the iPhone still works, because no backup can bring them back.

- Authenticator apps. Export from the iPhone app (Google Authenticator has Transfer accounts) and scan on Android. Check every account works before going on.
- Passwords in the iCloud Keychain cannot be read from a backup (each item is sealed with a key that never leaves the iPhone). Export them with a password manager, or from a Mac signed in to the same Apple ID.
- Tickets and passes bound to the device (transit, ski passes, event tickets). Move them through each provider's account.
- Footage that only exists inside an app (action cameras, video editors). Export it to the camera roll first.

## Phase 1. The official transfer

Start with the official tool, because it moves a lot with little risk. On most phones it is in the setup wizard ("Copy apps and data" from an iPhone, by cable or by the Switch to Android app on the iPhone). Some makers ship their own (OPPO and OnePlus Clone Phone, Samsung Smart Switch). Let it finish, then treat everything after this as filling its gaps.

## Phase 2. The backup

The user makes an encrypted backup in Finder (or iTunes on Windows) with "Encrypt local backup" ticked. Only an encrypted backup has messages, call history and app data.

```bash
iphone2android --json backups
iphone2android --json apps --names
iphone2android --json extract --inventory
```

`extract` copies the message, call, contacts, calendar, Safari, Notes, WhatsApp and home screen databases into `extracted/`.

## Phase 3. Audit what the official transfer missed

```bash
iphone2android --json audit --photos
```

Compare the counts (messages, calls, contacts, calendar events, camera roll names) and list the gaps for the user. A null count means the phone would not tell, not zero.

## Phase 4. Apps

```bash
iphone2android --json suggest            # mapping.json (sure) and mapping.draft.json (candidates)
```

For every app in `to_review`, read its candidates in `mapping.draft.json`, use `iphone2android --json find-app "<name>"` with other wordings, and add the right package to `mapping.json`. Apps with no Android version go in a list for the user, with the closest alternative if one exists. Guessed packages are often wrong (banks and local apps rarely match their iOS bundle id), so always run

```bash
iphone2android --json verify mapping.json
iphone2android --json audit --mapping mapping.json      # which mapped apps are still missing
iphone2android --json install --mapping mapping.json
```

`install` presses Install on each free app's Play Store page and waits until the app is installed. Paid apps and apps that need a choice are left for the user. If the phone came with apps the user does not want, list them in a file and run `debloat` with `--dry-run` first, then for real (it is reversible with `cmd package install-existing`).

## Phase 5. Messages, calls, contacts, calendars, bookmarks

```bash
iphone2android --json convert --out android-import
```

- Messages and calls. Install SMS Backup & Restore, push the two XML files with `adb push android-import/sms_backup.xml android-import/calls_backup.xml /sdcard/Download/`, open the app and restore from that folder. The app asks to become the default SMS app during the restore. That choice is the user's.
- Contacts. `contacts.vcf` into Google Contacts (Import), or push it and open it on the phone.
- Calendars. `calendar.ics` into Google Calendar on the web (Settings, Import & export).
- Bookmarks. `safari_bookmarks.html` into Chrome on a computer, then sync.

Run the audit again and compare the counts.

## Phase 6. Photos and media

```bash
iphone2android --json media message-attachments photo-edits
iphone2android --json media camera-roll          # only if the audit shows photos missing
```

iMessage attachments and photo edits are never in Google Photos. Check the counts on the phone with `adb shell find /sdcard/Pictures/iPhone_Messages -type f | wc -l`.

## Phase 7. App data

```bash
iphone2android --json appdata survey                       # apps that keep real data locally, biggest first
iphone2android --json appdata settings <bundle> ...        # account names to set each app up again
iphone2android --json appdata extract <bundle> ... --push  # copy the data to /sdcard/iPhoneMigration/AppData
```

Most Android apps cannot read their iPhone version's files. For each app with real data, decide with the user between the app's own export and import, a dedicated migrator (WhatsApp chats need one), and keeping a copy. Apps whose data is in the cloud only need signing in.

## Phase 8. Home screen

```bash
iphone2android --json layout extracted/IconState.plist --mapping mapping.json > layout.json
iphone2android --json wallpaper extract --out wallpaper
```

Show the user `layout.json` and the wallpaper images, and adjust anything they want different.

```bash
iphone2android --json build layout.json --state build.json --autofill
```

The builder adds each app from the drawer search, reads the screen again after every drop, and saves progress to `build.json`, so after an interruption you run the same command and it continues. It turns Icon autofill off while building and on at the end. After every page, take a screenshot and compare it with the layout.

Widgets are reported in `widgets_to_place`. Place each one through the launcher. Long-press an empty spot, choose Widgets, search the app, pick the size closest to the iPhone one (small 2x2, medium 4x2, large 4x4), and drag it to its place. Screenshot after each.

```bash
iphone2android --json wallpaper set wallpaper/<chosen image>
```

This opens the phone's "Set as" screen. Choose the wallpaper app and home screen, lock screen or both, with the user's agreement.

## Phase 9. Final check

Run `iphone2android --json audit --mapping mapping.json --photos`, take a screenshot of each home screen page, and give the user a short list of what moved, what did not, and what is theirs to finish.

## Launcher notes (tested on ColorOS 16)

- The launcher database, its content provider and shortcut pinning are closed to adb without root, so the home screen is changed through the screen only.
- `input draganddrop` with about 600 ms merges an icon into a folder. A long hover opens the folder instead.
- A folder is renamed by tapping its title, selecting all (`input keycombination 113 29`), typing, and pressing BACK. ENTER does not commit the name.
- Icons cannot be dragged out of a folder. Long-press the icon inside the open folder and choose Remove.
- A new page is made by dragging an icon to the right edge with a 3 second hold.
- Swiping left from the first page opens the feed, not a page. HOME always returns to the first page.
- Search in the app drawer matches substrings. Check the result before dragging ("WHAT" matches WhatsApp).
- Widgets take cells. A drop onto an occupied cell moves to the next free one, so clear widgets before laying out a page.

## adb notes

- `adb shell` reads stdin. In a shell `while read` loop add `</dev/null`, or the first command eats the rest of the list.
- `pm grant`, `appops set` and `pm clear` on system apps are refused for the shell on ColorOS. Permissions are granted on the phone's screen.
- Run the Play Store explicitly (`-p com.android.vending`). `market://` can open a maker's own store instead.
