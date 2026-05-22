# -*- coding: utf-8 -*-
"""
Built-in API token for external apps (never stored in auth.db sessions).

- Not revoked by logout, session TTL, or permanent-token revoke.
- Override via env AUTH_STATIC_API_TOKEN (set empty to disable).
- Maps to user AUTH_STATIC_API_USERNAME (default admin).

Usage from another app:
  Authorization: Bearer <SFC_VIEW_STATIC_API_TOKEN>
  or header: X-SFC-View-Api-Key: <SFC_VIEW_STATIC_API_TOKEN>
"""

# Change this string only if you intentionally rotate the shared secret.
SFC_VIEW_STATIC_API_TOKEN = "ForTesting"

# SFIS user identity for repair/execute (admin = all debug pages).
SFC_VIEW_STATIC_API_USERNAME = "admin"
