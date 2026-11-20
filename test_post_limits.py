import unittest
from unittest.mock import patch

import linkedsky
from post_limits import PostLengthError, validate_post_lengths


URL = "https://example.com/"


class PostLengthTests(unittest.TestCase):
    def test_linkedin_counts_hashtags_and_the_separator(self):
        validate_post_lengths("linkedin", "a" * 3000, "", URL)
        validate_post_lengths("linkedin", "a" * 2995, "#tag", URL)
        with self.assertRaisesRegex(PostLengthError, "3,000 characters"):
            validate_post_lengths("linkedin", "a" * 2996, "#tag", URL)

    def test_bluesky_counts_graphemes_including_hashtags(self):
        flag = "🇳🇱"
        validate_post_lengths("bluesky", flag * 295, "#tag", URL)
        with self.assertRaisesRegex(PostLengthError, "300 characters"):
            validate_post_lengths("bluesky", flag * 296, "#tag", URL)

    def test_bluesky_applies_the_utf8_budget_even_below_the_character_limit(self):
        family = "👨‍👩‍👧‍👦"  # One grapheme and 25 UTF-8 bytes.
        validate_post_lengths("bluesky", family * 120, "", URL)
        with self.assertRaisesRegex(PostLengthError, "3,000 UTF-8 bytes"):
            validate_post_lengths("bluesky", family * 121, "", URL)

    def test_bluesky_hashtag_limits_exclude_the_hash_sign(self):
        validate_post_lengths("bluesky", "Article", "#" + "é" * 64, URL)
        with self.assertRaisesRegex(PostLengthError, "hashtag 1 exceeds 64 characters"):
            validate_post_lengths("bluesky", "Article", "#" + "é" * 65, URL)
        family = "👨‍👩‍👧‍👦"
        with self.assertRaisesRegex(PostLengthError, "hashtag 2 exceeds 640 UTF-8 bytes"):
            validate_post_lengths("bluesky", "Article", "#ok #" + family * 26, URL)

    def test_article_url_limits_use_each_platforms_counting_unit(self):
        url = URL + "é" * (8192 - len(URL))
        validate_post_lengths("linkedin", "Article", "", url)
        with self.assertRaisesRegex(PostLengthError, "LinkedIn article URL exceeds 8,192 characters"):
            validate_post_lengths("linkedin", "Article", "", url + "a")
        with self.assertRaisesRegex(PostLengthError, "Bluesky article URL exceeds 8,192 UTF-8 bytes"):
            validate_post_lengths("bluesky", "Article", "", url)

    def test_publishers_reject_invalid_text_before_network_calls(self):
        with patch("linkedsky.requests.post") as request, patch("linkedsky.Client") as client:
            with self.assertRaises(PostLengthError):
                linkedsky.post_to_linkedin("a" * 3001, "", URL, "Article")
            with self.assertRaises(PostLengthError):
                linkedsky.post_to_bluesky("a" * 301, "", URL, "Article")
        request.assert_not_called()
        client.assert_not_called()
