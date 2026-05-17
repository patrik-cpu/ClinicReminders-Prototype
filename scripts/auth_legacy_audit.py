#!/usr/bin/env python3
"""Read-only audit for legacy authentication data in the settings sheet."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from typing import Any

try:
    from scripts import live_google_smoke_check as google_smoke
except ModuleNotFoundError:
    import live_google_smoke_check as google_smoke

import gspread


PBKDF2_PREFIX = "pbkdf2_sha256$"
MD5_HEX_RE = re.compile(r"^[a-fA-F0-9]{32}$")


@dataclass
class LegacyAuthAudit:
    total_rows: int = 0
    pbkdf2_password_hashes: int = 0
    legacy_md5_password_hashes: int = 0
    blank_password_hashes: int = 0
    unknown_password_hashes: int = 0
    plain_password_nonblank: int = 0
    risky_clinic_ids: set[str] = field(default_factory=set)

    @property
    def has_risk(self) -> bool:
        return (
            self.legacy_md5_password_hashes > 0
            or self.unknown_password_hashes > 0
            or self.plain_password_nonblank > 0
        )


def classify_password_hash(stored_hash: Any) -> str:
    value = google_smoke.normalize(stored_hash)
    if not value:
        return "blank"
    if value.startswith(PBKDF2_PREFIX):
        return "pbkdf2"
    if MD5_HEX_RE.fullmatch(value):
        return "legacy_md5"
    return "unknown"


def audit_settings_records(records: list[dict[str, Any]]) -> LegacyAuthAudit:
    audit = LegacyAuthAudit(total_rows=len(records))
    for record in records:
        clinic_id = google_smoke.normalize(record.get("ClinicID")) or "<missing ClinicID>"
        hash_kind = classify_password_hash(record.get("PasswordHash"))

        if hash_kind == "pbkdf2":
            audit.pbkdf2_password_hashes += 1
        elif hash_kind == "legacy_md5":
            audit.legacy_md5_password_hashes += 1
            audit.risky_clinic_ids.add(clinic_id)
        elif hash_kind == "blank":
            audit.blank_password_hashes += 1
        else:
            audit.unknown_password_hashes += 1
            audit.risky_clinic_ids.add(clinic_id)

        if google_smoke.normalize(record.get("PlainPassword")):
            audit.plain_password_nonblank += 1
            audit.risky_clinic_ids.add(clinic_id)

    return audit


def load_settings_records(args: argparse.Namespace) -> list[dict[str, str]]:
    google_smoke.apply_resource_config(args)
    creds, source = google_smoke.build_credentials(args)
    print(f"OK Credentials: loaded service-account credentials from {source}")
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(google_smoke.SETTINGS_SHEET_ID)
    worksheet = spreadsheet.worksheet(google_smoke.SETTINGS_WORKSHEET_NAME)
    rows = worksheet.get_all_values()
    if not rows:
        return []

    headers = rows[0]
    return [google_smoke.row_to_record(headers, row) for row in rows[1:]]


def print_audit(audit: LegacyAuthAudit, show_clinics: bool) -> None:
    print(f"OK Auth audit: inspected {audit.total_rows} settings rows")
    print(f"OK Auth audit: pbkdf2 password hashes: {audit.pbkdf2_password_hashes}")
    print(f"WARN Auth audit: legacy MD5 password hashes: {audit.legacy_md5_password_hashes}")
    print(f"WARN Auth audit: unknown password hashes: {audit.unknown_password_hashes}")
    print(f"WARN Auth audit: nonblank PlainPassword cells: {audit.plain_password_nonblank}")
    print(f"OK Auth audit: blank password hashes: {audit.blank_password_hashes}")

    if show_clinics and audit.risky_clinic_ids:
        print("WARN Auth audit: clinics needing auth cleanup:")
        for clinic_id in sorted(audit.risky_clinic_ids):
            print(f"  - {clinic_id}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit live settings rows for legacy authentication data.")
    parser.add_argument("--credentials-json", help="Path to a Google service-account JSON file.")
    parser.add_argument("--secrets-toml", help="Path to Streamlit secrets.toml with [gcp_service_account].")
    parser.add_argument("--show-clinics", action="store_true", help="Print ClinicIDs for rows needing cleanup.")
    parser.add_argument("--fail-on-risk", action="store_true", help="Exit nonzero if legacy auth data is present.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        audit = audit_settings_records(load_settings_records(args))
        print_audit(audit, args.show_clinics)
        if args.fail_on_risk and audit.has_risk:
            print("FAIL Auth audit: legacy authentication data remains", file=sys.stderr)
            return 1
        print("OK Auth audit passed")
        return 0
    except Exception as exc:
        print(f"FAIL Auth audit: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
