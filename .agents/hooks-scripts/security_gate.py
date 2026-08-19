import sys
import json
import os
import sqlite3

def run_security_gate():
    input_data = {}
    try:
        if not sys.stdin.isatty():
            raw = sys.stdin.read()
            if raw.strip():
                input_data = json.loads(raw)
    except Exception:
        pass

    tool_name = input_data.get("tool_name", os.environ.get("HOOK_TOOL_NAME", ""))
    tool_args = input_data.get("tool_args", {})
    command = str(tool_args.get("command", "") or input_data.get("command", ""))

    # 1. Prohibit dangerous destructive commands in sandbox
    dangerous_patterns = ["rm -rf /", "rm -rf ~", "mkfs", "dd if=/dev/zero", ":(){ :|:& };:"]
    for pat in dangerous_patterns:
        if pat in command:
            output = {
                "decision": "deny",
                "reason": f"Security violation: Prohibited dangerous pattern detected: '{pat}'"
            }
            print(json.dumps(output))
            return 1

    # 2. Check Monthly Token Budget
    db_path = input_data.get("db_path", "database/elektor_archive.db")
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path, timeout=5.0)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='gemini_usage_logs'")
            if cursor.fetchone():
                import time
                month_prefix = time.strftime("%Y-%m", time.gmtime())
                cursor.execute("SELECT SUM(total_tokens) FROM gemini_usage_logs WHERE timestamp LIKE ?", (f"{month_prefix}%",))
                row = cursor.fetchone()
                total_spent = row[0] or 0
                max_budget = int(input_data.get("max_monthly_budget_tokens", 50_000_000))
                if total_spent >= max_budget and "gemini" in tool_name.lower():
                    conn.close()
                    output = {
                        "decision": "deny",
                        "reason": f"Budget Cap Exceeded: Monthly token usage ({total_spent:,}) reached limit ({max_budget:,})."
                    }
                    print(json.dumps(output))
                    return 1
            conn.close()
        except Exception:
            pass

    # All checks passed
    output = {
        "decision": "allow",
        "reason": "Security and budget verification passed."
    }
    print(json.dumps(output))
    return 0

if __name__ == "__main__":
    sys.exit(run_security_gate())
