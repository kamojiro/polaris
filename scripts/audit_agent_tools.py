"""チャットエージェントに登録されているtoolの一覧をASTで抽出する(ADR-0014と同じ判断).

`docs/chat-agent-flow.md`の①(1ターンの処理パイプライン)・②(tool登録の仕組み)は
変更頻度が低い骨格のため常設ドキュメント化しているが、個々のtool一覧はドメインが
増えるたびに変わる(`audit_table_usage.py`のrepositoryメソッド呼び出し元一覧と同じ理由)ため
オンデマンド実行に留める。`uv run python scripts/audit_agent_tools.py`で実行する。

`agent/tools/*.py`内の`@agent.tool`/`@agent.tool_plain`が付いた関数を対象にする
(`@agent.instructions`の動的instructions関数は挙動を変えるだけでtoolとして
呼ばれないため対象外)。役割はdocstring1行目(LLMにもそのまま渡る説明文)。
"""

from __future__ import annotations

import ast
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent / "src" / "polaris" / "agent" / "tools"
_TOOL_DECORATORS = frozenset({"tool", "tool_plain"})


def _decorator_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    names = []
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Attribute):
            names.append(decorator.attr)
        elif isinstance(decorator, ast.Name):
            names.append(decorator.id)
    return names


def main() -> None:
    """全`agent/tools/*.py`のtool関数をファイル順・定義順で一覧表示する."""
    rows: list[tuple[str, str, str, str]] = []  # (file, name, kind, role)

    for path in sorted(_TOOLS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            decorators = _decorator_names(node)
            tool_decorators = [d for d in decorators if d in _TOOL_DECORATORS]
            if not tool_decorators:
                continue
            kind = "state" if tool_decorators[0] == "tool" else "plain"
            doc = ast.get_docstring(node) or "(docstringなし)"
            role = doc.strip().split("\n")[0]
            rows.append((path.name, node.name, kind, role))

    if not rows:
        print("toolが見つかりませんでした。")
        return

    width_file = max(len(r[0]) for r in rows)
    width_name = max(len(r[1]) for r in rows)
    for file, name, kind, role in rows:
        print(f"{file:<{width_file}}  {name:<{width_name}}  [{kind:5s}]  {role}")


if __name__ == "__main__":
    main()
