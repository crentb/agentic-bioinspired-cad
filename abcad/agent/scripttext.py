"""
abcad.agent.scripttext — extracting, normalizing and digesting Blender scripts from model output.

PURPOSE
    These rules decide which code the emitter, the repairer and the refiner accept, and they fix
    the digests that the stall guards compare. They are deliberately simple, deterministic string
    operations so that the same completion always yields the same script and digest.

INPUTS / OUTPUTS
    extract_script(completion)  -> the code block a completion carries (see the rules below)
    normalize_script(text)      -> the script as it is executed (fences and control characters
                                   removed, ``import bpy`` guaranteed at the top)
    script_digest(script)       -> 40-hex SHA-1 of the whitespace-trimmed script (not a security
                                   hash: it only detects verbatim repeats)
    first_line(text, limit)     -> first non-empty line, truncated, for logs and error trails
"""

from __future__ import annotations

import hashlib
import re

# A fence that opens with three backticks immediately followed by the lowercase tag "python";
# optional whitespace (newlines included) may follow the tag, and the block runs NON-greedily to
# the next three backticks. DOTALL lets the body span lines.
_PYTHON_FENCE = re.compile(r"```python\s*(.*?)```", re.DOTALL)

# C0 control characters that are removed: U+0000..U+0008 and U+000B..U+001F. Tab (U+0009) and line
# feed (U+000A) are kept; carriage return (U+000D) is in the removed range, so CRLF becomes LF.
_CONTROL_CHARS = re.compile("[\x00-\x08\x0b-\x1f]")

_IMPORT_BPY = "import bpy"


def extract_script(completion: str) -> str:
    """Return the code carried by a model completion.

    Rules, in order:
        1. If the text holds one or more ``python``-tagged fences, return the LAST block's content,
           stripped. Untagged fences and fences with another tag do not match this rule.
        2. Else, if the text contains ``import bpy``, return everything from its LAST occurrence
           to the end, stripped.
        3. Else, return the whole text, stripped.

    Args:
        completion: raw model output.

    Returns:
        The extracted script text (possibly empty).
    """
    blocks = _PYTHON_FENCE.findall(completion)
    if blocks:
        return blocks[-1].strip()
    position = completion.rfind(_IMPORT_BPY)
    if position >= 0:
        return completion[position:].strip()
    return completion.strip()


def normalize_script(text: str | None) -> str:
    """Normalize a script for execution.

    Steps: empty or None -> exactly ``import bpy``; strip surrounding whitespace; remove every
    "```python" and then every remaining "```"; remove control characters (tab and LF kept, CR
    removed); prepend ``import bpy`` + LF when the text (ignoring leading whitespace) does not
    start with it. There is deliberately no second strip and no trailing newline, which keeps the
    function idempotent on its own output whenever that output has no surrounding whitespace.

    Args:
        text: script text or None.

    Returns:
        The normalized script.
    """
    if not text:
        return _IMPORT_BPY
    result = text.strip()
    result = result.replace("```python", "").replace("```", "")
    result = _CONTROL_CHARS.sub("", result)
    if not result.lstrip().startswith(_IMPORT_BPY):
        result = _IMPORT_BPY + "\n" + result
    return result


def script_digest(script: str) -> str:
    """SHA-1 hex digest (40 lowercase hex characters) of the UTF-8 bytes of ``script.strip()``.

    The repair repeat guard and the refine stall guard compare these digests to detect verbatim
    repeats. ``usedforsecurity=False`` records that this is a content fingerprint, not a
    cryptographic use.
    """
    return hashlib.sha1(script.strip().encode("utf-8"), usedforsecurity=False).hexdigest()


def first_line(text: str | None, limit: int = 160) -> str:
    """Return the first non-empty line of ``text``, stripped and truncated to ``limit`` characters.

    Args:
        text: any text (an error excerpt, typically).
        limit: maximum number of characters returned.

    Returns:
        The line, or ``"(no message)"`` when the text has no non-blank line.
    """
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:limit]
    return "(no message)"
