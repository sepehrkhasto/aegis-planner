# Third‑party notices

Aegis Planner is licensed under GPL‑3.0‑or‑later. It depends on, or bundles, the following.

| Component | Use | License |
|---|---|---|
| [PyQt6](https://www.riverbankcomputing.com/software/pyqt/) | UI toolkit (the reason the project is GPL) | GPL v3 |
| [Qt 6](https://www.qt.io/) | via PyQt6 | LGPL v3 / GPL |
| [cryptography](https://cryptography.io/) | AES‑256‑GCM, PBKDF2 | Apache‑2.0 / BSD |
| [NumPy](https://numpy.org/) | numeric helpers | BSD‑3‑Clause |
| [Vazirmatn](https://github.com/rastikerdar/vazirmatn) | Persian UI font (bundled) | SIL Open Font License 1.1 |
| [Inter](https://rsms.me/inter/) | Latin UI font (bundled) | SIL Open Font License 1.1 (`aegis_desktop/assets/fonts/Inter-OFL-LICENSE.txt`) |
| [Cormorant Garamond](https://github.com/CatharsisFonts/Cormorant) | Latin display font (bundled) | SIL Open Font License 1.1 (`aegis_desktop/assets/fonts/Cormorant-OFL-LICENSE.txt`) |

Build and test tooling (not shipped inside the program): PyInstaller (GPL with bootloader exception), Inno Setup, pytest, pytest‑qt, Pillow.
