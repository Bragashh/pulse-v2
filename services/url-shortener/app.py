"""
URL shortener service.

Two endpoints:
  POST /shorten — body { "url": "..." } returns { "short": "abc123", "url": "..." }
  GET  /<short> — redirects to the long URL or returns 404

Stores mappings in Redis. Key format: short:<code> → <long_url>
"""

import os
import secrets
import string
import redis
from flask import Flask, jsonify, request, redirect


REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))

app = Flask(__name__)

# Redis client — connects lazily on first use
r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)


SHORT_CODE_LENGTH = 7
SHORT_CODE_ALPHABET = string.ascii_letters + string.digits


def generate_short_code() -> str:
    """Generate a random 7-character short code."""
    return ''.join(secrets.choice(SHORT_CODE_ALPHABET) for _ in range(SHORT_CODE_LENGTH))


@app.route('/health')
def health():
    """Health check — also verifies Redis is reachable."""
    try:
        r.ping()
        return jsonify({"status": "ok", "redis": "connected"})
    except redis.exceptions.ConnectionError:
        return jsonify({"status": "degraded", "redis": "unreachable"}), 503


@app.route('/')
def index():
    return jsonify({"message": "URL shortener — POST /shorten with a URL"})


@app.route('/shorten', methods=['POST'])
def shorten():
    """Create a short code for a long URL."""
    data = request.get_json(silent=True) or {}
    url = data.get('url', '').strip()

    if not url:
        return jsonify({"error": "url is required"}), 400

    if not (url.startswith('http://') or url.startswith('https://')):
        return jsonify({"error": "url must start with http:// or https://"}), 400

    # Generate a unique short code (retry if collision — vanishingly rare with 7 chars)
    for _ in range(5):
        code = generate_short_code()
        if not r.exists(f"short:{code}"):
            r.set(f"short:{code}", url)
            return jsonify({"short": code, "url": url}), 201

    return jsonify({"error": "could not generate unique short code"}), 500


@app.route('/<code>')
def redirect_short(code):
    """Look up a short code and redirect to the long URL."""
    long_url = r.get(f"short:{code}")
    if long_url is None:
        return jsonify({"error": "short code not found"}), 404
    return redirect(long_url, code=302)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)