"""Pakiet aplikacji Flask Downloader."""

import os
import time

from flask import Flask

from .paths import PROJECT_ROOT


def create_app():
    from .legacy_app import configure_app

    app = Flask(
        __name__,
        template_folder=os.path.join(PROJECT_ROOT, "templates"),
        static_folder=os.path.join(PROJECT_ROOT, "static"),
    )
    app.config["ASSET_VERSION"] = str(int(time.time()))

    @app.context_processor
    def inject_asset_version():
        return {"asset_version": app.config.get("ASSET_VERSION", "1")}

    return configure_app(app)


__all__ = ["create_app"]
