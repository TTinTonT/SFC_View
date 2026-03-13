# -*- coding: utf-8 -*-
"""Central application configuration: paths, Flask, SFC, export formatting."""

import os

from config.site_defaults import get_default
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

FLASK_HOST = os.environ.get("FLASK_HOST", get_default("FLASK_HOST"))
FLASK_PORT = int(os.environ.get("FLASK_PORT", get_default("FLASK_PORT")))
FLASK_DEBUG = os.environ.get("FLASK_DEBUG", get_default("FLASK_DEBUG")).lower() in ("1", "true", "yes")

DISPO_XLSX_HEADER_FILL = os.environ.get("DISPO_XLSX_HEADER_FILL", "E8D5B7")
DISPO_XLSX_DATA_FILL = os.environ.get("DISPO_XLSX_DATA_FILL", "FFF8E7")

SFC_BASE_URL = os.environ.get("SFC_BASE_URL", get_default("SFC_BASE_URL")).rstrip("/")
SFC_ASSY_INFO_URL = os.environ.get(
    "SFC_ASSY_INFO_URL", SFC_BASE_URL + "/L10_Report/NewAssembly/AssyInfo.jsp"
)
SFC_USER = os.environ.get("SFC_USER", get_default("SFC_USER"))
SFC_PWD = os.environ.get("SFC_PWD", get_default("SFC_PWD"))
SFC_GROUP_NAME = os.environ.get("SFC_GROUP_NAME", get_default("SFC_GROUP_NAME"))
SFC_SESSION_TTL_SECONDS = int(os.environ.get("SFC_SESSION_TTL_SECONDS", get_default("SFC_SESSION_TTL_SECONDS")))
VALID_LOCATION = os.environ.get("VALID_LOCATION", get_default("VALID_LOCATION"))
SFC_INCLUDE_RACK = (os.environ.get("SFC_INCLUDE_RACK", get_default("SFC_INCLUDE_RACK")) or "").strip().upper() or None

EXTEND_HOURS = get_extend_hours()
CA_TZ = get_ca_tz()
STATIONS_ORDER = get_stations_order()
TOP_K_ERRORS_DEFAULT = get_top_k_errors_default()

# Auth (debug area)
AUTH_DB_PATH = os.environ.get("AUTH_DB_PATH") or os.path.join(ANALYTICS_CACHE_DIR, "auth.db")
AUTH_SESSION_TTL_MINUTES = int(os.environ.get("AUTH_SESSION_TTL_MINUTES", get_default("AUTH_SESSION_TTL_MINUTES") or "30"))
SMTP_HOST = os.environ.get("SMTP_HOST", get_default("SMTP_HOST") or "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", get_default("SMTP_PORT") or "587"))
SMTP_USER = os.environ.get("SMTP_USER", get_default("SMTP_USER") or "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", get_default("SMTP_PASSWORD") or "")
SMTP_USE_TLS = (os.environ.get("SMTP_USE_TLS", get_default("SMTP_USE_TLS") or "true")).lower() in ("1", "true", "yes")
