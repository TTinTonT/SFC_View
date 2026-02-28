# -*- coding: utf-8 -*-
"""Central application configuration: paths, Flask, SFC, export formatting."""

import os

from config.analytics_config import (
    get_ca_tz,
    get_extend_hours,
    get_stations_order,
    get_top_k_errors_default,
)

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANALYTICS_CACHE_DIR = os.path.join(APP_DIR, "analytics_cache")
TEMPLATES_DIR = os.path.join(APP_DIR, "templates")

SKU_SUMMARY_TEMPLATE_PATH = os.path.join(TEMPLATES_DIR, "SKU_Summary.xlsx")
TRAY_SUMMARY_TEMPLATE_PATH = os.path.join(TEMPLATES_DIR, "Tray_Summary_Template.xlsx")
SKU_DISPO_TEMPLATE_PATH = os.path.join(TEMPLATES_DIR, "SKU_Dispo.xlsx")

FLASK_HOST = os.environ.get("FLASK_HOST", "0.0.0.0")
FLASK_PORT = int(os.environ.get("FLASK_PORT", "5556"))
FLASK_DEBUG = os.environ.get("FLASK_DEBUG", "true").lower() in ("1", "true", "yes")

DISPO_XLSX_HEADER_FILL = os.environ.get("DISPO_XLSX_HEADER_FILL", "E8D5B7")
DISPO_XLSX_DATA_FILL = os.environ.get("DISPO_XLSX_DATA_FILL", "FFF8E7")

SFC_BASE_URL = os.environ.get("SFC_BASE_URL", "http://10.16.137.110").rstrip("/")
SFC_USER = os.environ.get("SFC_USER", "SFC")
SFC_PWD = os.environ.get("SFC_PWD", "EPD2TJW")
SFC_GROUP_NAME = os.environ.get("SFC_GROUP_NAME", "'AST','FCT','FLA','FLB','FLC','FTS','IOT','NVL','PRET','RIN'")
SFC_SESSION_TTL_SECONDS = int(os.environ.get("SFC_SESSION_TTL_SECONDS", str(30 * 60)))

EXTEND_HOURS = get_extend_hours()
CA_TZ = get_ca_tz()
STATIONS_ORDER = get_stations_order()
TOP_K_ERRORS_DEFAULT = get_top_k_errors_default()
