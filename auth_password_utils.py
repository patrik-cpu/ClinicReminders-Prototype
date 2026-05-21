import base64
import hmac
import os
import re


PASSWORD_HASH_ALGORITHM = "pbkdf2_sha256"
PASSWORD_HASH_ITERATIONS = 260_000
PASSWORD_SALT_BYTES = 16
PASSWORD_MIN_LENGTH = 12
COMMON_PASSWORD_KEYS = {
    "123456789012",
    "admin123456",
    "changeme123456",
    "clinicreminders",
    "letmein123456",
    "password",
    "password123",
    "password1234",
    "password12345",
    "password123456",
    "qwerty123456",
    "welcome123456",
}


def password_hash_for_storage(password: str) -> str:
    """Return a salted password hash for new/changed clinic passwords."""
    salt = base64.urlsafe_b64encode(os.urandom(PASSWORD_SALT_BYTES)).decode("ascii").rstrip("=")
    digest = hashlib_pbkdf2_sha256(
        str(password or "").encode("utf-8"),
        salt.encode("utf-8"),
        PASSWORD_HASH_ITERATIONS,
    )
    digest_b64 = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return f"{PASSWORD_HASH_ALGORITHM}${PASSWORD_HASH_ITERATIONS}${salt}${digest_b64}"


def hashlib_pbkdf2_sha256(password: bytes, salt: bytes, iterations: int) -> bytes:
    import hashlib

    return hashlib.pbkdf2_hmac("sha256", password, salt, iterations)


def verify_password(password: str, stored_hash: str) -> bool:
    stored_hash = str(stored_hash or "").strip()
    if not stored_hash:
        return False

    parts = stored_hash.split("$")
    if len(parts) != 4 or parts[0] != PASSWORD_HASH_ALGORITHM:
        return False

    try:
        iterations = int(parts[1])
        salt = parts[2]
        expected = parts[3]
    except (TypeError, ValueError):
        return False

    digest = hashlib_pbkdf2_sha256(
        str(password or "").encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    )
    digest_b64 = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return hmac.compare_digest(digest_b64, expected)


def password_policy_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def password_policy_error(password: str, clinic_id: str = "") -> str:
    password_text = str(password or "")
    if len(password_text) < PASSWORD_MIN_LENGTH:
        return f"Password must be at least {PASSWORD_MIN_LENGTH} characters."

    password_key = password_policy_key(password_text)
    if not password_key:
        return "Password must include letters or numbers."

    for common_key in COMMON_PASSWORD_KEYS:
        if password_key == common_key or password_key.startswith(common_key):
            return "Choose a less common password."

    clinic_key = password_policy_key(clinic_id)
    if len(clinic_key) >= 4 and clinic_key in password_key:
        return "Password cannot include the clinic name."

    return ""


def validate_password_policy(password: str, clinic_id: str = "") -> None:
    error = password_policy_error(password, clinic_id)
    if error:
        raise ValueError(error)
