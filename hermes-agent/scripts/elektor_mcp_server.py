#!/usr/bin/env python3
"""Zero-dependency Stdio JSON-RPC 2.0 MCP Server for Elektor Dataset Pipeline.

Allows Hermes Agent (`hermes mcp`) or any MCP-compatible host to call Elektor's
RAG, SQLite, SFT/DPO context, and knowledge gap evaluation tools directly over stdio.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.mcp_tools import (  # noqa: E402
    evaluate_knowledge_gap,
    inject_sft_dpo_context,
    query_sqlite_knowledge,
    search_vector_rag,
)

SERVER_INFO = {
    "name": "elektor-dataset-mcp",
    "version": "1.0.0",
}

MCP_TOOLS = [
    {
        "name": "search_vector_rag",
        "description": "Search Qdrant vector database for semantic chunks extracted from technical datasheets and articles.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Technical search query"},
                "limit": {"type": "integer", "description": "Maximum number of chunks to retrieve", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "query_sqlite_knowledge",
        "description": "Query the local SQLite database for full articles or LLM-generated SFT/DPO enrichments.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "Keyword or query to search in SQLite"},
                "limit": {"type": "integer", "description": "Maximum rows to return", "default": 5},
            },
            "required": ["keyword"],
        },
    },
    {
        "name": "inject_sft_dpo_context",
        "description": "Retrieve exported SFT or DPO fine-tuning dataset samples for a given topic.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Technical topic to search in exported JSONL datasets"},
                "max_samples": {"type": "integer", "description": "Maximum samples to retrieve", "default": 3},
            },
            "required": ["topic"],
        },
    },
    {
        "name": "evaluate_knowledge_gap",
        "description": "Evaluate pre-training vs post-dataset knowledge coverage for a specific technical topic.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "base_response": {"type": "string", "description": "Baseline response or topic description"},
                "enriched_response": {"type": "string", "description": "Dataset-enriched response"},
                "context_text": {"type": "string", "description": "Supporting context text", "default": ""},
            },
            "required": ["base_response", "enriched_response"],
        },
    },
]


def dispatch_tool(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Execute one of the registered Elektor MCP tools and return MCP content blocks."""
    try:
        if name == "search_vector_rag":
            res = search_vector_rag(
                query=str(arguments.get("query", "")),
                top_k=int(arguments.get("limit", arguments.get("top_k", 5))),
            )
        elif name == "query_sqlite_knowledge":
            res = query_sqlite_knowledge(
                query=str(arguments.get("keyword", arguments.get("query", ""))),
                limit=int(arguments.get("limit", 5)),
            )
        elif name == "inject_sft_dpo_context":
            res = inject_sft_dpo_context(
                query=str(arguments.get("topic", arguments.get("query", ""))),
                limit=int(arguments.get("max_samples", arguments.get("limit", 3))),
            )
        elif name == "evaluate_knowledge_gap":
            res = evaluate_knowledge_gap(
                base_response=str(arguments.get("base_response", arguments.get("topic", ""))),
                enriched_response=str(arguments.get("enriched_response", arguments.get("test_question", ""))),
                context_text=str(arguments.get("context_text", "")),
            )
        else:
            return {
                "isError": True,
                "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
            }
        text = json.dumps(res, indent=2, ensure_ascii=False) if not isinstance(res, str) else res
        return {
            "isError": False,
            "content": [{"type": "text", "text": text}],
        }
    except Exception as exc:
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"Tool execution error ({name}): {exc}"}],
        }


def handle_rpc_request(req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Process a single JSON-RPC 2.0 request and return a response dict (or None for notifications)."""
    method = req.get("method", "")
    req_id = req.get("id")
    params = req.get("params") or {}

    if req_id is None and method.startswith("notifications/"):
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": MCP_TOOLS},
        }

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments") or {}
        result = dispatch_tool(tool_name, arguments)
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": result,
        }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {
            "code": -32601,
            "message": f"Method not found: {method}",
        },
    }


def main() -> int:
    for line in sys.stdin:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            req = json.loads(stripped)
        except json.JSONDecodeError as exc:
            err_resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {exc}"},
            }
            sys.stdout.write(json.dumps(err_resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
            continue

        resp = handle_rpc_request(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
