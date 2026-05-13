import os
import uuid

from flask_downloader.utils.formatting import build_natural_sort_key


class DlnaLibraryService:
    def __init__(
        self,
        *,
        get_mount_info,
        get_server_files,
        prune_missing_dlna_media_rules,
        get_dlna_config_snapshot,
        set_dlna_config,
        refresh_dlna_package_state,
        get_dlna_service_state,
        get_all_maintenance_task_snapshots,
        normalize_dlna_config,
        normalize_storage_kind,
        safe_relative_download_path,
        resolve_download_path,
        format_relative_path_for_user,
        format_bytes_text,
        format_ts,
        normalize_dlna_server_name,
        normalize_dlna_bind_ip,
        normalize_dlna_port,
        normalize_dlna_collection_name,
        normalize_dlna_client_ip,
        normalize_dlna_description,
        sync_dlna_runtime_safe,
        get_users_snapshot,
        default_admin_username,
        dlna_all_collection_id,
        dlna_all_collection_name,
        dlna_export_root,
        dlna_config_xml_file,
        dlna_service_unit_file,
    ):
        self._get_mount_info = get_mount_info
        self._get_server_files = get_server_files
        self._prune_missing_dlna_media_rules = prune_missing_dlna_media_rules
        self._get_dlna_config_snapshot = get_dlna_config_snapshot
        self._set_dlna_config = set_dlna_config
        self._refresh_dlna_package_state = refresh_dlna_package_state
        self._get_dlna_service_state = get_dlna_service_state
        self._get_all_maintenance_task_snapshots = get_all_maintenance_task_snapshots
        self._normalize_dlna_config = normalize_dlna_config
        self._normalize_storage_kind = normalize_storage_kind
        self._safe_relative_download_path = safe_relative_download_path
        self._resolve_download_path = resolve_download_path
        self._format_relative_path_for_user = format_relative_path_for_user
        self._format_bytes_text = format_bytes_text
        self._format_ts = format_ts
        self._normalize_dlna_server_name = normalize_dlna_server_name
        self._normalize_dlna_bind_ip = normalize_dlna_bind_ip
        self._normalize_dlna_port = normalize_dlna_port
        self._normalize_dlna_collection_name = normalize_dlna_collection_name
        self._normalize_dlna_client_ip = normalize_dlna_client_ip
        self._normalize_dlna_description = normalize_dlna_description
        self._sync_dlna_runtime_safe = sync_dlna_runtime_safe
        self._get_users_snapshot = get_users_snapshot
        self._default_admin_username = default_admin_username
        self._dlna_all_collection_id = dlna_all_collection_id
        self._dlna_all_collection_name = dlna_all_collection_name
        self._dlna_export_root = dlna_export_root
        self._dlna_config_xml_file = dlna_config_xml_file
        self._dlna_service_unit_file = dlna_service_unit_file

    @staticmethod
    def _parse_boolean_flag(value, default=False):
        if value is None:
            return bool(default)
        if isinstance(value, bool):
            return value
        text = str(value or "").strip().lower()
        if text in ("1", "true", "yes", "on", "tak"):
            return True
        if text in ("0", "false", "no", "off", "nie"):
            return False
        return bool(default)

    def get_collection_catalog(self, dlna_config=None):
        config = dlna_config or self._get_dlna_config_snapshot()
        catalog = [{
            "id": self._dlna_all_collection_id,
            "name": self._dlna_all_collection_name,
            "description": "Klient widzi wszystkie media aktywne dla DLNA, niezależnie od dodatkowych kolekcji.",
            "builtin": True,
        }]
        for item in config.get("collections") or []:
            catalog.append({
                "id": item["id"],
                "name": item["name"],
                "description": item.get("description") or "",
                "builtin": False,
            })
        return catalog

    def get_available_users(self):
        users = []
        for user in self._get_users_snapshot() or []:
            username = str((user or {}).get("username") or "").strip()
            if not username:
                continue
            users.append({
                "username": username,
                "role": str((user or {}).get("role") or "user").strip().lower() or "user",
                "enabled": bool((user or {}).get("enabled", True)),
            })
        users.sort(key=lambda item: (0 if item["role"] == "admin" else 1, item["username"].lower()))
        return users

    def get_named_collection_map(self, dlna_config=None):
        config = dlna_config or self._get_dlna_config_snapshot()
        return {
            item["id"]: {
                "id": item["id"],
                "name": item["name"],
                "description": item.get("description") or "",
            }
            for item in config.get("collections") or []
        }

    def get_assignable_collections_for_user(self, username="", is_admin=False, dlna_config=None):
        config = dlna_config or self._get_dlna_config_snapshot()
        named_map = self.get_named_collection_map(config)
        if not named_map:
            return []

        if is_admin:
            return sorted(named_map.values(), key=lambda item: item["name"].lower())

        normalized_username = str(username or "").strip()
        if not normalized_username:
            return []

        visible_ids = set()
        for client in config.get("clients") or []:
            if not client.get("enabled", True):
                continue
            assigned_usernames = self.get_client_assigned_usernames(client)
            if normalized_username not in assigned_usernames:
                continue

            client_collection_ids = self.get_client_visible_collection_ids(client, config)
            if self._dlna_all_collection_id in client_collection_ids:
                visible_ids.update(named_map.keys())
                continue

            for collection_id in client_collection_ids:
                if collection_id in named_map:
                    visible_ids.add(collection_id)

        return sorted(
            [named_map[collection_id] for collection_id in visible_ids if collection_id in named_map],
            key=lambda item: item["name"].lower(),
        )

    def get_library_candidates(self, files=None):
        files = files if files is not None else self._get_server_files()
        folders = {}
        folder_match_counts = {}
        normalized_files = []

        for item in files:
            storage_kind = self._normalize_storage_kind(item.get("storage_kind") or "video")
            relative_path = self._safe_relative_download_path(item.get("relative_path") or "")
            if not relative_path:
                continue

            display_path = self._format_relative_path_for_user(
                relative_path,
                viewer_username=self._default_admin_username,
                is_admin=True,
            )
            normalized_item = dict(item)
            normalized_item["storage_kind"] = storage_kind
            normalized_item["relative_path"] = relative_path
            normalized_item["display_path"] = display_path
            normalized_files.append(normalized_item)

            folder_path = relative_path
            while "/" in folder_path:
                folder_path = folder_path.rsplit("/", 1)[0]
                key = (storage_kind, folder_path)
                folder_match_counts[key] = folder_match_counts.get(key, 0) + 1
                folders[key] = {
                    "storage_kind": storage_kind,
                    "relative_path": folder_path,
                    "display_path": self._format_relative_path_for_user(
                        folder_path,
                        viewer_username=self._default_admin_username,
                        is_admin=True,
                    ),
                }

        folder_items = []
        for key, item in folders.items():
            folder_item = dict(item)
            folder_item["file_count"] = folder_match_counts.get(key, 0)
            folder_items.append(folder_item)

        folder_items.sort(key=lambda item: (build_natural_sort_key(item["display_path"]), item["storage_kind"]))
        normalized_files.sort(key=lambda item: build_natural_sort_key(item["display_path"]))
        return {
            "folders": folder_items,
            "files": normalized_files,
        }

    @staticmethod
    def normalize_library_mode(value):
        mode = str(value or "").strip().lower()
        if mode in ("folder", "folders"):
            return "folders"
        if mode == "all":
            return "all"
        return "files"

    def build_exact_rule_lookup(self, dlna_config=None):
        config = dlna_config or self._get_dlna_config_snapshot()
        lookup = {}
        for rule in config.get("media_rules") or []:
            key = (
                str(rule.get("kind") or "").strip().lower(),
                self._normalize_storage_kind(rule.get("storage_kind") or "video"),
                self._safe_relative_download_path(rule.get("relative_path") or ""),
            )
            if key[0] in ("file", "folder") and key[2]:
                lookup[key] = rule
        return lookup

    def normalize_collection_editor_id(self, collection_id, dlna_config=None):
        config = dlna_config or self._get_dlna_config_snapshot()
        normalized_id = str(collection_id or "").strip()
        return normalized_id if normalized_id in self.get_named_collection_map(config) else ""

    def normalize_client_collection_ids(self, collection_ids, dlna_config=None):
        config = dlna_config or self._get_dlna_config_snapshot()
        named_collection_ids = set(self.get_named_collection_map(config).keys())
        result = []
        seen = set()
        for item in collection_ids or []:
            value = str(item or "").strip()
            if not value or value in seen:
                continue
            if value != self._dlna_all_collection_id and value not in named_collection_ids:
                continue
            seen.add(value)
            result.append(value)
        return result

    def normalize_client_usernames(self, usernames):
        valid_usernames = {
            str(item.get("username") or "").strip()
            for item in (self.get_available_users() or [])
            if str(item.get("username") or "").strip()
        }
        result = []
        seen = set()
        for item in usernames or []:
            value = str(item or "").strip()
            if not value or value in seen or value not in valid_usernames:
                continue
            seen.add(value)
            result.append(value)
        return result

    def normalize_media_rule_collection_ids(self, collection_ids, dlna_config=None):
        config = dlna_config or self._get_dlna_config_snapshot()
        named_collection_ids = set(self.get_named_collection_map(config).keys())
        result = []
        seen = set()
        for item in collection_ids or []:
            value = str(item or "").strip()
            if not value or value in seen or value == self._dlna_all_collection_id:
                continue
            if value not in named_collection_ids:
                continue
            seen.add(value)
            result.append(value)
        return result

    def resolve_rule_matches(self, rule, files=None):
        files = files if files is not None else self._get_server_files()
        storage_kind = self._normalize_storage_kind(rule.get("storage_kind") or "video")
        relative_path = self._safe_relative_download_path(rule.get("relative_path") or "")
        kind = str(rule.get("kind") or "").strip().lower()
        matches = []

        for item in files:
            if self._normalize_storage_kind(item.get("storage_kind") or "video") != storage_kind:
                continue
            item_relative_path = self._safe_relative_download_path(item.get("relative_path") or "")
            if not item_relative_path:
                continue
            if kind == "file" and item_relative_path == relative_path:
                matches.append(item)
            elif kind == "folder" and (item_relative_path == relative_path or item_relative_path.startswith(relative_path + "/")):
                matches.append(item)

        return matches

    def get_effective_file_map(self, dlna_config=None, files=None):
        config = dlna_config or self._get_dlna_config_snapshot()
        files = files if files is not None else self._get_server_files()
        collection_map = self.get_named_collection_map(config)
        effective = {}

        for rule in config.get("media_rules") or []:
            if not rule.get("enabled", True):
                continue

            matches = self.resolve_rule_matches(rule, files=files)
            for item in matches:
                storage_kind = self._normalize_storage_kind(item.get("storage_kind") or "video")
                relative_path = self._safe_relative_download_path(item.get("relative_path") or "")
                if not relative_path:
                    continue
                absolute_path = self._resolve_download_path(relative_path, storage_kind)
                if not absolute_path or not os.path.isfile(absolute_path):
                    continue

                entry = effective.setdefault(absolute_path, {
                    "storage_kind": storage_kind,
                    "relative_path": relative_path,
                    "display_path": item.get("display_path") or ("%s/%s" % (storage_kind, relative_path)),
                    "size": item.get("size") or 0,
                    "mtime": item.get("mtime") or 0.0,
                    "collection_ids": set(),
                    "rule_ids": set(),
                })
                entry["rule_ids"].add(rule["id"])
                for collection_id in rule.get("collection_ids") or []:
                    if collection_id in collection_map:
                        entry["collection_ids"].add(collection_id)

        return effective

    def get_client_visible_collection_ids(self, client, dlna_config=None):
        config = dlna_config or self._get_dlna_config_snapshot()
        named_map = self.get_named_collection_map(config)
        collection_ids = [
            item
            for item in (client.get("collection_ids") or [])
            if item == self._dlna_all_collection_id or item in named_map
        ]
        if self._dlna_all_collection_id in collection_ids:
            return {self._dlna_all_collection_id}
        return set(collection_ids)

    def get_client_assigned_usernames(self, client):
        return self.normalize_client_usernames((client or {}).get("usernames") or [])

    def build_media_rule_summaries(self, dlna_config=None, files=None):
        config = dlna_config or self._get_dlna_config_snapshot()
        files = files if files is not None else self._get_server_files()
        collection_map = self.get_named_collection_map(config)
        summaries = []

        for rule in config.get("media_rules") or []:
            matches = self.resolve_rule_matches(rule, files=files)
            storage_kind = self._normalize_storage_kind(rule.get("storage_kind") or "video")
            relative_path = self._safe_relative_download_path(rule.get("relative_path") or "")
            display_path = self._format_relative_path_for_user(
                relative_path,
                viewer_username=self._default_admin_username,
                is_admin=True,
            )
            summaries.append({
                "id": rule["id"],
                "kind": rule["kind"],
                "storage_kind": storage_kind,
                "relative_path": relative_path,
                "display_path": display_path,
                "enabled": bool(rule.get("enabled", True)),
                "matched_files": len(matches),
                "exists": bool(matches),
                "collection_ids": [item for item in (rule.get("collection_ids") or []) if item in collection_map],
                "collection_names": [
                    collection_map[item]["name"]
                    for item in (rule.get("collection_ids") or [])
                    if item in collection_map
                ],
            })

        summaries.sort(key=lambda item: (build_natural_sort_key(item["display_path"]), item["kind"]))
        return summaries

    def build_client_summaries(self, dlna_config=None, files=None):
        config = dlna_config or self._get_dlna_config_snapshot()
        files = files if files is not None else self._get_server_files()
        effective_map = self.get_effective_file_map(config, files=files)
        collection_catalog = {item["id"]: item for item in self.get_collection_catalog(config)}
        available_users = {item["username"]: item for item in self.get_available_users()}
        client_items = []

        for client in config.get("clients") or []:
            visible_collection_ids = self.get_client_visible_collection_ids(client, config)
            assigned_usernames = self.get_client_assigned_usernames(client)
            visible_file_keys = set()

            for item in effective_map.values():
                if self._dlna_all_collection_id in visible_collection_ids:
                    visible_file_keys.add((
                        self._normalize_storage_kind(item.get("storage_kind") or "video"),
                        self._safe_relative_download_path(item.get("relative_path") or ""),
                    ))
                    continue
                if item["collection_ids"] & visible_collection_ids:
                    visible_file_keys.add((
                        self._normalize_storage_kind(item.get("storage_kind") or "video"),
                        self._safe_relative_download_path(item.get("relative_path") or ""),
                    ))

            for file_item in files:
                owner_username = str(file_item.get("owner_username") or "").strip()
                if owner_username not in assigned_usernames:
                    continue
                visible_file_keys.add((
                    self._normalize_storage_kind(file_item.get("storage_kind") or "video"),
                    self._safe_relative_download_path(file_item.get("relative_path") or ""),
                ))

            client_items.append({
                "id": client["id"],
                "ip": client["ip"],
                "description": client.get("description") or "",
                "enabled": bool(client.get("enabled", True)),
                "collection_ids": list(visible_collection_ids),
                "collection_names": [
                    collection_catalog[item]["name"]
                    for item in visible_collection_ids
                    if item in collection_catalog
                ],
                "usernames": assigned_usernames,
                "user_labels": [
                    ("%s%s" % (username, " (admin)" if (available_users.get(username) or {}).get("role") == "admin" else ""))
                    for username in assigned_usernames
                ],
                "visible_media_count": len(visible_file_keys),
            })

        client_items.sort(key=lambda item: item["ip"])
        return client_items

    def get_summary_state(self, dlna_config=None, files=None):
        config = dlna_config or self._get_dlna_config_snapshot()
        files = files if files is not None else self._get_server_files()
        effective_map = self.get_effective_file_map(config, files=files)
        return {
            "named_collection_count": len(config.get("collections") or []),
            "client_count": len(config.get("clients") or []),
            "active_client_count": len([item for item in (config.get("clients") or []) if item.get("enabled", True)]),
            "media_rule_count": len(config.get("media_rules") or []),
            "active_folder_rule_count": len([
                item
                for item in (config.get("media_rules") or [])
                if item.get("kind") == "folder" and item.get("enabled", True)
            ]),
            "active_file_rule_count": len([
                item
                for item in (config.get("media_rules") or [])
                if item.get("kind") == "file" and item.get("enabled", True)
            ]),
            "effective_media_count": len(effective_map),
            "last_sync_at": config.get("last_sync_at") or 0.0,
            "last_sync_text": self._format_ts(config.get("last_sync_at")) if config.get("last_sync_at") else "jeszcze nie synchronizowano",
            "last_sync_error": config.get("last_sync_error") or "",
            "export_root": self._dlna_export_root,
            "config_file": self._dlna_config_xml_file,
            "service_unit_file": self._dlna_service_unit_file,
        }

    def get_page_state(self):
        mount = self._get_mount_info(auto_remount=True)
        files = self._get_server_files() if mount.get("online") else []
        if mount.get("online"):
            prune_result = self._prune_missing_dlna_media_rules(
                files=files,
                sync_runtime=True,
                restart_service_if_active=False,
            )
            dlna_config = self._normalize_dlna_config(prune_result.get("config"))
            if prune_result.get("changed"):
                files = self._get_server_files()
        else:
            dlna_config = self._get_dlna_config_snapshot()

        return {
            "mount": mount,
            "dlna_config": dlna_config,
            "collections": self.get_collection_catalog(dlna_config),
            "available_users": self.get_available_users(),
            "media_rules": self.build_media_rule_summaries(dlna_config, files=files),
            "clients": self.build_client_summaries(dlna_config, files=files),
            "summary": self.get_summary_state(dlna_config, files=files),
            "dlna_package_state": self._refresh_dlna_package_state(force=False),
            "dlna_service_state": self._get_dlna_service_state(),
            "maintenance_tasks": self._get_all_maintenance_task_snapshots(),
        }

    def ensure_collection_membership_on_exact_rule(self, dlna_config, kind, storage_kind, relative_path, collection_id):
        normalized_kind = str(kind or "").strip().lower()
        if normalized_kind not in ("file", "folder"):
            raise ValueError("Nieobsługiwany typ wpisu DLNA.")

        normalized_storage_kind = self._normalize_storage_kind(storage_kind or "video")
        normalized_relative_path = self._safe_relative_download_path(relative_path)
        normalized_collection_id = self.normalize_collection_editor_id(collection_id, dlna_config)
        if not normalized_relative_path:
            raise ValueError("Ścieżka pliku lub folderu jest nieprawidłowa.")
        if not normalized_collection_id:
            raise ValueError("Nie znaleziono wskazanego bukietu DLNA.")

        for rule in dlna_config.get("media_rules") or []:
            if (
                rule.get("kind") == normalized_kind
                and self._normalize_storage_kind(rule.get("storage_kind") or "video") == normalized_storage_kind
                and self._safe_relative_download_path(rule.get("relative_path") or "") == normalized_relative_path
            ):
                changed = False
                if not rule.get("enabled", True):
                    rule["enabled"] = True
                    changed = True

                existing_collection_ids = list(rule.get("collection_ids") or [])
                if normalized_collection_id not in existing_collection_ids:
                    rule["collection_ids"] = self.normalize_media_rule_collection_ids(
                        existing_collection_ids + [normalized_collection_id],
                        dlna_config,
                    )
                    changed = True
                return changed

        dlna_config.setdefault("media_rules", []).append({
            "id": uuid.uuid4().hex,
            "kind": normalized_kind,
            "storage_kind": normalized_storage_kind,
            "relative_path": normalized_relative_path,
            "enabled": True,
            "collection_ids": self.normalize_media_rule_collection_ids([normalized_collection_id], dlna_config),
        })
        return True

    def remove_collection_membership_from_exact_rule(self, dlna_config, kind, storage_kind, relative_path, collection_id):
        normalized_kind = str(kind or "").strip().lower()
        normalized_storage_kind = self._normalize_storage_kind(storage_kind or "video")
        normalized_relative_path = self._safe_relative_download_path(relative_path)
        normalized_collection_id = self.normalize_collection_editor_id(collection_id, dlna_config)
        if normalized_kind not in ("file", "folder") or not normalized_relative_path or not normalized_collection_id:
            return False

        for rule in dlna_config.get("media_rules") or []:
            if (
                rule.get("kind") != normalized_kind
                or self._normalize_storage_kind(rule.get("storage_kind") or "video") != normalized_storage_kind
                or self._safe_relative_download_path(rule.get("relative_path") or "") != normalized_relative_path
            ):
                continue

            existing_collection_ids = list(rule.get("collection_ids") or [])
            if normalized_collection_id not in existing_collection_ids:
                return False

            rule["collection_ids"] = self.normalize_media_rule_collection_ids(
                [item for item in existing_collection_ids if item != normalized_collection_id],
                dlna_config,
            )
            return True

        return False

    def explode_collection_from_matching_folder_rules(self, dlna_config, collection_id, file_items, files=None):
        normalized_collection_id = self.normalize_collection_editor_id(collection_id, dlna_config)
        if not normalized_collection_id:
            raise ValueError("Nie znaleziono wskazanego bukietu DLNA.")

        files = files if files is not None else self._get_server_files()
        affected_file_keys = {
            (
                self._normalize_storage_kind(item.get("storage_kind") or "video"),
                self._safe_relative_download_path(item.get("relative_path") or ""),
            )
            for item in file_items or []
            if str(item.get("kind") or "").strip().lower() == "file"
            and self._safe_relative_download_path(item.get("relative_path") or "")
        }
        if not affected_file_keys:
            return False

        changed = False
        for rule in dlna_config.get("media_rules") or []:
            if str(rule.get("kind") or "").strip().lower() != "folder":
                continue
            if not rule.get("enabled", True):
                continue
            if normalized_collection_id not in (rule.get("collection_ids") or []):
                continue

            matches = self.resolve_rule_matches(rule, files=files)
            matched_keys = {
                (
                    self._normalize_storage_kind(item.get("storage_kind") or "video"),
                    self._safe_relative_download_path(item.get("relative_path") or ""),
                )
                for item in matches
                if self._safe_relative_download_path(item.get("relative_path") or "")
            }
            if not (matched_keys & affected_file_keys):
                continue

            for match in matches:
                if self.ensure_collection_membership_on_exact_rule(
                    dlna_config,
                    "file",
                    match.get("storage_kind"),
                    match.get("relative_path"),
                    normalized_collection_id,
                ):
                    changed = True

            existing_collection_ids = list(rule.get("collection_ids") or [])
            next_collection_ids = self.normalize_media_rule_collection_ids(
                [item for item in existing_collection_ids if item != normalized_collection_id],
                dlna_config,
            )
            if next_collection_ids != existing_collection_ids:
                rule["collection_ids"] = next_collection_ids
                changed = True

        return changed

    def bulk_assign_collection_items(self, collection_id, items):
        files = self._get_server_files()
        dlna_config = self._get_dlna_config_snapshot()
        normalized_collection_id = self.normalize_collection_editor_id(collection_id, dlna_config)
        if not normalized_collection_id:
            raise ValueError("Wybierz istniejący bukiet DLNA do edycji.")

        normalized_items = []
        seen_keys = set()
        for raw_item in items or []:
            if not isinstance(raw_item, dict):
                continue
            kind = str(raw_item.get("kind") or "").strip().lower()
            if kind not in ("file", "folder"):
                continue
            storage_kind = self._normalize_storage_kind(raw_item.get("storage_kind") or "video")
            relative_path = self._safe_relative_download_path(raw_item.get("relative_path") or "")
            if not relative_path:
                continue
            key = (kind, storage_kind, relative_path)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            normalized_items.append({
                "kind": kind,
                "storage_kind": storage_kind,
                "relative_path": relative_path,
                "checked": self._parse_boolean_flag(raw_item.get("checked"), default=False),
            })

        if not normalized_items:
            return {
                "changed": False,
                "updated_items": 0,
                "collection_id": normalized_collection_id,
            }

        changed = self.explode_collection_from_matching_folder_rules(
            dlna_config,
            normalized_collection_id,
            [item for item in normalized_items if item["kind"] == "file"],
            files=files,
        )

        for item in normalized_items:
            if item["checked"]:
                if self.ensure_collection_membership_on_exact_rule(
                    dlna_config,
                    item["kind"],
                    item["storage_kind"],
                    item["relative_path"],
                    normalized_collection_id,
                ):
                    changed = True
                continue

            if self.remove_collection_membership_from_exact_rule(
                dlna_config,
                item["kind"],
                item["storage_kind"],
                item["relative_path"],
                normalized_collection_id,
            ):
                changed = True

        if changed:
            self._set_dlna_config(dlna_config)
            self._sync_dlna_runtime_safe(restart_service_if_active=True, force_full_rescan=True)

        return {
            "changed": changed,
            "updated_items": len(normalized_items),
            "collection_id": normalized_collection_id,
        }

    def build_collection_library_results(self, collection_id="", query="", mode="files", limit=200, dlna_config=None, files=None):
        config = dlna_config or self._get_dlna_config_snapshot()
        files = files if files is not None else self._get_server_files()
        normalized_collection_id = self.normalize_collection_editor_id(collection_id, config)
        normalized_mode = self.normalize_library_mode(mode)
        query_text = str(query or "").strip().lower()
        exact_rule_lookup = self.build_exact_rule_lookup(config)
        effective_file_map = self.get_effective_file_map(config, files=files)
        effective_file_lookup = {}

        for entry in effective_file_map.values():
            key = (
                self._normalize_storage_kind(entry.get("storage_kind") or "video"),
                self._safe_relative_download_path(entry.get("relative_path") or ""),
            )
            if not key[1]:
                continue
            effective_file_lookup[key] = {
                "collection_ids": set(entry.get("collection_ids") or set()),
                "active": True,
            }

        library = self.get_library_candidates(files=files)
        items = []

        if normalized_mode in ("files", "all"):
            for item in library["files"]:
                key = (
                    self._normalize_storage_kind(item.get("storage_kind") or "video"),
                    self._safe_relative_download_path(item.get("relative_path") or ""),
                )
                display_path = str(item.get("display_path") or "")
                if query_text and query_text not in display_path.lower():
                    continue

                exact_rule = exact_rule_lookup.get(("file", key[0], key[1]))
                effective_entry = effective_file_lookup.get(key) or {"collection_ids": set(), "active": False}
                selected = bool(normalized_collection_id and normalized_collection_id in effective_entry["collection_ids"])
                direct_selected = bool(
                    exact_rule
                    and exact_rule.get("enabled", True)
                    and normalized_collection_id
                    and normalized_collection_id in (exact_rule.get("collection_ids") or [])
                )
                title = str(item.get("name") or os.path.basename(key[1]) or display_path)
                items.append({
                    "kind": "file",
                    "storage_kind": key[0],
                    "storage_label": item.get("storage_label") or ("Audio" if key[0] == "audio" else "Wideo"),
                    "relative_path": key[1],
                    "display_path": display_path,
                    "title": title,
                    "detail_text": "%s • %s • %s" % (
                        item.get("storage_label") or ("Audio" if key[0] == "audio" else "Wideo"),
                        self._format_bytes_text(item.get("size")),
                        item.get("mtime_text") or "brak daty",
                    ),
                    "selected": selected,
                    "selected_via": "direct" if direct_selected else ("inherited" if selected else "none"),
                    "active_in_dlna": bool(effective_entry["active"]),
                })

        if normalized_mode in ("folders", "all"):
            for item in library["folders"]:
                key = (
                    self._normalize_storage_kind(item.get("storage_kind") or "video"),
                    self._safe_relative_download_path(item.get("relative_path") or ""),
                )
                display_path = str(item.get("display_path") or "")
                if query_text and query_text not in display_path.lower():
                    continue

                exact_rule = exact_rule_lookup.get(("folder", key[0], key[1]))
                selected = bool(
                    exact_rule
                    and exact_rule.get("enabled", True)
                    and normalized_collection_id
                    and normalized_collection_id in (exact_rule.get("collection_ids") or [])
                )
                title = os.path.basename(key[1]) or key[1]
                items.append({
                    "kind": "folder",
                    "storage_kind": key[0],
                    "storage_label": "Audio" if key[0] == "audio" else "Wideo",
                    "relative_path": key[1],
                    "display_path": display_path,
                    "title": title,
                    "detail_text": "%s • %s plików" % (
                        "Audio" if key[0] == "audio" else "Wideo",
                        int(item.get("file_count") or 0),
                    ),
                    "selected": selected,
                    "selected_via": "direct" if selected else "none",
                    "active_in_dlna": bool(exact_rule and exact_rule.get("enabled", True)),
                })

        items.sort(
            key=lambda item: (
                build_natural_sort_key(item["display_path"]),
                0 if item["kind"] == "folder" else 1,
                build_natural_sort_key(item["title"]),
            )
        )
        limited_items = items[:max(1, min(500, int(limit or 200)))]
        collection_map = self.get_named_collection_map(config)

        return {
            "items": limited_items,
            "total_items": len(items),
            "shown_items": len(limited_items),
            "mode": normalized_mode,
            "collection_id": normalized_collection_id,
            "collection_name": (collection_map.get(normalized_collection_id) or {}).get("name") or "",
        }

    def update_general_settings(self, server_name, bind_ip, port):
        dlna_config = self._get_dlna_config_snapshot()
        dlna_config["server_name"] = self._normalize_dlna_server_name(server_name)
        dlna_config["bind_ip"] = self._normalize_dlna_bind_ip(bind_ip)
        dlna_config["port"] = self._normalize_dlna_port(port)
        self._set_dlna_config(dlna_config)
        self._sync_dlna_runtime_safe(restart_service_if_active=True, force_full_rescan=True)
        return self._get_dlna_config_snapshot()

    def create_collection(self, name, description=""):
        dlna_config = self._get_dlna_config_snapshot()
        normalized_name = self._normalize_dlna_collection_name(name)
        for item in dlna_config.get("collections") or []:
            if item["name"].lower() == normalized_name.lower():
                raise ValueError("Kolekcja o tej nazwie już istnieje.")

        collection = {
            "id": uuid.uuid4().hex,
            "name": normalized_name,
            "description": self._normalize_dlna_description(description, max_len=320),
        }
        dlna_config.setdefault("collections", []).append(collection)
        self._set_dlna_config(dlna_config)
        self._sync_dlna_runtime_safe(restart_service_if_active=True, force_full_rescan=True)
        return collection

    def update_collection(self, collection_id, name, description=""):
        collection_id = str(collection_id or "").strip()
        if not collection_id or collection_id == self._dlna_all_collection_id:
            raise ValueError("Nie można edytować tej kolekcji.")

        dlna_config = self._get_dlna_config_snapshot()
        normalized_name = self._normalize_dlna_collection_name(name)
        found = False
        for item in dlna_config.get("collections") or []:
            if item["id"] != collection_id and item["name"].lower() == normalized_name.lower():
                raise ValueError("Kolekcja o tej nazwie już istnieje.")

        for item in dlna_config.get("collections") or []:
            if item["id"] != collection_id:
                continue
            item["name"] = normalized_name
            item["description"] = self._normalize_dlna_description(description, max_len=320)
            found = True
            break

        if not found:
            raise ValueError("Nie znaleziono wskazanej kolekcji.")

        self._set_dlna_config(dlna_config)
        self._sync_dlna_runtime_safe(restart_service_if_active=True, force_full_rescan=True)

    def delete_collection(self, collection_id):
        collection_id = str(collection_id or "").strip()
        if not collection_id or collection_id == self._dlna_all_collection_id:
            raise ValueError("Nie można usunąć tej kolekcji.")

        dlna_config = self._get_dlna_config_snapshot()
        before_count = len(dlna_config.get("collections") or [])
        dlna_config["collections"] = [
            item
            for item in (dlna_config.get("collections") or [])
            if item["id"] != collection_id
        ]
        if len(dlna_config["collections"]) == before_count:
            raise ValueError("Nie znaleziono wskazanej kolekcji.")

        for client in dlna_config.get("clients") or []:
            client["collection_ids"] = [item for item in (client.get("collection_ids") or []) if item != collection_id]

        for rule in dlna_config.get("media_rules") or []:
            rule["collection_ids"] = [item for item in (rule.get("collection_ids") or []) if item != collection_id]

        self._set_dlna_config(dlna_config)
        self._sync_dlna_runtime_safe(restart_service_if_active=True, force_full_rescan=True)

    def assign_file_to_collection(self, storage_kind, relative_path, collection_id, *, sync_runtime=True):
        dlna_config = self._get_dlna_config_snapshot()
        changed = self.ensure_collection_membership_on_exact_rule(
            dlna_config,
            "file",
            storage_kind,
            relative_path,
            collection_id,
        )
        if not changed:
            return False

        self._set_dlna_config(dlna_config)
        if sync_runtime:
            self._sync_dlna_runtime_safe(restart_service_if_active=True, force_full_rescan=True)
        return True

    def create_client(self, ip, description="", enabled=True, collection_ids=None, usernames=None):
        dlna_config = self._get_dlna_config_snapshot()
        normalized_ip = self._normalize_dlna_client_ip(ip)
        if any(item["ip"] == normalized_ip for item in (dlna_config.get("clients") or [])):
            raise ValueError("Klient z tym adresem IP już istnieje.")

        client = {
            "id": uuid.uuid4().hex,
            "ip": normalized_ip,
            "description": self._normalize_dlna_description(description, max_len=200),
            "enabled": bool(enabled),
            "collection_ids": self.normalize_client_collection_ids(collection_ids or [], dlna_config),
            "usernames": self.normalize_client_usernames(usernames or []),
        }
        dlna_config.setdefault("clients", []).append(client)
        self._set_dlna_config(dlna_config)
        self._sync_dlna_runtime_safe(restart_service_if_active=True, force_full_rescan=True)
        return client

    def update_client(self, client_id, ip, description="", enabled=True, collection_ids=None, usernames=None):
        client_id = str(client_id or "").strip()
        if not client_id:
            raise ValueError("Brak identyfikatora klienta.")

        dlna_config = self._get_dlna_config_snapshot()
        normalized_ip = self._normalize_dlna_client_ip(ip)
        for item in dlna_config.get("clients") or []:
            if item["id"] != client_id and item["ip"] == normalized_ip:
                raise ValueError("Inny klient używa już tego adresu IP.")

        found = False
        for item in dlna_config.get("clients") or []:
            if item["id"] != client_id:
                continue
            item["ip"] = normalized_ip
            item["description"] = self._normalize_dlna_description(description, max_len=200)
            item["enabled"] = bool(enabled)
            item["collection_ids"] = self.normalize_client_collection_ids(collection_ids or [], dlna_config)
            item["usernames"] = self.normalize_client_usernames(usernames or [])
            found = True
            break

        if not found:
            raise ValueError("Nie znaleziono wskazanego klienta.")

        self._set_dlna_config(dlna_config)
        self._sync_dlna_runtime_safe(restart_service_if_active=True, force_full_rescan=True)

    def delete_client(self, client_id):
        client_id = str(client_id or "").strip()
        if not client_id:
            raise ValueError("Brak identyfikatora klienta.")

        dlna_config = self._get_dlna_config_snapshot()
        before_count = len(dlna_config.get("clients") or [])
        dlna_config["clients"] = [item for item in (dlna_config.get("clients") or []) if item["id"] != client_id]
        if len(dlna_config["clients"]) == before_count:
            raise ValueError("Nie znaleziono wskazanego klienta.")

        self._set_dlna_config(dlna_config)
        self._sync_dlna_runtime_safe(restart_service_if_active=True, force_full_rescan=True)

    def create_media_rule(self, kind, storage_kind, relative_path, collection_ids=None, enabled=True):
        dlna_config = self._get_dlna_config_snapshot()
        normalized_kind = str(kind or "").strip().lower()
        if normalized_kind not in ("file", "folder"):
            raise ValueError("Nieobsługiwany typ wpisu DLNA.")

        normalized_storage_kind = self._normalize_storage_kind(storage_kind or "video")
        normalized_path = self._safe_relative_download_path(relative_path)
        if not normalized_path:
            raise ValueError("Ścieżka pliku lub folderu jest nieprawidłowa.")

        for item in dlna_config.get("media_rules") or []:
            if (
                item["kind"] == normalized_kind
                and item["storage_kind"] == normalized_storage_kind
                and item["relative_path"] == normalized_path
            ):
                raise ValueError("Takie medium jest już dodane do DLNA.")

        rule = {
            "id": uuid.uuid4().hex,
            "kind": normalized_kind,
            "storage_kind": normalized_storage_kind,
            "relative_path": normalized_path,
            "enabled": bool(enabled),
            "collection_ids": self.normalize_media_rule_collection_ids(collection_ids or [], dlna_config),
        }
        dlna_config.setdefault("media_rules", []).append(rule)
        self._set_dlna_config(dlna_config)
        self._sync_dlna_runtime_safe(restart_service_if_active=True, force_full_rescan=True)
        return rule

    def update_media_rule(self, rule_id, collection_ids=None, enabled=True):
        rule_id = str(rule_id or "").strip()
        if not rule_id:
            raise ValueError("Brak identyfikatora wpisu DLNA.")

        dlna_config = self._get_dlna_config_snapshot()
        found = False
        for item in dlna_config.get("media_rules") or []:
            if item["id"] != rule_id:
                continue
            item["enabled"] = bool(enabled)
            item["collection_ids"] = self.normalize_media_rule_collection_ids(collection_ids or [], dlna_config)
            found = True
            break

        if not found:
            raise ValueError("Nie znaleziono wskazanego wpisu DLNA.")

        self._set_dlna_config(dlna_config)
        self._sync_dlna_runtime_safe(restart_service_if_active=True, force_full_rescan=True)

    def delete_media_rule(self, rule_id):
        rule_id = str(rule_id or "").strip()
        if not rule_id:
            raise ValueError("Brak identyfikatora wpisu DLNA.")

        dlna_config = self._get_dlna_config_snapshot()
        before_count = len(dlna_config.get("media_rules") or [])
        dlna_config["media_rules"] = [item for item in (dlna_config.get("media_rules") or []) if item["id"] != rule_id]
        if len(dlna_config["media_rules"]) == before_count:
            raise ValueError("Nie znaleziono wskazanego wpisu DLNA.")

        self._set_dlna_config(dlna_config)
        self._sync_dlna_runtime_safe(restart_service_if_active=True, force_full_rescan=True)
