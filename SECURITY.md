# Security Policy

## Supported versions

SpeechCraft Audio 3.0.x is the only currently-supported release line. Older versions will not receive security fixes.

## Reporting a vulnerability

Please **do not** file a public GitHub issue for security vulnerabilities.

Email <tracy@tracysmith.co.za> with:

- A short description of the vulnerability
- Steps to reproduce, if you have them
- The impact (what an attacker could do)
- Any suggested fix, if you have one

You should receive a reply within seven days. If you do not, please follow up.

## What to expect

- An acknowledgement of your report within seven days
- A determination of severity and impact within fourteen days
- A fix or mitigation as soon as practicable, with a coordinated disclosure timeline

We are a single-maintainer project; please be patient.

## Scope

In scope:

- Anything that allows arbitrary code execution from a crafted audio file, project file, or network input
- Anything that leaks local files or environment data to a remote server without consent
- Anything that bypasses the FFmpeg / Piper sandbox in `custom_asio.py`
- Anything that breaks screen-reader behaviour in a way that could mislead a blind user (e.g. a dialog that announces "OK" while doing something destructive)

Out of scope:

- The wxPython / PyInstaller supply chain (report upstream)
- The Faster Whisper / Edge TTS API endpoints (report upstream)
- Anything that requires physical access to the machine

## Recognition

We are happy to credit reporters in the fix commit message unless they prefer to remain anonymous.
