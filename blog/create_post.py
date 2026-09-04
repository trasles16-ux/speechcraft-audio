#!/usr/bin/env python3
"""Create the SpeechCraft Studio blog post on WordPress."""

import urllib.request
import json
import base64
import re
from pathlib import Path

try:
    import markdown
except ImportError:
    print("Installing markdown library...")
    import subprocess
    subprocess.check_call(["python", "-m", "pip", "install", "markdown"])
    import markdown

# Credentials
SECRETS_FILE = Path(r"C:\Users\trace\Documents\Personal\Secrets\Pip WordPress.txt")
SITE = "https://tracysmith.co.za"

with open(SECRETS_FILE) as f:
    lines = f.readlines()

USER = "Pip"
APP_PWD = None
for line in lines:
    if "App Password:" in line:
        APP_PWD = line.split("App Password:")[1].strip()
        break

auth = base64.b64encode(f"{USER}:{APP_PWD}".encode()).decode()

# Read the markdown content
content_file = Path(__file__).parent / "introducing-speechcraft.md"
md_content = content_file.read_text(encoding="utf-8")

# Parse the frontmatter - find the first --- line and skip everything until next ---
lines = md_content.split("\n")
body_lines = []
meta = {}
skipping_frontmatter = True
found_first_dashes = False
found_second_dashes = False

for line in lines:
    if skipping_frontmatter:
        if line.strip() == "---":
            if not found_first_dashes:
                found_first_dashes = True
            else:
                found_second_dashes = True
                skipping_frontmatter = False
        elif found_first_dashes and not found_second_dashes:
            # Parse meta line
            if ":" in line:
                key, val = line.split(":", 1)
                meta[key.strip()] = val.strip().strip('"')
        else:
            body_lines.append(line)
    else:
        body_lines.append(line)

body_text = "\n".join(body_lines).strip()
title = meta.get("title", "Introducing SpeechCraft Studio")

# Convert markdown to HTML using the markdown library
md = markdown.Markdown(extensions=['fenced_code', 'toc'])
html_body = md.convert(body_text)

# Create post data
post_data = {
    "title": title,
    "content": html_body,
    "status": "publish",
    "categories": [1],
    "excerpt": "My journey building SpeechCraft Studio — an accessible audio editor for Windows, born from a breath-smoothing experiment and grew into a full-featured app.",
}

# Make the request
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

try:
    with urllib.request.urlopen(req, timeout=30) as r:
        result = json.loads(r.read().decode())
        print(f"Post created successfully!")
        print(f"ID: {result.get('id')}")
        print(f"Status: {result.get('status')}")
        print(f"URL: {result.get('link')}")
except urllib.error.HTTPError as e:
    error_body = e.read().decode(errors="replace")
    print(f"HTTP Error {e.code}: {error_body[:500]}")
except Exception as e:
    print(f"Error: {e}")
