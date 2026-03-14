# -*- coding: utf-8 -*-
"""Database connection (Oracle). Thick mode nếu có Oracle Client, thin mode nếu không."""
import os

import oracledb

from .config import CONN_USER, CONN_PASSWORD, CONN_DSN, ORACLE_CLIENT_DIR


def get_conn():
    if ORACLE_CLIENT_DIR and os.path.isdir(ORACLE_CLIENT_DIR):
        try:
            oracledb.init_oracle_client(lib_dir=ORACLE_CLIENT_DIR)
        except Exception as e:
            if "already been initialized" not in str(e).lower():
                pass  # DPI-1047 etc. -> fallback thin mode
    return oracledb.connect(user=CONN_USER, password=CONN_PASSWORD, dsn=CONN_DSN)
