"""Pakiet aplikacji Flask Downloader."""

from .legacy_app import app


def create_app():
    return app


__all__ = ["app", "create_app"]
