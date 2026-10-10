"""High-score persistence and leaderboard logic.

Stores the top 5 scores in a JSON file alongside this script.
Handles missing or corrupt files gracefully. No external dependencies
beyond the Python standard library.
"""

import json
from pathlib import Path

SAVE_FILE = "high_scores.json"
MAX_SCORES = 5


def _save_path():
    """Absolute path to the high-score file, next to this module."""
    return Path(__file__).resolve().parent / SAVE_FILE


def load_scores():
    """Return the top-5 scores as a list of dicts: [{"name": str, "score": int}, ...].

    Returns an empty list if the file is missing, empty, or corrupt.
    """
    path = _save_path()
    if not path.exists():
        return []
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError, ValueError):
        return []

    if not isinstance(data, list):
        return []

    valid = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        score = entry.get("score")
        if not isinstance(name, str) or not isinstance(score, int):
            continue
        valid.append({"name": name, "score": score})

    valid.sort(key=lambda e: e["score"], reverse=True)
    return valid[:MAX_SCORES]


def save_scores(scores):
    """Write the score list to the JSON file. Silent on I/O failure."""
    path = _save_path()
    try:
        with open(path, "w") as f:
            json.dump(scores[:MAX_SCORES], f)
    except OSError:
        pass


def add_score(name, score):
    """Record a score and return the updated top-5 list.

    Uses "Anonymous" if the name is blank. Persists to disk.
    """
    name = name.strip() if isinstance(name, str) else ""
    if not name:
        name = "Anonymous"

    scores = load_scores()
    scores.append({"name": name, "score": int(score)})
    scores.sort(key=lambda e: e["score"], reverse=True)
    scores = scores[:MAX_SCORES]

    save_scores(scores)
    return scores


def qualifies(name, score):
    """Return True if this score would enter the top 5."""
    scores = load_scores()
    if len(scores) < MAX_SCORES:
        return True
    return int(score) > scores[-1]["score"]