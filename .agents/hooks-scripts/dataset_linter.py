import sys
import json
import re
import ast

def lint_payload():
    input_data = {}
    try:
        if not sys.stdin.isatty():
            raw = sys.stdin.read()
            if raw.strip():
                input_data = json.loads(raw)
    except Exception:
        pass

    tool_name = input_data.get("tool_name", "")
    content = str(input_data.get("content", "") or input_data.get("tool_output", ""))
    warnings = []
    errors = []

    # 1. Check Python Code Blocks for Syntax Errors
    code_blocks = re.findall(r'```(?:python|py)\n(.*?)```', content, re.DOTALL)
    for idx, block in enumerate(code_blocks, 1):
        try:
            ast.parse(block)
        except SyntaxError as e:
            errors.append(f"Python code block #{idx} syntax error on line {e.lineno}: {e.msg}")

    # 2. Check Balanced LaTeX Formula Delimiters
    inline_math_count = content.count("$")
    if inline_math_count % 2 != 0:
        warnings.append(f"Unbalanced inline LaTeX math ($) delimiters found (count: {inline_math_count})")

    open_paren_math = content.count(r"\(")
    close_paren_math = content.count(r"\)")
    if open_paren_math != close_paren_math:
        warnings.append(f"Unbalanced \\( ... \\) LaTeX delimiters found ({open_paren_math} vs {close_paren_math})")

    # 3. Check JSON Structure if output is supposed to be JSON
    if content.strip().startswith("{") and content.strip().endswith("}"):
        try:
            json.loads(content)
        except json.JSONDecodeError as e:
            errors.append(f"JSON formatting error: {e.msg}")

    status = "failed" if errors else ("warning" if warnings else "passed")
    result = {
        "status": status,
        "tool_name": tool_name,
        "errors": errors,
        "warnings": warnings
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0 if not errors else 1

if __name__ == "__main__":
    sys.exit(lint_payload())
