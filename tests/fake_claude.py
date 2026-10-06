"""Stand-in for the `claude` CLI in tests. Behaviour is chosen with environment variables:

FAKE_CLAUDE_LOG       file to append {"argv": [...], "stdin": "...", "cwd": ..., "env": [...]} to
FAKE_CLAUDE_RESPONSE  JSON file whose content becomes `structured_output`
FAKE_CLAUDE_MODE      ok (default) | sleep | auth | bad_json | is_error | exit1
"""

import json
import os
import sys
import time

prompt = sys.stdin.read()
log = os.environ.get("FAKE_CLAUDE_LOG")
if log:
    with open(log, "a") as f:
        f.write(
            json.dumps(
                {
                    "argv": sys.argv[1:],
                    "stdin": prompt,
                    "cwd": os.getcwd(),
                    "files": os.listdir("."),
                    "env": sorted(os.environ),
                    # test tokens only: lets tests check whose account a job ran on
                    "token": os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"),
                    "config_dir": os.environ.get("CLAUDE_CONFIG_DIR"),
                }
            )
            + "\n"
        )
mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")
if mode == "sleep":
    time.sleep(30)
if mode == "bad_json":
    print("this is not json")
    sys.exit(0)
if mode == "exit1":
    print(
        json.dumps(
            {
                "type": "result",
                "subtype": "error_max_turns",
                "is_error": True,
                "result": "Reached max turns",
            }
        )
    )
    sys.exit(1)
if mode == "auth":
    print(
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "is_error": True,
                "result": "Invalid API key · Please run /login",
            }
        )
    )
    sys.exit(1)
data = (
    json.load(open(os.environ["FAKE_CLAUDE_RESPONSE"]))
    if os.environ.get("FAKE_CLAUDE_RESPONSE")
    else {}
)
print(
    json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": mode == "is_error",
            "result": "done",
            "structured_output": data,
            "total_cost_usd": 0.0123,
        }
    )
)
