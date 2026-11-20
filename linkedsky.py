"""
LinkedSky: Post to LinkedIn and Bluesky programmatically
Copyright (C) 2025  Sakis Kasampalis

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

import os
import logging
import re
import requests

from atproto import Client, models, client_utils
from dotenv import load_dotenv

from post_limits import PostLengthError, PostValidationUnavailable, hashtag_value, linkedin_text, validate_post_lengths


LINKEDIN_VERSION = "202611"
LINKEDIN_COMMENTARY_TOKENS = re.compile(r"(?<!\w)#\w+|[|{}@\[\]()<>#\\*_~]")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
    )
    load_dotenv()
    for env_var in ("LINKEDIN_AUTHOR", "LINKEDIN_TOKEN", "BSKY_USER", "BSKY_PASS"):
        validate_env_var(name=env_var)
    description, hashtags, url, title = get_post_parts()
    for platform, publish in (("LinkedIn", post_to_linkedin), ("Bluesky", post_to_bluesky)):
        if get_prompt(prompt=f"Post to {platform}"):
            try:
                publish(description, hashtags, url, title)
            except (PostLengthError, PostValidationUnavailable) as error:
                logging.error("%s", error)


def validate_env_var(name: str):
    if not name in os.environ:
        raise MissingEnvVarError(f"{name} is mandatory")


class MissingEnvVarError(RuntimeError):
    pass


def get_prompt(prompt: str):
    answer = None
    while answer not in ("y", "yes", "n", "no"):
        answer = input(f"{prompt} (y/n)? ").lower()
    return True if answer in ("y", "yes") else False


def post_to_linkedin(description: str, hashtags: str, url: str, title: str):
    validate_post_lengths("linkedin", description, hashtags, url)
    post_structure = create_linkedin_post(description, hashtags, url, title)
    post_api_url = "https://api.linkedin.com/rest/posts"
    auth_token = os.getenv("LINKEDIN_TOKEN")
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json",
        "LinkedIn-Version": LINKEDIN_VERSION,
        "X-Restli-Protocol-Version": "2.0.0",
    }
    response = requests.post(url=post_api_url, json=post_structure, headers=headers, timeout=15)
    logging.debug("LinkedIn API returned HTTP %s", response.status_code)
    return response


def create_linkedin_post(description: str, hashtags: str, url: str, title: str):
    # LinkedIn's little text format accepts hashtags and requires escaping reserved literal characters.
    commentary = LINKEDIN_COMMENTARY_TOKENS.sub(
        lambda match: match[0] if len(match[0]) > 1 else f"\\{match[0]}",
        linkedin_text(description, hashtags),
    )
    return {
        "author": os.getenv("LINKEDIN_AUTHOR"),
        "commentary": commentary,
        "lifecycleState": "PUBLISHED",
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "thirdPartyDistributionChannels": [],
        },
        "content": {"article": {"source": url, "title": title}},
    }


def get_post_parts():
    description_of_post = get_answer('Main text of the post, e.g., "Nice article found in the Computer History Museum!"')
    hashtags = get_answer('The hashtags that you want to use, e.g., "#computerhistory #computers #internet #museum"')
    article_url = get_answer("The URL of the linked article, e.g., https://computerhistory.org/blog/postscript-a-digital-printing-press/")
    article_title = get_answer('The title of the linked article, e.g., "PostScript: A digital printing press"')
    return description_of_post, hashtags, article_url, article_title


def get_answer(prompt: str):
    answer = None
    while not answer:
        answer = input(f"{prompt}: ")
    return answer

def post_to_bluesky(description: str, hashtags: str, url: str, title: str):
    validate_post_lengths("bluesky", description, hashtags, url)
    client = Client()
    client.login(login=os.getenv("BSKY_USER"), password=os.getenv("BSKY_PASS"))

    embed = models.AppBskyEmbedExternal.Main(
        external=models.AppBskyEmbedExternal.External(
            title=title,
            description="",
            uri=url
        )
    )

    text_builder = client_utils.TextBuilder()
    text_builder.text(text=description)

    add_hashtags(htags=hashtags, txt_builder=text_builder)

    post = client.send_post(text=text_builder, embed=embed, langs=["en-US"])
    logging.debug(f"Bluesky API response: {post}")


def add_hashtags(htags, txt_builder):
    hashtag_list = htags.split()
    for htag in hashtag_list:
        txt_builder.text(text=" ")
        txt_builder.tag(text=htag, tag=hashtag_value(htag))


if __name__ == "__main__":
    main()
