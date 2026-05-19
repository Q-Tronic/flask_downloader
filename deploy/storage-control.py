#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import pwd
import grp
import shutil
import subprocess
import sys
import tempfile
import time
import uuid


FSTAB_FILE = "/etc/fstab"
FSTAB_MARKER_BEGIN = "# BEGIN FLASK_DOWNLOADER_STORAGE"
FSTAB_MARKER_END = "# END FLASK_DOWNLOADER_STORAGE"


def fail(message, code=1, **extra):
    payload = {"ok": False, "message": str(message or "").strip() or "Nieznany błąd."}
    payload.update(extra)
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.flush()
    raise SystemExit(code)


def respond(**payload):
    output = dict(payload or {})
    if "ok" not in output:
        output["ok"] = True
    sys.stdout.write(json.dumps(output, ensure_ascii=False))
    sys.stdout.flush()
    raise SystemExit(0)


def read_payload():
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except Exception as exc:
        fail("Nie udało się odczytać danych wejściowych helpera storage-control: %s" % exc)
    if not isinstance(payload, dict):
        fail("Dane wejściowe helpera storage-control muszą być obiektem JSON.")
    return payload


def normalize_abs_path(value, field_label):
    path = os.path.abspath(str(value or "").strip())
    if not path or path in (".", "/.."):
        fail("%s nie może być puste." % field_label)
    return path


def normalize_network_share(value):
    share = str(value or "").strip()
    if not share:
        fail("Adres udziału sieciowego nie może być pusty.")
    if not share.startswith("//"):
        fail("Adres udziału sieciowego musi mieć format //host/udział.")
    parts = [item for item in share.split("/") if item]
    if len(parts) < 2:
        fail("Adres udziału sieciowego musi mieć format //host/udział.")
    return "//%s/%s" % (parts[0], parts[1])


def normalize_subpath(value):
    text = str(value or "").strip().replace("\\", "/").strip("/")
    if not text:
        return ""
    normalized = os.path.normpath(text).replace("\\", "/").strip("/")
    if normalized in ("", ".", "..") or normalized.startswith("../"):
        fail("Podfolder udziału sieciowego ma nieprawidłową wartość.")
    return normalized


def normalize_simple_text(value, field_label, *, required=False, max_len=255):
    text = str(value or "").strip()
    if required and not text:
        fail("%s nie może być puste." % field_label)
    if len(text) > max_len:
        fail("%s jest za długie." % field_label)
    return text


def normalize_version(value):
    text = str(value or "").strip()
    if not text:
        return "3.0"
    return text


def normalize_iocharset(value):
    text = str(value or "").strip()
    return text or "utf8"


def get_identity_ids(username, group_name):
    try:
        user_info = pwd.getpwnam(str(username or "").strip())
    except KeyError:
        fail("Nie znaleziono użytkownika usługi Linux: %s" % username)
    try:
        group_info = grp.getgrnam(str(group_name or "").strip())
    except KeyError:
        fail("Nie znaleziono grupy usługi Linux: %s" % group_name)
    return int(user_info.pw_uid), int(group_info.gr_gid)


def ensure_parent_dir(path, mode=0o755):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, mode=mode, exist_ok=True)


def ensure_dir(path, mode=0o775):
    os.makedirs(path, mode=mode, exist_ok=True)


def write_credentials_file(path, username, password, domain=""):
    ensure_parent_dir(path, mode=0o755)
    fd, temp_path = tempfile.mkstemp(prefix=".storage-credentials-", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("username=%s\n" % username)
            handle.write("password=%s\n" % password)
            if domain:
                handle.write("domain=%s\n" % domain)
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def read_credentials_file(path):
    payload = {
        "username": "",
        "password": "",
        "domain": "",
    }
    if not path or not os.path.isfile(path):
        return payload
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = str(raw_line or "").strip()
                if not line or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = str(key or "").strip().lower()
                if key in payload:
                    payload[key] = str(value or "").strip()
    except Exception:
        return payload
    return payload


def ensure_credentials_available(credentials_file, username, password, domain="", *, keep_existing_password=True, persist=False):
    if password:
        if persist:
            write_credentials_file(credentials_file, username, password, domain=domain)
            return credentials_file, True
        fd, temp_path = tempfile.mkstemp(prefix=".storage-test-credentials-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write("username=%s\n" % username)
                handle.write("password=%s\n" % password)
                if domain:
                    handle.write("domain=%s\n" % domain)
            os.chmod(temp_path, 0o600)
            return temp_path, False
        except Exception:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise

    if keep_existing_password and os.path.isfile(credentials_file):
        if persist:
            existing = read_credentials_file(credentials_file)
            write_credentials_file(
                credentials_file,
                username or existing.get("username") or "",
                existing.get("password") or "",
                domain or existing.get("domain") or "",
            )
        return credentials_file, True

    fail("Brakuje hasła do udziału sieciowego. Wpisz nowe hasło albo zachowaj istniejące dane logowania.")


def build_mount_options(config, credentials_path, uid, gid, *, for_fstab=False):
    options = [
        "credentials=%s" % credentials_path,
        "iocharset=%s" % config["iocharset"],
        "uid=%s" % uid,
        "gid=%s" % gid,
        "file_mode=0664",
        "dir_mode=0775",
        "noperm",
        "rw",
        "_netdev",
        "nofail",
        "vers=%s" % config["cifs_version"],
    ]
    if config["subpath"]:
        options.append("prefixpath=%s" % config["subpath"])
    if for_fstab:
        options.extend([
            "x-systemd.automount",
            "x-systemd.device-timeout=10",
            "x-systemd.mount-timeout=10",
        ])
    return ",".join(options)


def build_fstab_block(config, credentials_path, uid, gid):
    options = build_mount_options(config, credentials_path, uid, gid, for_fstab=True)
    line = "%s %s cifs %s 0 0" % (config["share"], config["mount_dir"], options)
    return "%s\n%s\n%s\n" % (FSTAB_MARKER_BEGIN, line, FSTAB_MARKER_END)


def write_managed_fstab_block(block_text):
    ensure_parent_dir(FSTAB_FILE, mode=0o755)
    existing = ""
    if os.path.isfile(FSTAB_FILE):
        with open(FSTAB_FILE, "r", encoding="utf-8") as handle:
            existing = handle.read()

    lines = existing.splitlines()
    cleaned = []
    inside_block = False
    for line in lines:
        if line.strip() == FSTAB_MARKER_BEGIN:
            inside_block = True
            continue
        if line.strip() == FSTAB_MARKER_END:
            inside_block = False
            continue
        if not inside_block:
            cleaned.append(line)

    cleaned_text = "\n".join(cleaned).rstrip("\n")
    next_text = cleaned_text + ("\n\n" if cleaned_text else "") + block_text.strip("\n") + "\n"

    fd, temp_path = tempfile.mkstemp(prefix=".fstab.flask-downloader.", dir=os.path.dirname(FSTAB_FILE))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(next_text)
        os.chmod(temp_path, 0o644)
        os.replace(temp_path, FSTAB_FILE)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def is_mount_active(path):
    return os.path.ismount(path)


def run_command(command, *, timeout=30):
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False,
    )
    return result.returncode, str(result.stdout or "").strip(), str(result.stderr or "").strip()


def mount_share(config, credentials_path, uid, gid):
    ensure_dir(config["mount_dir"], mode=0o775)
    if is_mount_active(config["mount_dir"]):
        return True, "Udział sieciowy jest już zamontowany."
    options = build_mount_options(config, credentials_path, uid, gid, for_fstab=False)
    code, out, err = run_command(
        [
            "/bin/mount",
            "-t",
            "cifs",
            config["share"],
            config["mount_dir"],
            "-o",
            options,
        ],
        timeout=45,
    )
    if code != 0 and not is_mount_active(config["mount_dir"]):
        return False, err or out or "Nie udało się zamontować udziału sieciowego."
    return True, "Udział sieciowy został zamontowany."


def unmount_share(mount_dir):
    if not is_mount_active(mount_dir):
        return True, "Udział sieciowy jest już odmontowany."
    code, out, err = run_command(["/bin/umount", mount_dir], timeout=30)
    if code != 0 and is_mount_active(mount_dir):
        return False, err or out or "Nie udało się odmontować udziału sieciowego."
    return True, "Udział sieciowy został odmontowany."


def test_rw_access(root_path):
    result = {
        "read_ok": False,
        "write_ok": False,
        "execute_ok": False,
        "message": "",
    }
    try:
        entries = os.listdir(root_path)
        result["read_ok"] = True
    except Exception as exc:
        result["message"] = "Brak odczytu katalogu: %s" % exc
        return result

    result["execute_ok"] = os.access(root_path, os.X_OK)
    temp_name = ".flask-downloader-storage-test-%s.tmp" % uuid.uuid4().hex
    temp_path = os.path.join(root_path, temp_name)
    try:
        with open(temp_path, "w", encoding="utf-8") as handle:
            handle.write("ok %s\n" % int(time.time()))
        result["write_ok"] = True
    except Exception as exc:
        result["message"] = "Brak zapisu katalogu: %s" % exc
        return result
    finally:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass

    if not result["execute_ok"]:
        result["message"] = "Brak prawa wejścia do katalogu."
    else:
        result["message"] = "Połączenie z udziałem sieciowym działa poprawnie."
    return result


def ensure_full_rw_access(access, *, share, mount_dir):
    payload = dict(access or {})
    if payload.get("read_ok") and payload.get("write_ok") and payload.get("execute_ok"):
        return
    fail(
        payload.get("message") or "Udział sieciowy nie ma pełnych praw odczytu i zapisu.",
        share=share,
        mount_dir=mount_dir,
        read_ok=bool(payload.get("read_ok")),
        write_ok=bool(payload.get("write_ok")),
        execute_ok=bool(payload.get("execute_ok")),
        is_mount=bool(os.path.ismount(mount_dir)),
    )


def normalize_storage_payload(payload):
    storage = dict((payload or {}).get("storage") or {})
    network = dict(storage.get("network") or {})
    app_user = normalize_simple_text((payload or {}).get("app_user"), "Użytkownik aplikacji", required=True, max_len=120)
    app_group = normalize_simple_text((payload or {}).get("app_group"), "Grupa aplikacji", required=True, max_len=120)
    return {
        "app_user": app_user,
        "app_group": app_group,
        "active_backend": str(storage.get("active_backend") or "local").strip().lower() or "local",
        "network": {
            "share": normalize_network_share(network.get("share")),
            "subpath": normalize_subpath(network.get("subpath")),
            "mount_dir": normalize_abs_path(network.get("mount_dir"), "Katalog montowania udziału"),
            "username": normalize_simple_text(network.get("username"), "Login SMB", required=True, max_len=120),
            "domain": normalize_simple_text(network.get("domain"), "Domena SMB", required=False, max_len=120),
            "credentials_file": normalize_abs_path(network.get("credentials_file"), "Plik danych logowania SMB"),
            "cifs_version": normalize_version(network.get("cifs_version")),
            "iocharset": normalize_iocharset(network.get("iocharset")),
            "password": str(network.get("password") or ""),
            "keep_existing_password": bool(network.get("keep_existing_password", True)),
        },
    }


def test_cifs(payload):
    data = normalize_storage_payload(payload)
    config = data["network"]
    credentials_path, persisted = ensure_credentials_available(
        config["credentials_file"],
        config["username"],
        config["password"],
        domain=config["domain"],
        keep_existing_password=config["keep_existing_password"],
        persist=False,
    )
    uid, gid = get_identity_ids(data["app_user"], data["app_group"])

    temp_mount_dir = tempfile.mkdtemp(prefix="flask-downloader-mount-test-", dir="/run")
    temp_config = dict(config)
    temp_config["mount_dir"] = temp_mount_dir

    try:
        mounted, mount_message = mount_share(temp_config, credentials_path, uid, gid)
        if not mounted:
            fail(mount_message, share=config["share"], mount_dir=temp_mount_dir)
        access = test_rw_access(temp_mount_dir)
        ensure_full_rw_access(access, share=config["share"], mount_dir=temp_mount_dir)
        respond(
            ok=True,
            message=access["message"],
            share=config["share"],
            mount_dir=config["mount_dir"],
            read_ok=access["read_ok"],
            write_ok=access["write_ok"],
            execute_ok=access["execute_ok"],
            is_mount=True,
            tested=True,
        )
    finally:
        try:
            unmount_share(temp_mount_dir)
        except Exception:
            pass
        shutil.rmtree(temp_mount_dir, ignore_errors=True)
        if not persisted and credentials_path and os.path.exists(credentials_path):
            os.remove(credentials_path)


def configure_cifs(payload):
    data = normalize_storage_payload(payload)
    config = data["network"]
    uid, gid = get_identity_ids(data["app_user"], data["app_group"])
    mount_now = bool((payload or {}).get("mount_now"))

    credentials_path, _ = ensure_credentials_available(
        config["credentials_file"],
        config["username"],
        config["password"],
        domain=config["domain"],
        keep_existing_password=config["keep_existing_password"],
        persist=True,
    )

    ensure_dir(config["mount_dir"], mode=0o775)
    write_managed_fstab_block(build_fstab_block(config, credentials_path, uid, gid))

    mounted = is_mount_active(config["mount_dir"])
    message = "Konfiguracja udziału sieciowego została zapisana."
    if mount_now:
        mounted, mount_message = mount_share(config, credentials_path, uid, gid)
        if not mounted:
            fail(mount_message, share=config["share"], mount_dir=config["mount_dir"])
        access = test_rw_access(config["mount_dir"])
        ensure_full_rw_access(access, share=config["share"], mount_dir=config["mount_dir"])
        message = access["message"]
    else:
        mounted = is_mount_active(config["mount_dir"])
        access = test_rw_access(config["mount_dir"]) if mounted else {
            "read_ok": False,
            "write_ok": False,
            "execute_ok": False,
            "message": "Konfiguracja udziału sieciowego została zapisana. Użyj testu lub montowania, aby sprawdzić połączenie.",
        }

    respond(
        ok=True,
        message=message,
        share=config["share"],
        mount_dir=config["mount_dir"],
        read_ok=bool(access.get("read_ok")),
        write_ok=bool(access.get("write_ok")),
        execute_ok=bool(access.get("execute_ok")),
        is_mount=bool(mounted),
        configured=True,
    )


def mount_cifs(payload):
    data = normalize_storage_payload(payload)
    config = data["network"]
    uid, gid = get_identity_ids(data["app_user"], data["app_group"])
    credentials_path, _ = ensure_credentials_available(
        config["credentials_file"],
        config["username"],
        config["password"],
        domain=config["domain"],
        keep_existing_password=True,
        persist=False,
    )
    mounted, mount_message = mount_share(config, credentials_path, uid, gid)
    if not mounted:
        fail(mount_message, share=config["share"], mount_dir=config["mount_dir"])
    access = test_rw_access(config["mount_dir"])
    ensure_full_rw_access(access, share=config["share"], mount_dir=config["mount_dir"])
    respond(
        ok=True,
        message=access["message"],
        share=config["share"],
        mount_dir=config["mount_dir"],
        read_ok=access["read_ok"],
        write_ok=access["write_ok"],
        execute_ok=access["execute_ok"],
        is_mount=True,
        mounted=True,
    )


def unmount_cifs(payload):
    data = normalize_storage_payload(payload)
    config = data["network"]
    ok, message = unmount_share(config["mount_dir"])
    if not ok:
        fail(message, share=config["share"], mount_dir=config["mount_dir"])
    respond(
        ok=True,
        message=message,
        share=config["share"],
        mount_dir=config["mount_dir"],
        is_mount=False,
        mounted=False,
    )


def main():
    if os.geteuid() != 0:
        fail("Helper storage-control musi działać jako root.")

    action = str(sys.argv[1] or "").strip().lower() if len(sys.argv) > 1 else ""
    payload = read_payload()

    if action == "test-cifs":
        test_cifs(payload)
    elif action == "configure-cifs":
        configure_cifs(payload)
    elif action == "mount-cifs":
        mount_cifs(payload)
    elif action == "unmount-cifs":
        unmount_cifs(payload)

    fail("Nieznana akcja helpera storage-control: %s" % action, code=64)


if __name__ == "__main__":
    main()
