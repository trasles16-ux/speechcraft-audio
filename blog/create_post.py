#!/usr/bin/env python3
"""Create the SpeechCraft Studio blog post on WordPress."""

import urllib.request
import json
import base64
from pathlib import Path

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

# Parse the frontmatter and body
lines = md_content.split("\n")
meta = {}
body_lines = []
in_meta = True
for line in lines:
    if in_meta:
        if line.startswith("---"):
            in_meta = False
            continue
        if ":" in line:
            key, val = line.split(":", 1)
            meta[key.strip()] = val.strip()
    else:
        body_lines.append(line)

body_text = "\n".join(body_lines).strip()

# Convert to HTML for WordPress
# Basic markdown-to-HTML conversion
html_lines = []
in_code_block = False
in_list = False
for line in body_text.split("\n"):
    line = line.strip()
    if line.startswith("```"):
        if in_code_block:
            html_lines.append("</pre>")
            in_code_block = False
        else:
            html_lines.append("<pre><code>")
            in_code_block = True
        continue
    if in_code_block:
        html_lines.append(line)
        continue
    if line.startswith("# "):
        html_lines.append(f"<h1>{line[2:]}</h1>")
    elif line.startswith("## "):
        html_lines.append(f"<h2>{line[3:]}</h2>")
    elif line.startswith("### "):
        html_lines.append(f"<h3>{line[4:]}</h3>")
    elif line.startswith("- "):
        html_lines.append(f"<li>{line[2:]}</li>")
    elif line.startswith("   - "):
        html_lines.append(f"  <li>{line[3:]}</li>")
    elif line.startswith("> "):
        html_lines.append(f"<blockquote>{line[2:]}</blockquote>")
    elif line == "":
        html_lines.append("")
    else:
        # Handle bold and links
        text = line
        # Links
        import re
        text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)
        text = re.sub(r'\*([^\*]+)\*', r'<strong>\1</strong>', text)
        html_lines.append(f"<p>{text}</p>")

# Wrap list items
html_body = "\n".join(html_lines)
# Add list wrappers where needed
html_body = re.sub(r'(<li>.*?</li>\n?)+', r'<ul>\g<0></ul>', html_body)

# Create post data
post_data = {
    "title": meta.get("title", "Introducing SpeechCraft Studio"),
    "content": html_body,
    "status": "draft",  # Start as draft for review
    "categories": [1],  # Uncategorized - can change later
    "excerpt": "My journey building SpeechCraft Studio — an accessible audio editor for Windows, born from a breath-smoothing experiment and grew into a full-featured app.",
    "tags": []  # Leave empty or use category IDs
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
