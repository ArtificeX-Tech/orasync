from pathlib import Path
import traceback

from krita import Krita

from .extension import OrasyncPocExtension

LOG_PATH = Path.home() / ".config" / "orasync" / "krita-poc-loader.log"


def _log(message):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(message + "\n")


try:
    _log("orasync_poc: importing")
    Krita.instance().addExtension(OrasyncPocExtension(Krita.instance()))
    _log("orasync_poc: extension registered")
except Exception:
    _log("orasync_poc: import failed")
    _log(traceback.format_exc())
    raise
