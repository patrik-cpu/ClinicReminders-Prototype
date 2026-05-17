#!/usr/bin/env python3
"""Read-only live Google smoke checks for ClinicReminders.

This script intentionally performs no writes. It validates that the configured
service account can reach the expected Sheets/Drive resources before a release
or production smoke test.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
from pathlib import Path
from typing import Any

import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build


SETTINGS_SHEET_ID = "1JQgF268JyHZZRHg0V-p3chBu5jhANIMnUvkb7M0Fxs8"
DATASETS_FOLDER_ID = "1omuJfEmo_nuntr5uQBJhil_Q8ZNa2Lpr"
SETTINGS_WORKSHEET_NAME = "Clinic settings"

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]

SETTINGS_REQUIRED_COLUMNS = [
    "ClinicID",
    "PasswordHash",
    "SettingsJSON",
    "UpdatedAt",
    "DatasetFileId",
    "DatasetFileName",
    "DatasetUpdatedAt",
    "AuthProvider",
    "GoogleEmail",
    "GoogleSubject",
    "GoogleName",
    "Country",
    "CreatedAtGST",
    "LastLoginAtGST",
    "LastLoginProvider",
    "AccountStatus",
]

TRACKER_SHEETS = {
    "User tracker": [
        "ClinicID",
        "Country",
        "CreatedAtGST",
        "LastUpdatedAtGST",
        "LastLoginAtGST",
        "AccountStatus",
        "LastEvent",
    ],
    "Action tracker": [
        "DateTimeGST",
        "ActionedAtUTC",
        "ClinicID",
        "YourNameClinic",
        "Action",
        "ClientName",
        "AnimalNames",
        "Items",
        "ReminderDate",
        "DueDate",
        "ChargeDate",
        "Qty",
        "Days",
        "MessageCreated",
        "Source",
        "ReminderKey",
    ],
    "Dataset tracker": [
        "DateTimeGST",
        "Event",
        "Status",
        "ClinicID",
        "YourNameClinic",
        "FileName",
        "PMS",
        "Rows",
        "FromDate",
        "ToDate",
        "ReplaceOverlappingDates",
        "DriveFileId",
        "DriveFileName",
        "Message",
        "Source",
    ],
    "Settings audit": [
        "DateTimeGST",
        "ClinicID",
        "YourNameClinic",
        "Event",
        "Area",
        "Item",
        "Field",
        "OldValue",
        "NewValue",
        "Source",
    ],
    "Error tracker": [
        "DateTimeGST",
        "ClinicID",
        "YourNameClinic",
        "Event",
        "Stage",
        "ErrorType",
        "Message",
        "Source",
    ],
    "Performance tracker": [
        "DateTimeGST",
        "ClinicID",
        "YourNameClinic",
        "Event",
        "DurationMs",
        "Rows",
        "Status",
        "Message",
        "Source",
    ],
}


class SmokeFailure(RuntimeError):
    pass


def load_credentials_info(args: argparse.Namespace) -> tuple[dict[str, Any], str]:
    candidates = []
    if args.credentials_json:
        candidates.append(("explicit credentials file", Path(args.credentials_json)))
    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        candidates.append(("GOOGLE_APPLICATION_CREDENTIALS", Path(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])))
    candidates.append(("local google-credentials.json", Path("google-credentials.json")))

    for source, path in candidates:
        if path.exists():
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle), source

    secrets_path = Path(args.secrets_toml or ".streamlit/secrets.toml")
    if secrets_path.exists():
        with secrets_path.open("rb") as handle:
            secrets = tomllib.load(handle)
        service_account = secrets.get("gcp_service_account")
        if isinstance(service_account, dict):
            return dict(service_account), f"Streamlit secrets file {secrets_path}"

    raise SmokeFailure(
        "No Google service-account credentials found. Provide --credentials-json, "
        "set GOOGLE_APPLICATION_CREDENTIALS, create google-credentials.json, or add "
        "[gcp_service_account] to .streamlit/secrets.toml."
    )


def normalize(value: Any) -> str:
    return str(value or "").strip()


def build_credentials(args: argparse.Namespace) -> tuple[Credentials, str]:
    info, source = load_credentials_info(args)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return creds, source


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def check_header(actual: list[str], expected: list[str], sheet_title: str) -> None:
    missing = [column for column in expected if column not in actual]
    require(not missing, f"{sheet_title} is missing required columns: {missing}")


def row_to_record(headers: list[str], row: list[str]) -> dict[str, str]:
    return {
        header: row[index] if index < len(row) else ""
        for index, header in enumerate(headers)
    }


def check_settings_spreadsheet(creds: Credentials, clinic_id: str | None) -> dict[str, str] | None:
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(SETTINGS_SHEET_ID)
    worksheets = {worksheet.title: worksheet for worksheet in spreadsheet.worksheets()}

    print(f"OK Sheets: opened settings spreadsheet {SETTINGS_SHEET_ID}")
    require(SETTINGS_WORKSHEET_NAME in worksheets, f"Missing worksheet: {SETTINGS_WORKSHEET_NAME}")

    settings_sheet = worksheets[SETTINGS_WORKSHEET_NAME]
    settings_headers = settings_sheet.row_values(1)
    check_header(settings_headers, SETTINGS_REQUIRED_COLUMNS, SETTINGS_WORKSHEET_NAME)
    print(f"OK Sheets: {SETTINGS_WORKSHEET_NAME} has required columns")

    for title, expected_headers in TRACKER_SHEETS.items():
        require(title in worksheets, f"Missing tracker worksheet: {title}")
        actual_headers = worksheets[title].row_values(1)
        check_header(actual_headers, expected_headers, title)
    print(f"OK Sheets: {len(TRACKER_SHEETS)} tracker worksheets are present with expected columns")

    if not clinic_id:
        return None

    clinic_key = clinic_id.casefold()
    rows = settings_sheet.get_all_values()
    for row in rows[1:]:
        record = row_to_record(settings_headers, row)
        if normalize(record.get("ClinicID")).casefold() == clinic_key:
            print(f"OK Sheets: found ClinicID {clinic_id}")
            return record

    raise SmokeFailure(f"ClinicID not found in {SETTINGS_WORKSHEET_NAME}: {clinic_id}")


def check_drive(creds: Credentials, clinic_record: dict[str, str] | None, clinic_id: str | None) -> None:
    service = build("drive", "v3", credentials=creds, cache_discovery=False)
    folder = service.files().get(
        fileId=DATASETS_FOLDER_ID,
        fields="id,name,mimeType,trashed",
        supportsAllDrives=True,
    ).execute()
    require(not folder.get("trashed"), f"Datasets folder is trashed: {DATASETS_FOLDER_ID}")
    print(f"OK Drive: opened datasets folder {folder.get('name')} ({DATASETS_FOLDER_ID})")

    listed = service.files().list(
        q=f"'{DATASETS_FOLDER_ID}' in parents and trashed=false",
        fields="files(id,name,mimeType),nextPageToken",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
        pageSize=10,
    ).execute()
    print(f"OK Drive: listed {len(listed.get('files', []))} visible dataset folder children")

    if not clinic_record:
        return

    file_id = normalize(clinic_record.get("DatasetFileId"))
    file_name = normalize(clinic_record.get("DatasetFileName"))
    if not file_id:
        print(f"WARN Drive: ClinicID {clinic_id} has no DatasetFileId; skipping dataset file check")
        return

    file_meta = service.files().get(
        fileId=file_id,
        fields="id,name,mimeType,trashed,parents,appProperties,modifiedTime,size",
        supportsAllDrives=True,
    ).execute()
    require(not file_meta.get("trashed"), f"Dataset file is trashed: {file_id}")
    if file_name:
        require(
            normalize(file_meta.get("name")) == file_name,
            f"Dataset filename mismatch: sheet={file_name!r} drive={file_meta.get('name')!r}",
        )
    app_properties = file_meta.get("appProperties") or {}
    owner = normalize(app_properties.get("clinic_id"))
    if owner:
        require(owner.casefold() == normalize(clinic_id).casefold(), f"Drive appProperties clinic_id mismatch: {owner!r}")
    print(f"OK Drive: verified dataset file {file_meta.get('name')} ({file_id})")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run read-only live Google smoke checks.")
    parser.add_argument("--credentials-json", help="Path to a Google service-account JSON file.")
    parser.add_argument("--secrets-toml", help="Path to Streamlit secrets.toml with [gcp_service_account].")
    parser.add_argument("--clinic-id", help="Optional ClinicID whose dataset pointer should be checked.")
    parser.add_argument("--skip-drive", action="store_true", help="Only check the settings spreadsheet.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        creds, source = build_credentials(args)
        print(f"OK Credentials: loaded service-account credentials from {source}")
        clinic_record = check_settings_spreadsheet(creds, args.clinic_id)
        if args.skip_drive:
            print("SKIP Drive: --skip-drive was set")
        else:
            check_drive(creds, clinic_record, args.clinic_id)
        print("OK Live Google smoke check passed")
        return 0
    except Exception as exc:
        print(f"FAIL Live Google smoke check: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
