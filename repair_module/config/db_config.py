# -*- coding: utf-8 -*-
"""Oracle connection settings. Override before use in production."""
import os

CONN_USER = "sfis1"
CONN_PASSWORD = "sfis1"
CONN_DSN = "10.16.137.112:1526/SJSFC2DB"
ORACLE_CLIENT_DIR = os.path.join(os.path.expanduser("~"), "Downloads", "instantclient_23_0")
