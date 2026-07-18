from __future__ import annotations

from dataclasses import dataclass
import json
import subprocess


class DefuddleError(RuntimeError):
    """Raised when Defuddle cannot produce usable article Markdown."""


@dataclass(frozen=True)
class DefuddledArticle:
    title: str
    author: str | None
    markdown: str


def run_defuddle(url: str, executable: str) -> DefuddledArticle:
    """Run Defuddle and return its Markdown without changing its content."""
    try:
        result = subprocess.run(
            [executable, "parse", url, "--json", "--md"],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except FileNotFoundError as error:
        raise DefuddleError(f"Defuddle executable not found: {executable}") from error
    except subprocess.TimeoutExpired as error:
        raise DefuddleError(f"Defuddle timed out for {url}") from error

    if result.returncode != 0:
        raise DefuddleError(result.stderr.strip() or f"Defuddle exited with {result.returncode}")

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise DefuddleError("Defuddle returned invalid JSON") from error

    if not isinstance(payload, dict):
        raise DefuddleError("Defuddle returned invalid JSON")
    content = payload.get("content")
    if not isinstance(content, str) or not content.strip():
        raise DefuddleError("Defuddle returned no article content")

    title = payload.get("title")
    author = payload.get("author")
    return DefuddledArticle(
        title if isinstance(title, str) else "",
        author if isinstance(author, str) and author.strip() else None,
        content,
    )
