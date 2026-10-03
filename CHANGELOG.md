# Changelog

All notable changes. Versions follow `MAJOR.MINOR.PATCH`.

## 2.11.10

- Goals and habits open in a full page, like tasks (`Ctrl+Enter` saves; unsaved changes are confirmed).
- New time picker (hour/minute grid, 5‑minute step, mouse wheel and keyboard) replaces the old time boxes.
- Optional update check (Settings → About), **off by default**; once a day it asks the public GitHub API for the latest version tag. No vault data is sent.
- Released as free software under GPL‑3.0‑or‑later; added README (English and Persian), SECURITY, CONTRIBUTING, build guide and CI workflows.
- Code audit fixes: out‑of‑range years in quick add, “12:30 شب”, recurring task with an invalid stored date, duplicate IDs when migrating legacy notes, damaged‑backup handling on restore, pinned‑backup name collision, malformed certificate dates, export to a read‑only location.

## 2.5.0

- Task editor as a full page; Help section with searchable FAQ; calendar date picker; “next task” band on Today; appearance settings regrouped with live preview.

## 2.4.0

- Chip filters and status tabs; reworked task/habit/goal sheets; visual polish.

## 2.0 – 2.3

- Data‑key rotation on password change, recurring‑task horizon, background saving for large vaults, calendar printing, cinematic opening, sixteen themes, sunset‑aware automatic theme.

## 1.x

- Initial Windows release: encrypted vault, Jalali calendar, tasks, kanban, notes, habits, goals, focus timer, reports, backups, tour and “What's new”.
