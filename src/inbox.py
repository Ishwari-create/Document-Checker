"""
Live inbox: watches a folder and checks every PDF dropped into it, so a demo can
show a receipt going from a laptop folder to findings on screen in seconds.

Which application a file belongs to:
  1. a sub-folder named after the application number (inbox/1-SYN-2026-0101/receipt.pdf)
  2. otherwise the institute whose name best matches the depositor / institute on the document
  3. otherwise the default application chosen on the Live inbox screen
"""
from __future__ import annotations

import os
import threading
import time
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
INBOX_DIR = Path(os.environ.get("INBOX_DIR", ROOT / "inbox"))


class InboxWatcher:
    def __init__(self, folder: Path, handler: Callable[[Path, bytes, Optional[str]], Dict]):
        self.folder = folder
        self.handler = handler
        self.events: List[Dict] = []
        self.seen: Dict[str, float] = {}
        self.settings = {"default_app": None, "received": None}
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.folder.mkdir(parents=True, exist_ok=True)
        # files already there when the watcher starts are not re-checked
        for p in self.folder.rglob("*.pdf"):
            self.seen[str(p)] = p.stat().st_mtime
        self._thread = threading.Thread(target=self._loop, daemon=True, name="inbox-watcher")
        self._thread.start()

    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def received_date(self) -> date:
        r = self.settings.get("received")
        return date.fromisoformat(r) if r else date.today()

    def _loop(self) -> None:
        while True:
            try:
                for p in sorted(self.folder.rglob("*.pdf")):
                    key, mtime = str(p), p.stat().st_mtime
                    if self.seen.get(key) == mtime:
                        continue
                    size = p.stat().st_size
                    time.sleep(0.4)                      # wait until the copy has finished
                    if p.stat().st_size != size:
                        continue
                    self.seen[key] = mtime
                    sub = p.parent.name if p.parent != self.folder else None
                    t0 = time.time()
                    try:
                        ev = self.handler(p, p.read_bytes(), sub)
                    except Exception as e:                # one bad file must not stop the watcher
                        ev = {"error": f"{type(e).__name__}: {e}"}
                    ev.update(file=p.name, at=datetime.now().strftime("%H:%M:%S"), seconds=round(time.time() - t0, 1))
                    with self._lock:
                        self.events.insert(0, ev)
                        del self.events[50:]
            except Exception:
                pass
            time.sleep(1.0)

    def recent(self) -> List[Dict]:
        with self._lock:
            return list(self.events)
