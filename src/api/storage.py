"""On-disk session store for uploaded IMU CSVs.

Each uploaded session is assigned a UUID and stored under
`api_storage/sessions/{session_id}/` alongside its optional annotations
file. A JSON metadata index is kept at `api_storage/sessions.json` and
loaded on startup.
"""
from __future__ import annotations

import json
import os
import shutil
import threading
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional

_HERE = os.path.dirname(__file__)
STORAGE_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "api_storage"))
SESSIONS_DIR = os.path.join(STORAGE_ROOT, "sessions")
INDEX_PATH = os.path.join(STORAGE_ROOT, "sessions.json")


@dataclass
class SessionRecord:
    session_id: str
    filename: str
    csv_path: str
    annotations_path: Optional[str]
    lifter: Optional[str]
    load_lb: Optional[int]
    n_reps_prescribed: Optional[int]
    fs_hz: float
    duration_s: float
    n_samples: int
    uploaded_at: str

    @property
    def has_annotations(self) -> bool:
        return self.annotations_path is not None


class SessionStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: Dict[str, SessionRecord] = {}
        os.makedirs(SESSIONS_DIR, exist_ok=True)
        self._load_index()

    def _load_index(self) -> None:
        if not os.path.exists(INDEX_PATH):
            return
        with open(INDEX_PATH, "r") as f:
            raw = json.load(f)
        for sid, rec in raw.items():
            if not os.path.exists(rec["csv_path"]):
                continue
            self._records[sid] = SessionRecord(**rec)

    def _persist_index(self) -> None:
        payload = {sid: asdict(r) for sid, r in self._records.items()}
        tmp = INDEX_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp, INDEX_PATH)

    def create(self, *, filename: str, csv_bytes: bytes,
               annotations_bytes: Optional[bytes],
               lifter: Optional[str], load_lb: Optional[int],
               n_reps_prescribed: Optional[int],
               fs_hz: float, duration_s: float, n_samples: int) -> SessionRecord:
        session_id = str(uuid.uuid4())
        session_dir = os.path.join(SESSIONS_DIR, session_id)
        os.makedirs(session_dir, exist_ok=True)

        safe_name = os.path.basename(filename) or "session.csv"
        csv_path = os.path.join(session_dir, safe_name)
        with open(csv_path, "wb") as f:
            f.write(csv_bytes)

        ann_path: Optional[str] = None
        if annotations_bytes is not None:
            ann_name = safe_name.replace(".csv", "") + "_annotations.csv"
            ann_path = os.path.join(session_dir, ann_name)
            with open(ann_path, "wb") as f:
                f.write(annotations_bytes)

        record = SessionRecord(
            session_id=session_id,
            filename=safe_name,
            csv_path=csv_path,
            annotations_path=ann_path,
            lifter=lifter,
            load_lb=load_lb,
            n_reps_prescribed=n_reps_prescribed,
            fs_hz=float(fs_hz),
            duration_s=float(duration_s),
            n_samples=int(n_samples),
            uploaded_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        with self._lock:
            self._records[session_id] = record
            self._persist_index()
        return record

    def get(self, session_id: str) -> Optional[SessionRecord]:
        return self._records.get(session_id)

    def list(self) -> List[SessionRecord]:
        return sorted(self._records.values(),
                      key=lambda r: r.uploaded_at, reverse=True)

    def delete(self, session_id: str) -> bool:
        with self._lock:
            rec = self._records.pop(session_id, None)
            if rec is None:
                return False
            session_dir = os.path.join(SESSIONS_DIR, session_id)
            if os.path.isdir(session_dir):
                shutil.rmtree(session_dir, ignore_errors=True)
            self._persist_index()
            return True


_store: Optional[SessionStore] = None


def get_store() -> SessionStore:
    global _store
    if _store is None:
        _store = SessionStore()
    return _store
