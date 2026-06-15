from __future__ import annotations

import os

import uvicorn

from app.config import settings


def main() -> None:
    host = os.environ.get("APP_HOST", settings.APP_HOST)
    port = int(os.environ.get("APP_PORT", settings.APP_PORT))
    reload = os.environ.get("APP_RELOAD", "0") not in ("0", "false", "False", "")
    uvicorn.run("app.main:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
