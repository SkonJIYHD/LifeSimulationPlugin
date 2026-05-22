# utils/hint_helper.py
# 纯映射工具，供 components/tools.py 和 components/apis.py 共用
# 不含任何 SDK 依赖

_HINTS: dict[tuple[str, str], str] = {
    ("sleeping", "sleepy"):   "Preparing to sleep, feeling drowsy",
    ("sleeping", "sleeping"): "Currently sleeping, do not disturb",
    ("sleeping", "waking"):   "Just woke up, still a bit groggy",
    ("eating",   "awake"):    "Having a meal",
    ("studying", "awake"):    "Studying, pretty focused",
    ("exercising", "awake"):  "Exercising",
    ("working",  "awake"):    "Busy with work",
    ("leisure",  "awake"):    "Relaxing",
    ("other",    "awake"):    "Doing something",
}


def build_status_hint(activity: str, sleep_state: str, description: str = "") -> str:
    base = _HINTS.get((activity, sleep_state), "Status unknown")
    if description and activity not in ("sleeping",):
        return f"{base} ({description})"
    return base


_AFFINITY_LEVELS = [
    (0.8, "Very close, chat often"),
    (0.6, "Good impression, talk quite a bit"),
    (0.4, "Some interaction"),
    (0.2, "Occasional contact"),
    (0.0, "Barely know each other"),
]


def affinity_to_hint(affinity: float) -> str:
    for threshold, hint in _AFFINITY_LEVELS:
        if affinity >= threshold:
            return hint
    return _AFFINITY_LEVELS[-1][1]
