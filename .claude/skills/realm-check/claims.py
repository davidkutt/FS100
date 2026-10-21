"""Prints the claims that matter for ADR-0009 of each token-endpoint JSON line on stdin."""

import base64
import json
import sys

KEYS = ["aud", "azp", "sub", "preferred_username", "scope", "realm_access", "resource_access", "act"]

for line in sys.stdin:
    if not line.strip():
        continue
    body = json.loads(line)
    if "access_token" not in body:
        print("ERROR", body)
        continue
    payload = body["access_token"].split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    print({key: claims.get(key) for key in KEYS})
