"""robots.txt rules as RFC 9309 defines them (constitution V).

Python's `urllib.robotparser` applies the first matching rule in file order, so a file such as
"Disallow: /" followed by "Allow: /api/apply" (common on Eightfold career sites) would block the
allowed paths. RFC 9309 §2.2.2 says the most specific (longest) matching rule wins and Allow wins
a tie; `*` matches any characters and a trailing `$` anchors the end.
"""

import re
from urllib.parse import unquote, urlsplit


def _pattern(path: str) -> re.Pattern:
    anchored = path.endswith("$")
    body = path[:-1] if anchored else path
    regex = ".*".join(re.escape(part) for part in body.split("*"))
    return re.compile(regex + ("$" if anchored else ""))


class Robots:
    def __init__(self) -> None:
        self.allow_all = False
        self.disallow_all = False
        # user-agent token (lower case) -> [(rule length, allow?, compiled pattern)]
        self._groups: dict[str, list[tuple[int, bool, re.Pattern]]] = {}

    def parse(self, lines: list[str]) -> None:
        agents: list[str] = []
        in_rules = False
        for raw in lines:
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, value = (x.strip() for x in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                if in_rules:  # a new group starts
                    agents, in_rules = [], False
                agents.append(value.lower())
                for agent in agents:
                    self._groups.setdefault(agent, [])
            elif key in ("allow", "disallow") and agents:
                in_rules = True
                if not value:  # an empty Disallow allows everything: no rule
                    continue
                rule = (len(value), key == "allow", _pattern(unquote(value)))
                for agent in agents:
                    self._groups[agent].append(rule)

    def _rules(self, user_agent: str) -> list[tuple[int, bool, re.Pattern]]:
        token = user_agent.split("/", 1)[0].strip().lower()
        for agent, rules in self._groups.items():
            if agent != "*" and agent == token:
                return rules
        return self._groups.get("*", [])

    def can_fetch(self, user_agent: str, url: str) -> bool:
        if self.disallow_all:
            return False
        if self.allow_all:
            return True
        parts = urlsplit(url)
        path = unquote(parts.path or "/") + (f"?{unquote(parts.query)}" if parts.query else "")
        if path == "/robots.txt":
            return True
        best: tuple[int, bool] | None = None
        for length, allow, pattern in self._rules(user_agent):
            if pattern.match(path) and (
                best is None or length > best[0] or (length == best[0] and allow)
            ):
                best = (length, allow)
        return True if best is None else best[1]
