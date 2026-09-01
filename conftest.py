"""
Pytest bootstrap.

Tests must not depend on the developer's local .env. With API_KEY set
there, require_api_key rejects every request with 401 before any test's
own assertions run. CI has no .env either, so clearing these keeps local
and CI behaviour identical.
"""
import os

os.environ["API_KEY"] = ""
os.environ["ADMIN_API_KEY"] = ""
