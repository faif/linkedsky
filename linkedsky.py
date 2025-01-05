import os
import logging
import requests

from atproto import Client, models, client_utils
from dotenv import load_dotenv

def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
    )
    load_dotenv()
    for env_var in ("LINKEDIN_AUTHOR", "LINKEDIN_TOKEN", "BSKY_USER", "BSKY_PASS"):
        validate_env_var(name=env_var)
    description, hashtags, url, title = get_post_parts()
    post_to_ln = get_prompt(prompt="Post to LinkedIn")
    if post_to_ln:
        post_to_linkedin(description, hashtags, url, title)
    post_to_bsky = get_prompt(prompt="Post to Bluesky")
    if post_to_bsky:
        post_to_bluesky(description, hashtags, url, title)


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
    post_structure = create_linkedin_post(description, hashtags, url, title)
    post_api_url = "https://api.linkedin.com/v2/ugcPosts"
    auth_token = os.getenv("LINKEDIN_TOKEN")
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json"
    }
    response = requests.post(url=post_api_url, json=post_structure, headers=headers)
    logging.debug(f"LinkedIn API response {response.text}")


def create_linkedin_post(description: str, hashtags: str, url: str, title: str):
    map_structure = {
        "author": os.getenv("LINKEDIN_AUTHOR"),
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {
                    "text": f"{description} {hashtags}"
                },
                "shareMediaCategory": "ARTICLE",
                "media": [
                    {
                        "status": "READY",
                        "originalUrl": url,
                        "title": {
                            "text": title
                        }
                    }
                ]
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
        }
    }
    return map_structure


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
        hashtag_no_hash = htag.replace("#", "")
        txt_builder.text(text=" ")
        txt_builder.tag(text=htag, tag=hashtag_no_hash)


if __name__ == "__main__":
    main()
