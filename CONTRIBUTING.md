# Contributing

Issues and pull requests are welcome, especially support for more launchers and more iPhone databases.

```bash
python -m venv .venv && .venv/bin/pip install -e '.[test]'
.venv/bin/pytest
```

Please add a test for every change in behaviour. The tests never need a real iPhone or Android phone. Use the synthetic databases in `tests/test_convert_layout.py`, the fake decryptor in `tests/test_backup_media.py`, and the fake `adb` and simulated home screen in `tests/test_android.py`.

If you add support for a launcher, please say which phone and which launcher version you tested on.
