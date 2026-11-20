from email.message import Message
from http import HTTPStatus
from io import BytesIO
import json
import os
import sys
import unittest
from unittest.mock import Mock, patch

from requests import HTTPError, Response

from linkedsky_web import WebHandler, configured_platforms, publish


POST = {
    "description": " An article worth reading ",
    "hashtags": "#python    web",
    "url": "https://example.com/article",
    "title": "Example article",
    "platforms": ["linkedin", "bluesky"],
}
CREDENTIALS = {
    "LINKEDIN_AUTHOR": "urn:li:person:test",
    "LINKEDIN_TOKEN": "test-token",
    "BSKY_USER": "test.example.com",
    "BSKY_PASS": "test-password",
}


class WebPublishingTests(unittest.TestCase):
    def test_missing_grapheme_dependency_returns_a_setup_error_before_publishing(self):
        body = json.dumps(POST).encode("utf-8")
        handler = Mock(spec=WebHandler)
        handler.check_host.return_value = True
        handler.server = Mock(server_port=8765)
        handler.path = "/api/publish"
        handler.headers = Message()
        handler.headers["Origin"] = "http://127.0.0.1:8765"
        handler.headers["Content-Type"] = "application/json"
        handler.headers["Content-Length"] = str(len(body))
        handler.rfile = BytesIO(body)
        with (
            patch("post_limits.unicodedata", object()),
            patch.dict(sys.modules, {"regex": None}),
            patch("linkedsky_web.post_to_linkedin") as linkedin,
            patch("linkedsky_web.post_to_bluesky") as bluesky,
        ):
            WebHandler.do_POST(handler)

        linkedin.assert_not_called()
        bluesky.assert_not_called()
        handler.send_json.assert_called_once()
        status, payload = handler.send_json.call_args.args
        self.assertEqual(status, HTTPStatus.SERVICE_UNAVAILABLE)
        self.assertIn("python -m pip install -r requirements.txt", payload["error"])

    def test_configuration_requires_both_values_for_each_platform(self):
        with patch.dict(os.environ, {**CREDENTIALS, "BSKY_PASS": " "}, clear=True):
            self.assertEqual(configured_platforms(), {"linkedin": True, "bluesky": False})

    def test_invalid_drafts_are_rejected_before_publishing(self):
        for changes in ({"description": " "}, {"url": "file:///tmp/article"}, {"platforms": []}):
            with self.subTest(changes=changes):
                with (
                    patch("linkedsky_web.post_to_linkedin") as linkedin,
                    patch("linkedsky_web.post_to_bluesky") as bluesky,
                    self.assertRaises(ValueError),
                ):
                    publish({**POST, **changes})
                linkedin.assert_not_called()
                bluesky.assert_not_called()

    def test_publishing_reports_each_platform_and_sends_normalized_content_once(self):
        with (
            patch.dict(os.environ, CREDENTIALS, clear=True),
            patch("linkedsky_web.post_to_linkedin") as linkedin,
            patch("linkedsky_web.post_to_bluesky") as bluesky,
            self.assertLogs(level="WARNING"),
        ):
            linkedin.return_value.raise_for_status.side_effect = HTTPError("private upstream details")
            results = publish({**POST, "platforms": ["linkedin", "bluesky", "bluesky"]})

        for publisher in (linkedin, bluesky):
            publisher.assert_called_once_with("An article worth reading", "#python #web", POST["url"], POST["title"])
        self.assertFalse(results["linkedin"]["ok"])
        self.assertNotIn("private upstream details", results["linkedin"]["message"])
        self.assertTrue(results["bluesky"]["ok"])

    def test_unconfigured_platform_cannot_publish(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("linkedsky_web.post_to_bluesky") as bluesky,
        ):
            results = publish({**POST, "platforms": ["bluesky"]})
        self.assertFalse(results["bluesky"]["ok"])
        bluesky.assert_not_called()

    def test_linkedin_auth_failures_report_status_without_exposing_api_details(self):
        for status, details, expected in (
            (401, b'{"serviceErrorCode":65602,"message":"private upstream details"}', "expired (HTTP 401)"),
            (401, b"Unexpected response from LinkedIn", "rejected authentication (HTTP 401)"),
            (403, b'{"message":"private upstream details"}', "w_member_social"),
        ):
            with self.subTest(status=status, expected=expected):
                response = Response()
                response.status_code = status
                response._content = details
                with (
                    patch.dict(os.environ, CREDENTIALS, clear=True),
                    patch("linkedsky_web.post_to_linkedin", return_value=response),
                    self.assertLogs(level="WARNING"),
                ):
                    result = publish({**POST, "platforms": ["linkedin"]})["linkedin"]
                self.assertFalse(result["ok"])
                self.assertIn(expected, result["message"])
                self.assertNotIn("private upstream details", result["message"])

    def test_linkedin_reports_duplicate_and_invalid_field_rejections(self):
        for body, expected in (
            (b'{"message":"Content is a duplicate of urn:li:share:123"}', "flagged this post as a duplicate"),
            (b'{"message":"Article title exceeds its allowed length. test-token"}', "Article title exceeds its allowed length. [redacted]"),
            (b"upstream HTML", "LinkedIn did not provide a reason"),
        ):
            with self.subTest(expected=expected):
                response = Response()
                response.status_code = 422
                response._content = body
                with (
                    patch.dict(os.environ, CREDENTIALS, clear=True),
                    patch("linkedsky_web.post_to_linkedin", return_value=response),
                    self.assertLogs(level="WARNING") as logs,
                ):
                    result = publish({**POST, "platforms": ["linkedin"]})["linkedin"]
                self.assertFalse(result["ok"])
                self.assertIn("HTTP 422", result["message"])
                self.assertIn(expected, result["message"])
                self.assertNotIn(CREDENTIALS["LINKEDIN_TOKEN"], result["message"])
                self.assertNotIn(CREDENTIALS["LINKEDIN_TOKEN"], " ".join(logs.output))

    def test_length_check_applies_to_selected_platforms_before_sending(self):
        draft = {**POST, "description": "a" * 299, "hashtags": "tag"}
        with (
            patch.dict(os.environ, CREDENTIALS, clear=True),
            patch("linkedsky_web.post_to_linkedin") as linkedin,
            patch("linkedsky_web.post_to_bluesky") as bluesky,
        ):
            with self.assertRaisesRegex(ValueError, "Bluesky post text"):
                publish(draft)
            linkedin.assert_not_called()
            bluesky.assert_not_called()

            results = publish({**draft, "platforms": ["linkedin"]})
            self.assertTrue(results["linkedin"]["ok"])
            linkedin.assert_called_once_with(draft["description"], "#tag", POST["url"], POST["title"])
            bluesky.assert_not_called()
