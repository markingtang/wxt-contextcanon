"""WXT ContextCanon MCP server - stdio JSON-RPC, standard library only.

MCP over stdio is newline-delimited JSON-RPC 2.0. That is small enough to
implement directly, which keeps WXT ContextCanon installable with `pip install`
of nothing at all.

Tool surface is deliberately small (8 tools). Everything else belongs in the
CLI, not in the agent's tool belt.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Callable, Dict, List, Optional

from contextcanon_config import load_config, resolve_paths, ensure_dirs
from profile_core import ProfileService, ProfileStore, now_iso
from registry_core import RegistryService, RegistryStore

PROTOCOL_VERSION = "2024-11-05"


class ToolError(Exception):
    pass


class ContextCanonMcpServer:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.profile = ProfileService(
            ProfileStore(config["profile"]["database"]), actor="mcp"
        )
        self.registry = RegistryService(
            RegistryStore(config["registry"]["shared_store"]),
            device_id=config["registry"]["device_id"],
            device_role=config["registry"]["device_role"],
        )
        self.registry.ensure_device()
        self.tools: Dict[str, Callable[[Dict[str, Any]], Any]] = {
            "profile_get": self.tool_profile_get,
            "profile_search": self.tool_profile_search,
            "profile_upsert": self.tool_profile_upsert,
            "profile_as_of": self.tool_profile_as_of,
            "profile_history": self.tool_profile_history,
            "profile_audit": self.tool_profile_audit,
            "registry_query": self.tool_registry_query,
            "registry_event": self.tool_registry_event,
        }

    # ------------------------------------------------------------------ tools

    def tool_profile_get(self, args: Dict[str, Any]) -> Dict[str, Any]:
        subject = _require(args, "subject")
        key = _require(args, "key")
        fact = self.profile.get_fact(subject, key, include_inactive=bool(args.get("include_inactive")))
        if fact is None:
            return {"found": False, "subject": subject, "key": key}
        return {"found": True, "fact": _public_fact(fact)}

    def tool_profile_search(self, args: Dict[str, Any]) -> Dict[str, Any]:
        subject = _require(args, "subject")
        query = _require(args, "query")
        limit = int(args.get("limit", 20))
        facts = self.profile.search(subject, query, limit)
        return {"count": len(facts), "facts": [_public_fact(f) for f in facts]}

    def tool_profile_upsert(self, args: Dict[str, Any]) -> Dict[str, Any]:
        subject = _require(args, "subject")
        key = _require(args, "key")
        if "value" not in args:
            raise ToolError("'value' is required")
        result = self.profile.upsert_fact(
            subject=subject,
            key=key,
            value=args["value"],
            sensitivity=args.get("sensitivity", "personal"),
            durability=args.get("durability", "durable"),
            certainty=float(args.get("certainty", 1.0)),
            valid_from=args.get("valid_from"),
            valid_until=args.get("valid_until"),
            provenance={
                "source": args.get("source", "agent-stated"),
                "ref": args.get("ref", ""),
                "method": args.get("method", "mcp.upsert"),
                "observed_at": args.get("observed_at", now_iso()),
                "confidence": float(args.get("confidence", 1.0)),
            },
            on_conflict=args.get("on_conflict", "supersede"),
            actor=args.get("actor", "mcp"),
        )
        return {
            "action": result["action"],
            "fact": _public_fact(result["fact"]),
            "supersedes": result.get("supersedes"),
            "conflicts_with": result.get("conflicts_with"),
        }

    def tool_profile_as_of(self, args: Dict[str, Any]) -> Dict[str, Any]:
        subject = _require(args, "subject")
        timestamp = _require(args, "timestamp")
        facts = self.profile.as_of(subject, timestamp, include_rejected=bool(args.get("include_rejected")))
        return {"timestamp": timestamp, "count": len(facts), "facts": [_public_fact(f) for f in facts]}

    def tool_profile_history(self, args: Dict[str, Any]) -> Dict[str, Any]:
        subject = _require(args, "subject")
        key = _require(args, "key")
        facts = self.profile.history(subject, key)
        return {"count": len(facts), "facts": [_public_fact(f) for f in facts]}

    def tool_profile_audit(self, args: Dict[str, Any]) -> Dict[str, Any]:
        subject = _require(args, "subject")
        events = self.profile.audit(subject, int(args.get("limit", 50)))
        return {"count": len(events), "events": events}

    def tool_registry_query(self, args: Dict[str, Any]) -> Dict[str, Any]:
        rows = self.registry.query(args.get("object_key"), args.get("device_id"))
        return {"count": len(rows), "rows": rows}

    def tool_registry_event(self, args: Dict[str, Any]) -> Dict[str, Any]:
        kind = _require(args, "kind")
        payload = args.get("payload") or {}
        if not isinstance(payload, dict):
            raise ToolError("'payload' must be an object")
        if kind.startswith("file.") and not payload.get("object_key"):
            raise ToolError("'payload.object_key' is required for file.* events")
        event = self.registry.append_event(kind, payload, device_id=args.get("device_id"))
        self.registry.apply_all()
        return {"event": event, "applied": True}

    # -------------------------------------------------------------- protocol

    def handle(self, message: Any) -> Optional[Dict[str, Any]]:
        """Handle one decoded JSON-RPC message. Never raises for bad input."""
        if not isinstance(message, dict):
            # A batch array or a bare scalar is not a request we can serve.
            # Say so explicitly instead of silently dropping the line.
            return _error(None, -32600, "invalid request: expected a JSON object "
                                        "(JSON-RPC batch is not supported)")

        if message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
            return _error(None, -32600, "invalid JSON-RPC request")
        if "id" not in message:
            # Notifications never receive replies or perform tool mutations.
            return None
        if isinstance(message["id"], (dict, list, bool)):
            return _error(None, -32600, "invalid request id")
        method = message.get("method")
        req_id = message.get("id")
        params = message.get("params")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return _error(req_id, -32602, "invalid params: 'params' must be an object")

        if method == "initialize":
            return _result(req_id, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": self.config["server"]["name"],
                    "version": self.config["server"]["version"],
                },
                "instructions": (
                    "WXT ContextCanon = one personal context + one file-state ledger for many agents. "
                    "Recall before you ask, update only what you actually learned, and wrap "
                    "mutations in registry begin/end intent."
                ),
            })

        if method in ("notifications/initialized", "initialized"):
            return None

        if method == "tools/list":
            return _result(req_id, {"tools": self.tool_specs()})

        if method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments")
            if arguments is None:
                arguments = {}
            if not isinstance(arguments, dict):
                return _result(req_id, {"content": [{"type": "text",
                                                     "text": "error: 'arguments' must be an object"}],
                                        "isError": True})
            if not isinstance(name, str):
                return _error(req_id, -32602, "tool name must be a string")
            handler = self.tools.get(name)
            if handler is None:
                return _error(req_id, -32602, "unknown tool")
            try:
                spec = next(t for t in self.tool_specs() if t["name"] == name)
                _validate_arguments(arguments, spec["inputSchema"])
                data = handler(arguments)
                text = json.dumps(data, ensure_ascii=False, indent=2, default=str)
                return _result(req_id, {"content": [{"type": "text", "text": text}], "isError": False})
            except ToolError as exc:
                return _result(req_id, {"content": [{"type": "text", "text": "error: %s" % exc}],
                                        "isError": True})
            except Exception as exc:  # never crash the agent's session
                return _result(req_id, {"content": [{"type": "text", "text": "operation failed; check arguments and local configuration"}],
                                        "isError": True})

        if method == "ping":
            return _result(req_id, {})

        return _error(req_id, -32601, "method not found: %s" % method)

    def tool_specs(self) -> List[Dict[str, Any]]:
        return [
            _spec("profile_get", "Read one active fact for a subject.",
                  {"subject": _s("Subject id, e.g. demo:alex-chen"), "key": _s("Fact key, e.g. timezone"),
                   "include_inactive": _s("Also return superseded/rejected/expired facts", "boolean")},
                  ["subject", "key"]),
            _spec("profile_search", "Substring search over active fact keys and values.",
                  {"subject": _s("Subject id"), "query": _s("Search text"), "limit": _s("Max results", "integer")},
                  ["subject", "query"]),
            _spec("profile_upsert", "Create or replace a fact. Old value is kept as a superseded revision.",
                  {"subject": _s("Subject id"), "key": _s("Fact key"), "value": {"description": "New non-null JSON value"},
                   "sensitivity": _s("public|personal|sensitive|restricted"),
                   "durability": _s("durable|temporary|scheduled"),
                   "valid_from": {"type": ["string", "null"]}, "valid_until": {"type": ["string", "null"]},
                   "certainty": _s("0 to 1", "number"), "confidence": _s("0 to 1", "number"),
                   "ref": _s("Source reference"), "method": _s("Observation method"),
                   "observed_at": _s("ISO timestamp"), "actor": _s("Audit actor"),
                   "source": _s("Provenance source"), "on_conflict": _s("supersede|reject|keep")},
                  ["subject", "key", "value"]),
            _spec("profile_as_of", "What did we believe at time T? Temporal read across revisions.",
                  {"subject": _s("Subject id"), "timestamp": _s("ISO timestamp"),
                   "include_rejected": _s("Include rejected claims", "boolean")},
                  ["subject", "timestamp"]),
            _spec("profile_history", "All revisions of one key, oldest first.",
                  {"subject": _s("Subject id"), "key": _s("Fact key")}, ["subject", "key"]),
            _spec("profile_audit", "Append-only audit trail for a subject.",
                  {"subject": _s("Subject id"), "limit": _s("Max events", "integer")}, ["subject"]),
            _spec("registry_query", "Read the shared file-state index (optionally by object key).",
                  {"object_key": _s("Object key to look up"), "device_id": _s("Filter by device")}, []),
            _spec("registry_event", "Append a file-state event to the ledger and project it.",
                  {"kind": _s("file.upsert|file.delete|file.move"),
                   "payload": _s("Event payload object, must include object_key", "object"),
                   "device_id": _s("Override device id")}, ["kind", "payload"]),
        ]

    def close(self) -> None:
        self.profile.store.close()
        self.registry.store.close()

    def serve(self, stdin=None, stdout=None) -> None:
        stdin = stdin or sys.stdin
        stdout = stdout or sys.stdout
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            response = self.handle_line(line)
            if response is None:
                continue
            stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            stdout.flush()

    def handle_line(self, line: str) -> Optional[Dict[str, Any]]:
        """Decode and handle a single input line, in full isolation.

        One malformed line can never end the stdio session: it produces a
        JSON-RPC error and the next valid line is handled normally.
        """
        try:
            message = json.loads(line)
        except ValueError:
            return _error(None, -32700, "parse error: input is not valid JSON")
        try:
            return self.handle(message)
        except Exception as exc:  # noqa: BLE001 - the session must survive anything
            req_id = message.get("id") if isinstance(message, dict) else None
            return _error(req_id, -32603, "operation failed; check arguments and local configuration")


def _result(req_id: Any, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": payload}


def _error(req_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _s(description: str, type_name: str = "string") -> Dict[str, Any]:
    return {"type": type_name, "description": description}


def _spec(name: str, description: str, properties: Dict[str, Any], required: List[str]) -> Dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "inputSchema": {"type": "object", "properties": properties, "required": required},
    }


def _require(args: Dict[str, Any], key: str) -> Any:
    if key not in args:
        raise ToolError("'%s' is required" % key)
    if not isinstance(args[key], str) or not args[key].strip():
        raise ToolError("'%s' must be a non-empty string" % key)
    return args[key]


def _public_fact(fact: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "fact_id": fact["fact_id"],
        "subject": fact["subject"],
        "key": fact["key"],
        "value": fact["value"],
        "status": fact["status"],
        "sensitivity": fact["sensitivity"],
        "durability": fact["durability"],
        "certainty": fact["certainty"],
        "valid_from": fact.get("valid_from"),
        "valid_until": fact.get("valid_until"),
        "revision": fact["revision"],
        "provenance": fact.get("provenance", {}),
        "supersedes": fact.get("supersedes"),
        "superseded_by": fact.get("superseded_by"),
    }


def build_server(config_path: Optional[str] = None, root: Optional[str] = None) -> ContextCanonMcpServer:
    config = load_config(config_path)
    resolve_paths(config, root or _default_root())
    ensure_dirs(config)
    return ContextCanonMcpServer(config)


def _default_root() -> str:
    import os
    return os.getcwd()


def _validate_arguments(args, schema):
    for key in schema["required"]:
        if key not in args:
            raise ToolError("missing required argument: " + key)
    for key, value in args.items():
        prop = schema["properties"].get(key)
        if prop is None:
            raise ToolError("unknown argument")
        types = prop.get("type")
        if types is None:
            continue
        types = types if isinstance(types, list) else [types]
        valid = (("null" in types and value is None)
                 or ("string" in types and isinstance(value, str))
                 or ("boolean" in types and isinstance(value, bool))
                 or ("integer" in types and isinstance(value, int) and not isinstance(value, bool))
                 or ("number" in types and isinstance(value, (int, float)) and not isinstance(value, bool))
                 or ("object" in types and isinstance(value, dict)))
        if not valid:
            raise ToolError("invalid argument type: " + key)
        if key == "limit" and not 1 <= value <= 1000:
            raise ToolError("limit must be between 1 and 1000")
