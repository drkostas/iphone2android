# iphone2android

iphone2android moves your data from an iPhone to an Android phone using an encrypted iPhone backup on your computer and `adb` to the new phone. It converts messages, call history, contacts, calendars and bookmarks into formats Android and Google import, copies photos and the media Google Photos does not keep, installs your apps, and rebuilds your iPhone home screen on the Android launcher.

## Before you wipe the iPhone

Some things cannot be recovered from any backup, so move them while the iPhone still works.

- Authenticator apps. Export the accounts from the iPhone app (Google Authenticator has Transfer accounts) and scan them on Android.
- Passwords in the iCloud Keychain. A backup cannot decrypt them, because every item is also sealed with a key that never leaves the iPhone. Use a password manager or a Mac signed in to the same Apple ID to export them.
- Tickets and passes bound to the device (transit tickets, ski passes). Move them through the provider's account.
- Footage that exists only on the phone in apps such as action-camera apps.

## Install

```bash
pip install iphone2android
```

You also need `adb` (`brew install android-platform-tools` on macOS) with USB debugging on in the phone's developer options.

## 1. Make an encrypted backup

In Finder (or iTunes on Windows) select the iPhone, choose "Back up all of the data on your iPhone to this Mac", tick "Encrypt local backup" and back up. Only an encrypted backup contains messages, call history and app data.

```bash
iphone2android backups          # list the backups on this computer
iphone2android apps             # the apps that were installed (no password needed)
```

On Windows, pass `--backup-root "%APPDATA%\Apple Computer\MobileSync\Backup"`.

## 2. Extract and convert

```bash
iphone2android extract --inventory      # asks for the backup password (or set IPHONE_BACKUP_PASSWORD)
iphone2android convert --out android-import
```

| File | Import it with |
|---|---|
| `sms_backup.xml`, `calls_backup.xml` | the SMS Backup & Restore app on the phone (Restore, then choose the file) |
| `contacts.vcf` | Google Contacts (Import) |
| `calendar.ics` | Google Calendar (Settings, Import & export) |
| `safari_bookmarks.html` | Chrome on a computer (Bookmarks, Import), then sync |

Apple sometimes saves the message database in the middle of a write, so the backup copy is shorter than its own header says and SQLite refuses to open it. `convert` corrects the header in a copy and reads what is there. If that is not enough and your `sqlite3` has the `.recover` command, it uses that instead.

WhatsApp chats (`ChatStorage.sqlite`) need a dedicated iOS to Android WhatsApp migrator, and Apple Notes (`NoteStore.sqlite`) need an Apple Notes parser. `extract` copies both out for those tools.

## 3. Photos and media

```bash
iphone2android media camera-roll message-attachments photo-edits
```

Files are decrypted in batches, pushed to the phone and deleted, so the computer does not need room for the whole camera roll. If your photos are already in Google Photos, skip `camera-roll`. The other two are never in Google Photos (iMessage attachments, and the edited versions of photos).

## 4. Apps

Write a mapping from iPhone bundle ids to Android packages, using `iphone2android apps` for the list. `label` is the app's name in the Android app drawer.

```json
{"net.whatsapp.WhatsApp": {"package": "com.whatsapp", "label": "WhatsApp"}}
```

Check every package before installing. Guessed package names are often wrong, because the Android package of a bank or a local app rarely matches its iOS bundle id.

```bash
iphone2android verify mapping.json
iphone2android install --mapping mapping.json
```

`install` opens each app's page in the Play Store app and presses Install, so it works for free apps only. Each app is checked as installed before the next one starts.

To remove preinstalled apps you do not want, list them in a file and run `iphone2android debloat list.txt --keep-mapping mapping.json --dry-run`, then again without `--dry-run`. Apps are removed for the current user only, and `adb shell cmd package install-existing <package>` brings one back.

## 5. Home screen

```bash
iphone2android extract                                   # also copies IconState.plist
iphone2android layout extracted/IconState.plist --mapping mapping.json > layout.json
iphone2android build layout.json --state build.json --autofill
```

`layout.json` lists pages of apps and folders by their drawer name, which you can edit before building. The builder adds each app from the app drawer search, reads the screen again after every drop, and saves its progress so an interrupted build continues where it stopped. Then it puts each page in order one swap at a time, and finally turns the launcher's icon autofill on to close the gaps. Do not touch the phone while it runs.

Many launchers do not let adb change the layout directly (on ColorOS the launcher database and shortcut pinning are closed without root), so the builder moves icons through the screen the way a person does. It is tested on ColorOS 16 (OPPO Find X9 Pro). Other launchers name their menus differently and may need changes in `android/launcher.py`.

## Limits

- Only an encrypted backup has messages and app data.
- Keychain passwords cannot be extracted (see above).
- Paid apps are not installed.
- The home screen builder is tested on one launcher.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -e '.[test]'
.venv/bin/pytest
```

The tests use synthetic databases, a fake decryptor, a fake `adb` and a simulated home screen, so they need no iPhone and no Android phone.

## License

MIT. Backup decryption uses [iOSbackup](https://github.com/avibrazil/iOSbackup) (LGPL).
