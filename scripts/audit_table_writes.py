"""どのコードがどのテーブルに書き込むかをASTで監査する(ADR-0014).

常設ドキュメント化はせず、必要になった都度このスクリプトを実行して最新の状態を得る運用
(ADRの決定通り)。`uv run python scripts/audit_table_writes.py`で実行する。

判定対象: 変数名が`session`のオブジェクトに対する`.add(X)`/`.merge(X)`/`.delete(X)`呼び出し
(このコードベースの規約で、SQLModelの`Session`は常に`session`という変数名を使うため。
これにより`_background_tasks.add(task)`のような無関係な`.add()`呼び出しを除外する)。

`X`の型(≒テーブル)は次の優先順で推定する(完全な型推論ではないヒューリスティック):

1. `X`が`ClassName(...)`の直接呼び出し
2. 同じ関数内で`X`が引数の型注釈(`ClassName`/`ClassName | None`/`list[ClassName]`等)を持つ
3. 同じ関数内で`X = ClassName(...)`という代入
4. 同じ関数内で`X = session.get(ClassName, ...)`という代入
5. 同じ関数内で`X = session.exec(<queryが select(ClassName) を含む>).first()`という代入
   (`query = select(ClassName)...`のように一度変数に入れてから`session.exec(query)`する
   形も追跡する)
6. `for X in <上記4/5のパターン、または list[ClassName] 注釈の変数>:`というforループ

どれにも当てはまらない場合は「未解決」として出力し、テーブル名を推測しない
(誤った断定より「わからない」と正直に言う方が監査ツールとして安全なため)。

`conn.exec_driver_sql(...)`(`db/vector_store.py`のsqlite-vec直SQL書き込み、ORM経由ではない)
は別枠で検出する。同じモジュール内に`_TABLE_NAME = "..."`という定数があれば参考情報として
添えるが、SQL文自体を解析して検証してはいないため注意書きを付ける。

既知の限界: タプルアンパック(`item, record = existing`のような、呼び出し先の戻り値型に
依存する代入)は解決しない。ネストした関数(クロージャ)は、外側とは独立に自分自身の
スコープだけを見て監査する(外側の変数を参照するクロージャ内の書き込みは解決できないことがある)。
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

_SRC_ROOT = Path(__file__).resolve().parent.parent / "src" / "polaris"
_WRITE_METHODS = frozenset({"add", "merge", "delete"})
_SESSION_VAR_NAMES = frozenset({"session"})


def _entity_table_map() -> dict[str, str]:
    """`domain/entities.py`を実際にimportし、SQLModelのtable=TrueクラスからClassName→テーブル名を作る."""
    sys.path.insert(0, str(_SRC_ROOT.parent))
    import sqlmodel  # noqa: PLC0415 - sys.path登録の後でないとimportできない

    from polaris.domain import entities as entities_module  # noqa: PLC0415

    return {
        name: str(obj.__tablename__)
        for name, obj in vars(entities_module).items()
        if isinstance(obj, type) and issubclass(obj, sqlmodel.SQLModel) and getattr(obj, "__tablename__", None)
    }


@dataclass
class WriteSite:
    """1箇所の書き込み呼び出し."""

    file: Path
    line: int
    method: str  # "add" | "merge" | "delete" | "raw_sql"
    table: str | None  # Noneは未解決
    expr: str
    note: str = ""


def _walk_own_scope(node: ast.AST) -> Iterator[ast.AST]:
    """`ast.walk`と同じだが、ネストした関数定義の内部には降りない.

    ネストした関数(クロージャ)は`ast.NodeVisitor`が別途`visit_FunctionDef`等で
    単独訪問するため、外側の関数を監査する際にその中身まで含めると二重カウントになる。
    """
    stack = list(ast.iter_child_nodes(node))
    while stack:
        current = stack.pop()
        yield current
        if isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            continue
        stack.extend(ast.iter_child_nodes(current))


def _annotation_class_name(annotation: ast.expr | None, known: set[str]) -> str | None:
    """`ClassName`・`ClassName | None`・`list[ClassName]`等から既知クラス名を取り出す."""
    if annotation is None:
        return None
    if isinstance(annotation, ast.Name) and annotation.id in known:
        return annotation.id
    if isinstance(annotation, ast.BinOp):  # X | None
        return _annotation_class_name(annotation.left, known) or _annotation_class_name(annotation.right, known)
    if isinstance(annotation, ast.Subscript):  # list[X] / Optional[X]
        return _annotation_class_name(annotation.slice, known)
    return None


class _FunctionAuditor(ast.NodeVisitor):
    """1ファイル分のFunctionDef/AsyncFunctionDefを、それぞれ自分のスコープだけ監査する."""

    def __init__(self, file: Path, known: dict[str, str]) -> None:
        self.file = file
        self.known = known  # ClassName -> table
        self.sites: list[WriteSite] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._audit_function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._audit_function(node)
        self.generic_visit(node)

    def _audit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        var_types: dict[str, str] = {}
        for arg in (*node.args.args, *node.args.kwonlyargs):
            cls = _annotation_class_name(arg.annotation, set(self.known))
            if cls is not None:
                var_types[arg.arg] = cls

        # `query = select(ClassName)...`をまず集める(変数の型推定より前に必要な情報のため)。
        query_var_types = self._collect_query_var_types(node)
        self._collect_var_types(node, var_types, query_var_types)
        self._collect_write_sites(node, var_types)

    def _collect_query_var_types(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, str]:
        query_var_types: dict[str, str] = {}
        for child in _walk_own_scope(node):
            if not isinstance(child, ast.Assign):
                continue
            cls = self._select_class_name(child.value)
            if cls is None:
                continue
            for target in child.targets:
                if isinstance(target, ast.Name):
                    query_var_types[target.id] = cls
        return query_var_types

    def _collect_var_types(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        var_types: dict[str, str],
        query_var_types: dict[str, str],
    ) -> None:
        """代入・forループから変数の型を推定し、`var_types`に書き足す."""
        for child in _walk_own_scope(node):
            if isinstance(child, ast.Assign):
                cls = self._resolve_expr_class(child.value, query_var_types)
                if cls is not None:
                    for target in child.targets:
                        if isinstance(target, ast.Name):
                            var_types[target.id] = cls
            elif isinstance(child, ast.For) and isinstance(child.target, ast.Name):
                cls = self._iterable_class_name(child.iter, var_types, query_var_types)
                if cls is not None:
                    var_types[child.target.id] = cls

    def _collect_write_sites(self, node: ast.FunctionDef | ast.AsyncFunctionDef, var_types: dict[str, str]) -> None:
        """`session.add/.merge/.delete`呼び出しを収集する."""
        for child in _walk_own_scope(node):
            if not (isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)):
                continue
            receiver = child.func.value
            if not (isinstance(receiver, ast.Name) and receiver.id in _SESSION_VAR_NAMES):
                continue
            method = child.func.attr
            if method not in _WRITE_METHODS or not child.args:
                continue
            table = self._resolve_table(child.args[0], var_types)
            self.sites.append(
                WriteSite(file=self.file, line=child.lineno, method=method, table=table, expr=ast.unparse(child))
            )

    def _call_class_name(self, call: ast.Call) -> str | None:
        if isinstance(call.func, ast.Name) and call.func.id in self.known:
            return call.func.id
        return None

    def _select_class_name(self, expr: ast.expr) -> str | None:
        """式の中に`select(ClassName)`があれば、そのClassNameを返す."""
        for node in ast.walk(expr):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "select":
                for arg in node.args:
                    if isinstance(arg, ast.Name) and arg.id in self.known:
                        return arg.id
        return None

    def _resolve_expr_class(self, expr: ast.expr, query_var_types: dict[str, str]) -> str | None:
        """`ClassName(...)`/`session.get(ClassName, ...)`/`session.exec(...).first()`系を解決する."""
        if isinstance(expr, ast.Call):
            cls = self._call_class_name(expr)
            if cls is not None:
                return cls
        for node in ast.walk(expr):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if (
                    node.func.attr == "get"
                    and node.args
                    and isinstance(node.args[0], ast.Name)
                    and node.args[0].id in self.known
                ):
                    return node.args[0].id
                if node.func.attr == "exec" and node.args:
                    arg0 = node.args[0]
                    if isinstance(arg0, ast.Name) and arg0.id in query_var_types:
                        return query_var_types[arg0.id]
        return self._select_class_name(expr)

    def _iterable_class_name(
        self, iter_expr: ast.expr, var_types: dict[str, str], query_var_types: dict[str, str]
    ) -> str | None:
        if isinstance(iter_expr, ast.Name) and iter_expr.id in var_types:
            return var_types[iter_expr.id]
        return self._resolve_expr_class(iter_expr, query_var_types)

    def _resolve_table(self, arg: ast.expr, var_types: dict[str, str]) -> str | None:
        cls: str | None = None
        if isinstance(arg, ast.Call):
            cls = self._call_class_name(arg)
        elif isinstance(arg, ast.Name):
            cls = var_types.get(arg.id)
        return self.known.get(cls) if cls is not None else None


def _module_table_name_constant(tree: ast.Module) -> str | None:
    """モジュール直下の`_TABLE_NAME = "..."`定数があれば値を返す(vector_store.py向け)."""
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "_TABLE_NAME"
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value
    return None


def _audit_raw_sql(file: Path, tree: ast.Module) -> list[WriteSite]:
    """`conn.exec_driver_sql(...)`呼び出しを検出する(ORM経由ではないため断定はしない)."""
    table_hint = _module_table_name_constant(tree)
    note = f"モジュール定数 _TABLE_NAME='{table_hint}' から推測(SQL文自体は未検証)" if table_hint else ""
    return [
        WriteSite(
            file=file,
            line=node.lineno,
            method="raw_sql",
            table=table_hint,
            expr="conn.exec_driver_sql(...)",
            note=note,
        )
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "exec_driver_sql"
    ]


def main() -> None:
    """全書き込み箇所をテーブル別にグルーピングして標準出力に一覧表示する."""
    known = _entity_table_map()
    repo_root = _SRC_ROOT.parent.parent
    all_sites: list[WriteSite] = []

    for path in sorted(_SRC_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        auditor = _FunctionAuditor(path, known)
        auditor.visit(tree)
        all_sites.extend(auditor.sites)
        all_sites.extend(_audit_raw_sql(path, tree))

    by_table: dict[str, list[WriteSite]] = {}
    unresolved: list[WriteSite] = []
    for site in all_sites:
        bucket = unresolved if site.table is None else by_table.setdefault(site.table, [])
        bucket.append(site)

    for table in sorted(by_table):
        print(f"## {table}")
        for site in by_table[table]:
            suffix = f"  # {site.note}" if site.note else ""
            print(f"  {site.file.relative_to(repo_root)}:{site.line}  {site.method}: {site.expr}{suffix}")
        print()

    if unresolved:
        print("## (未解決 — 手動確認が必要)")
        for site in unresolved:
            print(f"  {site.file.relative_to(repo_root)}:{site.line}  {site.method}: {site.expr}")


if __name__ == "__main__":
    main()
