import os
import unittest
from unittest.mock import patch

import linkedsky


POST = ("Read this article", "#python #testing", "https://example.com/article", "An article")
CREDENTIALS = {
    "LINKEDIN_AUTHOR": "urn:li:person:test",
    "LINKEDIN_TOKEN": "test-token",
    "BSKY_USER": "test.example.com",
    "BSKY_PASS": "test-password",
}


class LinkedSkyTests(unittest.TestCase):
    def test_main_posts_only_to_selected_services(self):
        for linkedin in (True, False):
            for bluesky in (True, False):
                with self.subTest(linkedin=linkedin, bluesky=bluesky):
                    with (
                        patch.dict(os.environ, CREDENTIALS, clear=True),
                        patch("linkedsky.load_dotenv"),
                        patch("linkedsky.get_post_parts", return_value=POST),
                        patch("linkedsky.get_prompt", side_effect=[linkedin, bluesky]) as prompt,
                        patch("linkedsky.post_to_linkedin") as post_linkedin,
                        patch("linkedsky.post_to_bluesky") as post_bluesky,
                    ):
                        linkedsky.main()

                    self.assertEqual(
                        [call.kwargs["prompt"] for call in prompt.call_args_list],
                        ["Post to LinkedIn", "Post to Bluesky"],
                    )
                    for selected, post in ((linkedin, post_linkedin), (bluesky, post_bluesky)):
                        if selected:
                            post.assert_called_once_with(*POST)
                        else:
                            post.assert_not_called()

    def test_main_stops_before_prompting_when_a_credential_is_missing(self):
        for missing in CREDENTIALS:
            with self.subTest(missing=missing):
                credentials = {name: value for name, value in CREDENTIALS.items() if name != missing}
                with (
                    patch.dict(os.environ, credentials, clear=True),
                    patch("linkedsky.load_dotenv"),
                    patch("builtins.input") as prompt,
                ):
                    with self.assertRaisesRegex(linkedsky.MissingEnvVarError, missing):
                        linkedsky.main()
                prompt.assert_not_called()

    def test_get_prompt_retries_invalid_input_and_accepts_mixed_case(self):
        for answer, expected in (("YeS", True), ("NO", False)):
            with self.subTest(answer=answer):
                with patch("builtins.input", side_effect=["maybe", answer]) as prompt:
                    self.assertIs(linkedsky.get_prompt("Post?"), expected)
                self.assertEqual(prompt.call_count, 2)

    def test_get_post_parts_retries_an_empty_answer_and_preserves_field_order(self):
        with patch("builtins.input", side_effect=["", *POST]) as prompt:
            self.assertEqual(linkedsky.get_post_parts(), POST)
        self.assertEqual(prompt.call_count, 5)

    def test_post_to_linkedin_sends_article_payload_and_bearer_token(self):
        with (
            patch.dict(os.environ, CREDENTIALS, clear=True),
            patch("linkedsky.requests.post") as post,
        ):
            linkedsky.post_to_linkedin(*POST)

        post.assert_called_once()
        request = post.call_args.kwargs
        self.assertEqual(request["url"], "https://api.linkedin.com/rest/posts")
        self.assertEqual(request["headers"]["Authorization"], "Bearer test-token")
        self.assertEqual(request["headers"]["Content-Type"], "application/json")
        self.assertEqual(request["headers"]["LinkedIn-Version"], "202611")
        self.assertEqual(request["headers"]["X-Restli-Protocol-Version"], "2.0.0")
        payload = request["json"]
        self.assertEqual(payload["author"], CREDENTIALS["LINKEDIN_AUTHOR"])
        self.assertEqual(payload["lifecycleState"], "PUBLISHED")
        self.assertEqual(payload["visibility"], "PUBLIC")
        self.assertEqual(payload["distribution"]["feedDistribution"], "MAIN_FEED")
        self.assertEqual(payload["commentary"], "Read this article #python #testing")
        self.assertEqual(payload["content"], {"article": {"source": POST[2], "title": POST[3]}})

    def test_linkedin_escapes_literal_commentary_and_preserves_hashtags(self):
        payload = linkedsky.create_linkedin_post(r"Read (this) @home | C:\docs", "#python", POST[2], POST[3])
        self.assertEqual(payload["commentary"], r"Read \(this\) \@home \| C:\\docs #python")

    def test_post_to_bluesky_sends_article_embed_and_hashtag_facets(self):
        with (
            patch.dict(os.environ, CREDENTIALS, clear=True),
            patch("linkedsky.Client", autospec=True) as client_class,
        ):
            linkedsky.post_to_bluesky(*POST)

        client = client_class.return_value
        client.login.assert_called_once_with(login="test.example.com", password="test-password")
        client.send_post.assert_called_once()
        post = client.send_post.call_args.kwargs
        self.assertEqual(post["langs"], ["en-US"])
        self.assertEqual(post["embed"].external.uri, POST[2])
        self.assertEqual(post["embed"].external.title, POST[3])
        text = post["text"].build_text()
        self.assertEqual(text, "Read this article #python #testing")
        facets = post["text"].build_facets()
        self.assertEqual([facet.features[0].tag for facet in facets], ["python", "testing"])
        text_bytes = text.encode("utf-8")
        self.assertEqual(
            [text_bytes[facet.index.byte_start:facet.index.byte_end] for facet in facets],
            [b"#python", b"#testing"],
        )
