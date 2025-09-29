import os
from functools import lru_cache
from googleapiclient.discovery import build
from .auth import get_google_credentials

@lru_cache(maxsize=1)
def sheets():
    creds = get_google_credentials()
    return build("sheets", "v4", credentials=creds)

@lru_cache(maxsize=1)
def drive():
    creds = get_google_credentials()
    return build("drive", "v3", credentials=creds)

@lru_cache(maxsize=1)
def docs():
    creds = get_google_credentials()
    return build("docs", "v1", credentials=creds)

@lru_cache(maxsize=1)
def calendar():
    creds = get_google_credentials()
    return build("calendar", "v3", credentials=creds)
