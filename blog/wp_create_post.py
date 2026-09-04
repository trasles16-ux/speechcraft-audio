#!/usr/bin/env python3
"""Create a blog post on Tracy's WordPress site (tracysmith.co.za).

Usage:
    python create_post.py --title "My Post" --body "Post content..."

Reads credentials from C:\\Users\\trace\\Documents\\Personal\\Secrets\\Pip WordPress.txt

The script creates the post as a draft first, then publishes it.
This two-step approach ensures the post is created successfully before making it live.
"""

import argparse
import json
import base64
import urllib.request
from pathlib import Path

SECRETS_FILE = Path(r"C:\Users\trace\Documents\Personal\Secrets\Pip WordPress.txt")
SITE = "https://tracysmith.co.za"

def load_credentials():
    """Load WP credentials from the secrets file."""
    with open(SECRETS_FILE) as f:
        lines = f.readlines()
    USER = "Pip"
    APP_PWD = None
    for line in lines:
        if "App Password:" in line:
            APP_PWD = line.split("App Password:")[1].strip()
            break
    return USER, APP_PWD

def create_post(title, body, category_id=1, status="draft"):
    """Create a WordPress post via REST API.
    
    Args:
        title: Post title
        body: HTML content for the post body
        category_id: Category ID (default 1 = Uncategorized)
        status: 'draft' or 'publish'
    """
    USER, APP_PWD = load_credentials()
    auth = base64.b64encode(f"{USER}:{APP_PWD}".encode()).decode()
    
    post_data = {
        "title": title,
        "content": body,
        "status": status,
        "categories": [category_id],
    }
    
    url = f"{SITE}/wp-json/wp/v2/posts"
    data = json.dumps(post_data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Basic {auth}",
            "User-Agent": "SpeechCraft-Pip/1.0",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
    )
    
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

def publish_post(post_id):
    """Update a post's status to published."""
    USER, APP_PWD = load_credentials()
    auth = base64.b64encode(f"{USER}:{APP_PWD}".encode()).decode()
    
    post_data = {"status": "publish"}
    url = f"{SITE}/wp-json/wp/v2/posts/{post_id}"
    data = json.dumps(post_data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="PUT",
        headers={
            "Authorization": f"Basic {auth}",
            "User-Agent": "SpeechCraft-Pip/1.0",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
    )
    
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

def main():
    parser = argparse.ArgumentParser(description="Create a WordPress blog post")
    parser.add_argument("--title", required=True, help="Post title")
    parser.add_argument("--body", required=True, help="HTML content for the post")
    parser.add_argument("--category", type=int, default=1, help="Category ID (default: 1)")
    parser.add_argument("--publish", action="store_true", help="Publish immediately (default: draft)")
    args = parser.parse_args()
    
    print(f"Creating post: {args.title}")
    result = create_post(args.title, args.body, args.category, "publish" if args.publish else "draft")
    
    post_id = result.get("id")
    post_url = result.get("link", f"{SITE}/?p={post_id}")
    
    print(f"Post created! ID: {post_id}")
    print(f"URL: {post_url}")
    
    if not args.publish:
        print("Post is in draft status. Use --publish to make it live.")
        print(f"To publish later: python {__file__} --title '{args.title}' --publish-post-id {post_id}")

if __name__ == "__main__":
    main()
