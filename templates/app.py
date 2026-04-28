# app.py - Оптимизированный децентрализованный мессенджер
# Версия: 2.1 (с кэшированием, оптимизацией БД и PoW)

import hashlib
import os
import base64
import logging
import logging.handlers
import sqlite3
import time
import json
import uuid
import threading
from functools import lru_cache, wraps
from contextlib import contextmanager
from typing import List, Dict, Any, Optional, Callable

from flask import Flask, jsonify, request, render_template, session, redirect, url_for, send_from_directory
from mnemonic import Mnemonic
from marshmallow import Schema, fields, ValidationError, post_load
from werkzeug.utils import secure_filename

from crypto_manager import (
    encrypt_message,
    decrypt
