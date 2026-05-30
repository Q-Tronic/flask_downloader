#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from flask_downloader import create_app
from flask_downloader.config import APP_HOST, APP_PORT


app = create_app()


if __name__ == "__main__":
    app.run(host=APP_HOST, port=APP_PORT, debug=False, threaded=True)
