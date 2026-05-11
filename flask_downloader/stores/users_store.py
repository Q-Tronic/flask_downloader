import copy
import json
import os
import re
import time

from werkzeug.security import check_password_hash, generate_password_hash


VALID_USER_ROLES = ("admin", "user")
MIN_PASSWORD_LENGTH = 4


def normalize_username(value):
    text = re.sub(r"[^a-zA-Z0-9._-]+", "", str(value or "").strip().lower())
    if not text:
        raise ValueError("Login użytkownika nie może być pusty.")
    if len(text) < 3 or len(text) > 32:
        raise ValueError("Login użytkownika musi mieć od 3 do 32 znaków.")
    if text.startswith(".") or text.startswith("-") or text.startswith("_"):
        raise ValueError("Login użytkownika ma nieprawidłowy początek.")
    return text


def normalize_user_role(value):
    role = str(value or "").strip().lower()
    if role not in VALID_USER_ROLES:
        raise ValueError("Rola użytkownika musi być jedną z wartości: admin, user.")
    return role


def hash_user_password(password):
    text = str(password or "")
    if len(text) < MIN_PASSWORD_LENGTH:
        raise ValueError("Hasło użytkownika musi mieć co najmniej 4 znaki.")
    return generate_password_hash(text)


def sort_user_records(users):
    users.sort(key=lambda item: (0 if item.get("role") == "admin" else 1, item.get("username") or ""))
    return users


def default_user_record(username, default_admin_username, default_admin_password, role="admin", password_hash=""):
    normalized_username = normalize_username(username)
    normalized_role = normalize_user_role(role)
    return {
        "username": normalized_username,
        "role": normalized_role,
        "password_hash": str(password_hash or "").strip() or hash_user_password(
            default_admin_password if normalized_username == default_admin_username else "changeme"
        ),
        "enabled": True,
        "created_at": time.time(),
    }


def default_user_store(default_admin_username, default_admin_password):
    return {
        "schema_version": 1,
        "users": [
            default_user_record(default_admin_username, default_admin_username, default_admin_password, role="admin"),
        ],
    }


def normalize_user_entry(raw):
    if not isinstance(raw, dict):
        return None
    try:
        username = normalize_username(raw.get("username"))
        role = normalize_user_role(raw.get("role") or "user")
    except Exception:
        return None

    password_hash = str(raw.get("password_hash") or "").strip()
    if not password_hash:
        return None

    try:
        created_at = float(raw.get("created_at") or 0.0)
    except Exception:
        created_at = 0.0

    return {
        "username": username,
        "role": role,
        "password_hash": password_hash,
        "enabled": bool(raw.get("enabled", True)),
        "created_at": created_at or time.time(),
    }


def load_user_store(users_file, default_admin_username, default_admin_password):
    store = default_user_store(default_admin_username, default_admin_password)
    changed = False

    try:
        if os.path.isfile(users_file):
            with open(users_file, "r", encoding="utf-8") as fh:
                raw = json.load(fh) or {}

            if isinstance(raw, dict):
                seen = set()
                users = []
                for item in raw.get("users") or []:
                    normalized = normalize_user_entry(item)
                    if not normalized:
                        continue
                    if normalized["username"] in seen:
                        continue
                    seen.add(normalized["username"])
                    users.append(normalized)

                if users:
                    store["users"] = sort_user_records(users)
                    store["schema_version"] = int(raw.get("schema_version") or 1)
    except Exception:
        store = default_user_store(default_admin_username, default_admin_password)
        changed = True

    admin_entry = None
    for item in store["users"]:
        if item["username"] == default_admin_username:
            admin_entry = item
            break
    if admin_entry is None:
        store["users"].insert(
            0,
            default_user_record(
                default_admin_username,
                default_admin_username,
                default_admin_password,
                role="admin",
            ),
        )
        changed = True
    else:
        if admin_entry.get("role") != "admin":
            admin_entry["role"] = "admin"
            changed = True
        if not admin_entry.get("enabled", True):
            admin_entry["enabled"] = True
            changed = True

    sort_user_records(store["users"])

    if changed or not os.path.isfile(users_file):
        write_user_store(users_file, store)

    return store


def write_user_store(users_file, store):
    with open(users_file, "w", encoding="utf-8") as fh:
        json.dump(store, fh, ensure_ascii=False, indent=2)


def get_users_snapshot(store):
    return copy.deepcopy(list(store.get("users") or []))


def get_user_by_username(store, username):
    normalized_username = normalize_username(username)
    for item in store.get("users") or []:
        if item.get("username") == normalized_username:
            return copy.deepcopy(item)
    return None


def verify_user_credentials(store, username, password):
    try:
        normalized_username = normalize_username(username)
    except Exception:
        return None

    user = get_user_by_username(store, normalized_username)
    if not user or not user.get("enabled", True):
        return None
    if not check_password_hash(str(user.get("password_hash") or ""), str(password or "")):
        return None
    return user


def create_user_account(store, username, password, role):
    normalized_username = normalize_username(username)
    normalized_role = normalize_user_role(role)
    password_hash = hash_user_password(password)

    for item in store.get("users") or []:
        if item.get("username") == normalized_username:
            raise ValueError("Użytkownik o takim loginie już istnieje.")

    user = {
        "username": normalized_username,
        "role": normalized_role,
        "password_hash": password_hash,
        "enabled": True,
        "created_at": time.time(),
    }
    store.setdefault("users", []).append(user)
    sort_user_records(store["users"])
    return copy.deepcopy(user)


def update_user_password(store, username, new_password):
    normalized_username = normalize_username(username)
    password_hash = hash_user_password(new_password)

    for item in store.get("users") or []:
        if item.get("username") != normalized_username:
            continue
        item["password_hash"] = password_hash
        return copy.deepcopy(item)
    raise ValueError("Nie znaleziono użytkownika do zmiany hasła.")
