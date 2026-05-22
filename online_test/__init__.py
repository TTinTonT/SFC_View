# -*- coding: utf-8 -*-
"""
Portable Online Test bundle (copy of SFC_View ETF / L10 online-test APIs).

Register in a Flask app::

    from online_test import create_blueprint
    app.register_blueprint(create_blueprint())

See README.md for env vars, static files, and host dependencies (sfis_tool, crabber).
"""

from __future__ import annotations

from flask import Blueprint

from online_test.blueprint import build_blueprint


def create_blueprint() -> Blueprint:
    """Return a Flask Blueprint with the same URL paths as SFC_View online-test + L10 queue."""
    return build_blueprint()
