"""Portable configuration without requiring a dotenv dependency."""
import os
from pathlib import Path
from gemini_review import load_env
ROOT=Path(__file__).resolve().parent
def setting(name,default=''):
    return os.environ.get(name) or load_env(ROOT/'.env').get(name) or default
