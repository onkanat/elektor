# Registering Elektor as an MCP Server in Hermes Agent

In addition to CLI execution via `${HERMES_SKILL_DIR}/scripts/elektor_hermes_cli.py`, Elektor includes a zero-dependency Stdio JSON-RPC 2.0 MCP server at `/home/hakan/Git/elektor/hermes-agent/scripts/elektor_mcp_server.py`.

## 1. Available MCP Tools

1. `search_vector_rag(query: str, limit: int = 5)`
   Queries Qdrant vector memory (`qdrant_collection_name`, e.g., `rp01_articles`) and returns top matching technical chunks with similarity scores.
2. `query_sqlite_knowledge(keyword: str, table: "articles" | "enrichments" = "articles", limit: int = 5)`
   Performs fast SQL `LIKE` searches across full extracted PDFs or synthesized Q&A enrichments.
3. `inject_sft_dpo_context(topic: str, format_type: "sft" | "dpo" = "sft", max_samples: int = 3)`
   Fetches curated SFT or DPO fine-tuning examples from `exports/<project>/` matching the topic.
4. `evaluate_knowledge_gap(topic: str, test_question: str = "")`
   Compares raw vector chunk availability vs exported SFT/DPO sample density to identify under-represented topics.

## 2. Hermes `config.yaml` MCP Configuration

Add the following block under `mcp_servers:` in `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  elektor:
    command: "/home/hakan/Git/elektor/.venv/bin/python"
    args:
      - "/home/hakan/Git/elektor/hermes-agent/scripts/elektor_mcp_server.py"
    env:
      ELEKTOR_REPO_PATH: "/home/hakan/Git/elektor"
```

## 3. Testing the MCP Server via Stdio

```bash
printf '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}\n' \
  | /home/hakan/Git/elektor/.venv/bin/python /home/hakan/Git/elektor/hermes-agent/scripts/elektor_mcp_server.py
```
