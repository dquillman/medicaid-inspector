"""
JSON-backed store for saved search/filter configurations.
"""
import json
import time
import uuid
import pathlib
from typing import Optional

_SAVED_SEARCHES_FILE = pathlib.Path(__file__).parent.parent / "saved_searches.json"

_saved_searches: list[dict] = []


def _save_to_disk() -> None:
    try:
        _SAVED_SEARCHES_FILE.write_text(
            json.dumps({"searches": _saved_searches}, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"[saved_search_store] Could not save: {e}")


def load_saved_searches_from_disk() -> None:
    global _saved_searches
    try:
        if not _SAVED_SEARCHES_FILE.exists():
            return
        raw = json.loads(_SAVED_SEARCHES_FILE.read_text(encoding="utf-8"))
        _saved_searches = raw.get("searches", [])
        print(f"[saved_search_store] Loaded {len(_saved_searches)} saved searches from disk")
    except Exception as e:
        print(f"[saved_search_store] Could not load: {e}")


def list_saved_searches() -> list[dict]:
    return sorted(_saved_searches, key=lambda s: -s.get("created_at", 0))


def create_saved_search(name: str, filters: dict) -> dict:
    search = {
        "id": str(uuid.uuid4()),
        "name": name,
        "filters": filters,
        "created_at": time.time(),
    }
    _saved_searches.append(search)
    _save_to_disk()
    return search


def delete_saved_search(search_id: str) -> bool:
    global _saved_searches
    before = len(_saved_searches)
    _saved_searches = [s for s in _saved_searches if s["id"] != search_id]
    if len(_saved_searches) < before:
        _save_to_disk()
        return True
    return False
