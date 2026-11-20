import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
from urllib.parse import urlsplit

from requests import HTTPError

from linkedsky import load_dotenv, post_to_bluesky, post_to_linkedin
from post_limits import POST_LIMITS, PostValidationUnavailable, validate_post_lengths


HOST = "127.0.0.1"
ASSETS = Path(__file__).with_name("web")
ASSET_ROUTES = {
    "/": ("index.html", "text/html"),
    "/styles.css": ("styles.css", "text/css"),
    "/app.js": ("app.js", "text/javascript"),
}
CREDENTIALS = {
    "linkedin": ("LINKEDIN_AUTHOR", "LINKEDIN_TOKEN"),
    "bluesky": ("BSKY_USER", "BSKY_PASS"),
}
FIELDS = ("description", "hashtags", "url", "title")
MAX_BODY_BYTES = 32_768


def configured_platforms():
    return {
        platform: all(os.environ.get(name, "").strip() for name in names)
        for platform, names in CREDENTIALS.items()
    }


def linkedin_error_message(response):
    status = response.status_code
    details = {}
    reason = ""
    if status in (HTTPStatus.UNAUTHORIZED, HTTPStatus.BAD_REQUEST, HTTPStatus.UNPROCESSABLE_ENTITY):
        try:
            parsed = response.json()
        except (ValueError, RecursionError):
            parsed = None
        if isinstance(parsed, dict):
            details = parsed
            if isinstance(details.get("message"), str):
                reason = details["message"]

    if status == HTTPStatus.UNAUTHORIZED:
        if details.get("serviceErrorCode") == 65602 or "expired" in reason.lower():
            return "The LinkedIn access token has expired (HTTP 401). Update LINKEDIN_TOKEN in .env and restart LinkedSky."
        return "LinkedIn rejected authentication (HTTP 401). Check the access token and LINKEDIN_AUTHOR."
    if status == HTTPStatus.FORBIDDEN:
        return "LinkedIn denied posting (HTTP 403). Check that the token has w_member_social and matches LINKEDIN_AUTHOR."
    if status in (HTTPStatus.BAD_REQUEST, HTTPStatus.UNPROCESSABLE_ENTITY):
        if status == HTTPStatus.UNPROCESSABLE_ENTITY and "content is a duplicate of" in reason.lower():
            return "LinkedIn flagged this post as a duplicate (HTTP 422). Check your feed before trying again."
        token = os.getenv("LINKEDIN_TOKEN")
        if token:
            reason = reason.replace(token, "[redacted]")
        reason = " ".join(reason.split())
        if len(reason) > 500:
            reason = reason[:499] + "…"
        summary = f"LinkedIn rejected the post (HTTP {status})."
        if reason:
            return f"{summary} {reason}"
        return f"{summary} LinkedIn did not provide a reason. Check the article details and your recent posts."
    if status == HTTPStatus.TOO_MANY_REQUESTS:
        return "LinkedIn reached a posting or API limit (HTTP 429). Try again later."
    return f"LinkedIn publishing failed (HTTP {status}). Check your LinkedIn feed before retrying."


def publish(payload):
    if not isinstance(payload, dict) or any(not isinstance(payload.get(field), str) for field in FIELDS):
        raise ValueError("Enter the post text, hashtags, article URL, and article title.")
    description, hashtags, url, title = (payload[field].strip() for field in FIELDS)
    if not description or not title:
        raise ValueError("Post text and article title are required.")
    try:
        link = urlsplit(url)
    except ValueError:
        raise ValueError("Enter a valid HTTP or HTTPS article URL.") from None
    if link.scheme not in {"http", "https"} or not link.hostname or any(char.isspace() for char in url):
        raise ValueError("Enter a valid HTTP or HTTPS article URL.")

    platforms = payload.get("platforms")
    if not isinstance(platforms, list) or not platforms:
        raise ValueError("Select a platform to publish to.")
    if any(not isinstance(platform, str) or platform not in CREDENTIALS for platform in platforms):
        raise ValueError("Choose LinkedIn or Bluesky.")

    normalized_tags = " ".join(f"#{tag.strip('#')}" for tag in hashtags.split() if tag.strip("#"))
    platforms = dict.fromkeys(platforms)
    for platform in platforms:
        validate_post_lengths(platform, description, normalized_tags, url)

    configured = configured_platforms()
    results = {}
    for platform in platforms:
        if not configured[platform]:
            results[platform] = {"ok": False, "message": "Add this platform’s credentials to .env."}
            continue
        try:
            if platform == "linkedin":
                post_to_linkedin(description, normalized_tags, url, title).raise_for_status()
            else:
                post_to_bluesky(description, normalized_tags, url, title)
        except Exception as error:
            if platform == "linkedin" and isinstance(error, HTTPError) and error.response is not None:
                logging.warning("LinkedIn publish failed with HTTP %s", error.response.status_code)
                message = linkedin_error_message(error.response)
            else:
                logging.warning("%s publish failed (%s)", platform, type(error).__name__)
                message = "Publishing failed. Check the account or connection."
            results[platform] = {"ok": False, "message": message}
        else:
            results[platform] = {"ok": True, "message": "Published."}
    return results


class WebHandler(BaseHTTPRequestHandler):
    timeout = 10

    def do_GET(self):
        if not self.check_host():
            return
        if self.path == "/api/platforms":
            self.send_json(HTTPStatus.OK, {**configured_platforms(), "limits": POST_LIMITS})
        elif self.path in ASSET_ROUTES:
            filename, content_type = ASSET_ROUTES[self.path]
            self.send_body(HTTPStatus.OK, content_type, (ASSETS / filename).read_bytes())
        else:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Page not found."})

    def do_POST(self):
        if not self.check_host():
            return
        if self.path != "/api/publish":
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Page not found."})
            return
        if self.headers.get("Origin") != f"http://{HOST}:{self.server.server_port}":
            self.send_json(HTTPStatus.FORBIDDEN, {"error": "Open the composer from its local address."})
            return
        if self.headers.get_content_type() != "application/json":
            self.send_json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "Expected a JSON request."})
            return
        length = self.headers.get("Content-Length", "")
        if not length.isascii() or not length.isdecimal() or len(length) > 5 or int(length) > MAX_BODY_BYTES:
            self.send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "The request is too large or missing a body."})
            return
        try:
            payload = json.loads(self.rfile.read(int(length)))
        except (ValueError, RecursionError):
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON request."})
            return
        try:
            results = publish(payload)
        except PostValidationUnavailable as error:
            self.send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(error)})
            return
        except ValueError as error:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return
        self.send_json(HTTPStatus.OK, {"results": results})

    def check_host(self):
        if self.headers.get("Host") == f"{HOST}:{self.server.server_port}":
            return True
        self.send_json(HTTPStatus.FORBIDDEN, {"error": "Open the composer from its local address."})
        return False

    def send_json(self, status, data):
        self.send_body(status, "application/json", json.dumps(data).encode("utf-8"))

    def send_body(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        )
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser(description="Run the LinkedSky web composer locally.")
    parser.add_argument("--port", type=int, default=8765, help="Local port (default: 8765)")
    args = parser.parse_args()
    load_dotenv()
    with ThreadingHTTPServer((HOST, args.port), WebHandler) as server:
        print(f"LinkedSky is ready at http://{HOST}:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
