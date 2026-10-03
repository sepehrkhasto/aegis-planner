# Security Policy

## Supported versions

Only the latest release receives security fixes.

## Reporting a vulnerability

Please **do not open a public issue** for a security problem.

Use GitHub's private reporting: open the repository's **Security** tab → **Report a vulnerability**. Include the affected version, the steps to reproduce, and the impact you believe it has. You will get an acknowledgement within a few days. Once a fix is released you are welcome to be credited in the changelog.

Please never attach a real vault, password or recovery key to a report. A synthetic vault that reproduces the problem is enough.

## What the application protects

- Vault contents (tasks, notes, habits, goals, settings) at rest, in the vault file and in every backup, against someone who obtains the files but not the master password.
- Integrity of the ciphertext: AES‑256‑GCM authenticates every vault, so modified or truncated files are detected and rejected.
- Hostile or malformed vault/backup files must never crash the application, execute code, or write outside the data directory.

## Design

- Key derivation: PBKDF2‑HMAC‑SHA256, 600,000 iterations, 16‑byte random salt. Imported files whose iteration count is outside the allowed range are rejected.
- Data key: a random 256‑bit key encrypts the vault with AES‑256‑GCM and a fresh 12‑byte random nonce for each save. The master password (and optionally a recovery key) wraps this key.
- Changing the password rotates the data key and re‑encrypts the vault and the backups.
- Files are written atomically (temporary file, `fsync`, rename).
- The master password and keys are not written to disk, to the log, or to preferences.
- Network: none by default. An optional update check (off by default) sends one HTTPS request to the public GitHub API with a fixed `User-Agent`; it carries no vault data or identifier and the response is limited to a version tag and a link.

## Known limits (please read)

- **Forgotten password.** With no recovery key the data cannot be recovered. This is intentional.
- **A compromised computer.** Malware, a keylogger, or someone with access to the unlocked session can read the data. Memory is not scrubbed reliably (Python/Qt copy buffers); lock the vault when you leave.
- **Rollback.** The header (including the revision number) is not part of the authenticated data, so someone who can replace files could substitute an older, valid copy of the vault or a backup.
- **Metadata.** File names, sizes, modification times and the number of backups are visible to anyone who can see the folder.
- **Sync tools.** Putting the data folder in a cloud‑sync folder works, but two running instances or a sync conflict can overwrite newer data with older data. Use a single instance and keep backups.
- **Unsigned binaries.** Release executables are not code‑signed; verify the SHA‑256 shown on the release page.

## Dependencies

Cryptography is provided by the `cryptography` package (OpenSSL); the UI by PyQt6. Report issues in those projects to their maintainers.
