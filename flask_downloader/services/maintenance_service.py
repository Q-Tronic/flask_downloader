import threading
import time


class MaintenanceTaskService:
    def __init__(self, tasks_store, tasks_lock, create_task_state, format_ts):
        self._tasks_store = tasks_store
        self._tasks_lock = tasks_lock
        self._create_task_state = create_task_state
        self._format_ts = format_ts

    @staticmethod
    def clamp_progress_percent(value):
        try:
            return max(0.0, min(100.0, float(value)))
        except Exception:
            return None

    @staticmethod
    def get_status_kind(status):
        if status == "running":
            return "queued"
        if status == "success":
            return "success"
        if status == "error":
            return "error"
        return "muted"

    def serialize_task_state(self, task_key, task):
        snapshot = dict(task or {})
        progress_percent = self.clamp_progress_percent(snapshot.get("progress_percent"))
        started_at = float(snapshot.get("started_at") or 0.0)
        finished_at = float(snapshot.get("finished_at") or 0.0)
        status = str(snapshot.get("status") or "idle").strip() or "idle"
        visible = bool(snapshot.get("visible")) or status in ("running", "success", "error")

        return {
            "task_key": task_key,
            "title": str(snapshot.get("title") or "").strip(),
            "status": status,
            "status_kind": self.get_status_kind(status),
            "status_label": str(snapshot.get("status_label") or "").strip() or "Brak aktywnego zadania",
            "progress_percent": progress_percent,
            "detail": str(snapshot.get("detail") or "").strip(),
            "message": str(snapshot.get("message") or "").strip(),
            "started_at": started_at,
            "started_at_text": self._format_ts(started_at) if started_at else "",
            "finished_at": finished_at,
            "finished_at_text": self._format_ts(finished_at) if finished_at else "",
            "visible": visible,
            "active": status == "running",
            "done": status in ("success", "error"),
        }

    def get_task_snapshot(self, task_key):
        with self._tasks_lock:
            task = dict(self._tasks_store.get(task_key) or self._create_task_state(task_key))
        return self.serialize_task_state(task_key, task)

    def get_all_task_snapshots(self):
        with self._tasks_lock:
            raw_tasks = {
                key: dict(value)
                for key, value in self._tasks_store.items()
            }

        return {
            key: self.serialize_task_state(key, value)
            for key, value in raw_tasks.items()
        }

    def update_task_state(self, task_key, **updates):
        with self._tasks_lock:
            task = self._tasks_store.setdefault(task_key, self._create_task_state(task_key))
            task.update(updates)

            if "progress_percent" in updates:
                task["progress_percent"] = self.clamp_progress_percent(task.get("progress_percent"))
            if "visible" not in updates and task.get("status") in ("running", "success", "error"):
                task["visible"] = True

            snapshot = dict(task)

        return self.serialize_task_state(task_key, snapshot)

    def finish_task(self, task_key, ok, message):
        previous = self.get_task_snapshot(task_key)
        progress_percent = previous["progress_percent"]

        if ok:
            progress_percent = 100.0
        elif progress_percent is None:
            progress_percent = 0.0

        return self.update_task_state(
            task_key,
            status="success" if ok else "error",
            status_label="Zakończono powodzeniem" if ok else "Zakończono błędem",
            progress_percent=progress_percent,
            detail=str(message or "").strip(),
            message=str(message or "").strip(),
            finished_at=time.time(),
            visible=True,
        )

    def start_task(self, task_key, title, worker):
        with self._tasks_lock:
            current = dict(self._tasks_store.get(task_key) or self._create_task_state(title))
            if str(current.get("status") or "").strip() == "running":
                return False, self.serialize_task_state(task_key, current)

            self._tasks_store[task_key] = {
                "title": title,
                "status": "running",
                "status_label": "Przygotowanie",
                "progress_percent": 0.0,
                "detail": "Uruchamianie zadania...",
                "started_at": time.time(),
                "finished_at": 0.0,
                "visible": True,
                "message": "",
            }

        def runner():
            try:
                ok, message = worker(
                    lambda **kwargs: self.update_task_state(task_key, **kwargs)
                )
            except Exception as exc:
                ok = False
                message = str(exc) or "Nieznany błąd zadania administracyjnego."

            self.finish_task(task_key, ok, message)

        thread = threading.Thread(
            target=runner,
            name="maintenance-%s" % task_key,
            daemon=True,
        )
        thread.start()

        return True, self.get_task_snapshot(task_key)
