from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
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
    command = _command(executable, url)
    try:
        result = subprocess.run(
            command,
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


def _command(executable: str, url: str) -> list[str]:
    executable_path = Path(executable)
    if executable_path.suffix.lower() not in {".cmd", ".bat"}:
        return [executable, "parse", url, "--json", "--md"]

    sibling_node = executable_path.with_name("node.exe")
    node = str(sibling_node) if sibling_node.is_file() else shutil.which("node")
    if node is None:
        raise DefuddleError("Node executable not found for the Defuddle npm shim")

    cli = executable_path.parent / "node_modules" / "defuddle" / "dist" / "cli.js"
    if not cli.is_file():
        local_node_modules = next(
            (parent for parent in executable_path.parents if parent.name == "node_modules"),
            None,
        )
        if local_node_modules is not None:
            cli = local_node_modules / "defuddle" / "dist" / "cli.js"
    if not cli.is_file():
        raise DefuddleError(f"Defuddle CLI not found beside npm shim: {executable}")

    return [node, str(cli), "parse", url, "--json", "--md"]
