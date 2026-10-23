import os

if not os.environ.get("APP_PASSWORD") or not os.environ.get("SECRET_KEY"):
    raise RuntimeError("APP_PASSWORD and SECRET_KEY must be set for online hosting.")

from app import app, start_scheduler

start_scheduler()
