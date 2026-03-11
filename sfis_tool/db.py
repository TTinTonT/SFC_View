# -*- coding: utf-8 -*-
"""Database connection (Oracle). Import config và cung cấp get_conn()."""
import oracledb

from .config import CONN_USER, CONN_PASSWORD, CONN_DSN, ORACLE_CLIENT_DIR


def get_conn():
    try:
        oracledb.init_oracle_client(lib_dir=ORACLE_CLIENT_DIR)
    except oracledb.ProgrammingError as e:
        if "already been initialized" not in str(e).lower():
            raise
    return oracledb.connect(user=CONN_USER, password=CONN_PASSWORD, dsn=CONN_DSN)
