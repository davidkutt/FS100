"""HMAC-signed write actions (D28, ADR-0008): proposed in one turn, executed in a later one."""

import hashlib
import hmac
import json
from dataclasses import asdict, dataclass
from datetime import datetime

import jwt
from pydantic import BaseModel


class ApprovalError(Exception):
    """The signed action is invalid for this request; nothing may run."""


@dataclass(frozen=True)
class Action:
    approval_id: str
    sub: str
    conversation_id: str
    tool: str
    call_id: str
    args_sha256: str


def args_hash(args: BaseModel) -> str:
    """Over the validated args, so JSON round trips (`1` vs `1.0`, key order) keep the hash."""
    canonical = json.dumps(args.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _keys(keys: str) -> list[str]:
    if not (parsed := [key.strip() for key in keys.split(",") if key.strip()]):
        raise RuntimeError("APPROVAL_SIGNING_KEY is not set")
    return parsed


def sign(action: Action, keys: str, expires_at: datetime) -> str:
    """Signed with the first key; the others still verify (rotation)."""
    return jwt.encode({**asdict(action), "exp": expires_at}, _keys(keys)[0], algorithm="HS256")


def verify(signed: str, keys: str) -> Action:
    for key in _keys(keys):
        try:
            claims = jwt.decode(signed, key, algorithms=["HS256"], options={"require": ["exp"]})
        except jwt.InvalidSignatureError:
            continue
        except jwt.ExpiredSignatureError as error:
            raise ApprovalError("the action has expired") from error
        except jwt.PyJWTError as error:
            raise ApprovalError(f"malformed action: {error}") from error
        claims.pop("exp")
        try:
            return Action(**claims)
        except TypeError as error:
            raise ApprovalError("malformed action") from error
    raise ApprovalError("invalid signature")


def check(action: Action, sub: str, conversation_id: str, args: BaseModel) -> None:
    if action.sub != sub:
        raise ApprovalError("the action belongs to another user")
    if action.conversation_id != conversation_id:
        raise ApprovalError("the action belongs to another conversation")
    if not hmac.compare_digest(action.args_sha256, args_hash(args)):
        raise ApprovalError("the arguments differ from the proposed ones")
