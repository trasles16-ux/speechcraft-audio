# Contributing to SpeechCraft Audio

Thank you for your interest in contributing. SpeechCraft is a single-maintainer desktop project; please be patient with review turnaround.

## Code of Conduct

By participating, you agree to abide by the [Code of Conduct](CODE_OF_CONDUCT.md).

## Reporting bugs

The fastest way is **Help → Report a Bug** inside the app. It pre-fills the GitHub issues page with environment info, your description, and the tail of the local error log.

You can also file issues directly: <https://github.com/trasles16-ux/speechcraft-audio/issues>.

Please include:

- A short title describing the problem
- What you expected to happen
- What actually happened
- The steps to reproduce (numbered is best)
- Your Python version, OS, and screen-reader if relevant

## Accessibility is a hard requirement

SpeechCraft is used by blind and low-vision audio producers. Every dialog, combobox, button, and label must work with NVDA (or JAWS / Narrator). The maintainer is a blind NVDA user and reviews every PR for screen-reader behaviour, but **you should test your own PR before requesting review**.

### The NVDA rule

> Every PR that adds or modifies a dialog, combobox, or any wxPython widget must be tested with NVDA before merge. Run NVDA, navigate to the changed control with Tab, and confirm it announces a meaningful name — not "unknown", not "button", not blank.

If you do not have NVDA on your machine, mark the PR with the `needs-accessibility-review` label. The maintainer will run NVDA before merging.

Common NVDA traps to look for:

| Symptom | Likely cause | Fix |
|---|---|---|
| Combobox announces "unknown" | `wx.Choice` was created without `SetName` | `voice_choice.SetName("Voice")` after creation |
| Button announces only "button" | `wx.Button` without an explicit label or name | `button.SetName("Synthesize")` |
| Dialog opens but NVDA focus is lost | Missing `SetFocus()` on the first interactive control | Initial focus on the first input field |
| Two labels associated with one input | Adjacent `StaticText` is not a programmatic label | Use `SetName` on the control, or wrap in a labelled container |

### Useful wxPython accessibility patterns

- `control.SetName("label text")` — sets the accessible name (what NVDA announces)
- `control.SetToolTip("description")` — also picked up by some screen readers
- `dlg.SetInitialControl(first_input)` — controls where focus lands on dialog open
- For custom combobox-like widgets: implement `wx.Choice` correctly per the WAI-ARIA Authoring Practices, or use a native control instead

## Development setup

```bash
git clone https://github.com/trasles16-ux/speechcraft-audio.git
cd speechcraft-audio
pip install -r requirements.txt
python run_speechcraft.py
```

## Code style

- Python 3.11+ syntax (`from __future__ import annotations` is welcome but not required)
- Match the surrounding file's style — this repo pre-dates a linter, so consistency with neighbours matters more than a style guide
- One file at a time. The 220 KB `audio_editor.py` is on a deliberate decomposition plan; do not add new features to it — extract a module instead

## Tests

There is no full test suite yet. The smoke test at `tests/test_dialog_smoke.py` imports each TTS engine module to catch the kind of `AttributeError` that broke the Piper dialog. If you add a new engine module, add it to that test.

When you fix a bug, please add a regression test in the same PR. Even a one-line test that exercises the buggy path helps.

## Pull request process

1. Branch from `main`: `git checkout -b fix/short-description` or `feat/short-description`
2. Make your change. Commit with a Conventional Commits message: `feat(scope): …`, `fix(scope): …`, `docs: …`, `chore: …`, `test: …`
3. Run `python -c "import ast; ast.parse(open('your_file.py').read())"` on any Python file you touched — there is no full lint, but syntax errors will not be merged
4. Test with NVDA. Mark the PR `needs-accessibility-review` if you cannot
5. Push and open a PR against `main`
6. Wait for review. The maintainer is the only reviewer; turnaround is typically a few days

## Security

If you find a security vulnerability, **do not** file a public issue. Email <tracy@tracysmith.co.za> instead. See [SECURITY.md](SECURITY.md).

## License

By contributing, you agree that your contributions will be licensed under the MIT License. See [LICENSE](LICENSE).
