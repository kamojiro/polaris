"""どのコードがどのrepositoryメソッドを呼んでいるかをASTで監査する(ADR-0014).

常設ドキュメント化はせず、必要になった都度このスクリプトを実行して最新の状態を得る運用
(ADRの決定通り)。`uv run python scripts/audit_table_usage.py`で実行する。

改訂(2026-09-13、`docs/adr/0014-documentation-freshness-policy.md`項目2参照): 当初の
`scripts/audit_table_writes.py`は`session.add/merge/delete`という生のORM呼び出しをASTで
grepする書き込み専用の設計だった。polarisは全DBアクセスが`db/*_repository.py`の
repositoryクラスのメソッド経由に統一されているため、**各repositoryメソッドの呼び出し元を
列挙する**方式に作り直した。生のORM呼び出しパターンを判定するより単純かつ正確で、
`find_*`/`list_*`のような読み込み系メソッドも同じ仕組みでそのまま拾える(読み書き両方を
1つの仕組みでカバーできる)。旧`audit_table_writes.py`は削除した。

対象: `src/polaris/db/*repository*.py`(`repository.py`本体・`*_repository.py`一式。
`session.py`・`vector_store.py`はrepositoryパターンの外側にある素のSQLite直叩きのため対象外)
の各クラスの公開メソッド(アンダースコア始まりを除く)。

呼び出し元の受信オブジェクトの型は次の優先順で推定する(完全な型推論ではないヒューリスティック):

1. 関数・メソッドの引数の型注釈(例: `repo: PaperRepository`。このコードベースの規約で
   repositoryは常に型注釈付きの引数として渡されるため、これが主な解決経路になる)
2. 同じ関数内で`X = ClassName(...)`という代入
3. `__init__`等で`self.X = ClassName(...)`(またはそれ自体が型注釈済み引数)という代入
   (以降そのクラスの他メソッド内での`self.X.method()`をそのクラスの属性として解決する)

上記で型が分からない場合でも、メソッド名がちょうど1つのrepositoryクラスにしか
存在しなければそのクラスの呼び出しとして扱う(型推定なしである旨を注記する)。複数の
repositoryクラスに同名メソッドがある場合(例: `save`)は「未解決」として出力する
(誤った断定より「わからない」と正直に言う方が監査ツールとして安全なため)。

既知の限界: ネストした関数(クロージャ)は外側とは独立に自分自身のスコープだけを見て
監査する。`self`を経由しない多段の属性チェーン(`ctx.deps.repo.method()`等)や、
repositoryではない無関係なオブジェクトへの同名メソッド呼び出し(型注釈もローカル代入も
無い場合)は解決できないことがある。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

_SRC_ROOT = Path(__file__).resolve().parent.parent / "src" / "polaris"
_DB_ROOT = _SRC_ROOT / "db"


@dataclass
class RepoInfo:
    """1つのrepositoryクラスの情報."""

    file: Path
    methods: set[str]


def _load_repository_classes() -> dict[str, RepoInfo]:
    """`db/*repository*.py`をASTで読み、クラス名→公開メソッド集合を作る."""
    repos: dict[str, RepoInfo] = {}
    for path in sorted(_DB_ROOT.glob("*repository*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            methods = {
                item.name
                for item in node.body
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef) and not item.name.startswith("_")
            }
            if methods:
                repos[node.name] = RepoInfo(file=path, methods=methods)
    return repos


def _walk_own_scope(node: ast.AST) -> Iterator[ast.AST]:
    """`ast.walk`と同じだが、ネストした関数定義の内部には降りない(二重カウント防止)."""
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


def _call_class_name(expr: ast.expr, known: set[str]) -> str | None:
    """`ClassName(...)`という直接呼び出しであればクラス名を返す."""
    if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name) and expr.func.id in known:
        return expr.func.id
    return None


def _local_var_types(node: ast.FunctionDef | ast.AsyncFunctionDef, known: set[str]) -> dict[str, str]:
    """引数の型注釈・`X = ClassName(...)`代入から、関数内のローカル変数の型を推定する."""
    var_types: dict[str, str] = {}
    for arg in (*node.args.args, *node.args.kwonlyargs):
        cls = _annotation_class_name(arg.annotation, known)
        if cls is not None:
            var_types[arg.arg] = cls
    for child in _walk_own_scope(node):
        if isinstance(child, ast.Assign):
            cls = _call_class_name(child.value, known)
            if cls is not None:
                for target in child.targets:
                    if isinstance(target, ast.Name):
                        var_types[target.id] = cls
    return var_types


def _self_attr_types(class_node: ast.ClassDef, known: set[str]) -> dict[str, str]:
    """クラス内の全メソッドから`self.X = <repositoryクラスの式>`を集める(主に`__init__`向け)."""
    attrs: dict[str, str] = {}
    for item in class_node.body:
        if not isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        local_types = _local_var_types(item, known)
        for child in _walk_own_scope(item):
            if not isinstance(child, ast.Assign):
                continue
            for target in child.targets:
                if not (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                ):
                    continue
                cls = _call_class_name(child.value, known)
                if cls is None and isinstance(child.value, ast.Name):
                    cls = local_types.get(child.value.id)
                if cls is not None:
                    attrs[target.attr] = cls
    return attrs


@dataclass
class CallSite:
    """1箇所のrepositoryメソッド呼び出し."""

    file: Path
    line: int
    owner: str | None  # repositoryクラス名(Noneは未解決)
    method: str
    expr: str
    note: str = ""


class _CallCollector(ast.NodeVisitor):
    """1ファイル分を、クラス定義のネストを追いながらrepositoryメソッド呼び出しを集める."""

    def __init__(self, file: Path, repos: dict[str, RepoInfo], method_owners: dict[str, list[str]]) -> None:
        self.file = file
        self.repos = repos
        self.known = set(repos)
        self.method_owners = method_owners
        self.sites: list[CallSite] = []
        self._self_attrs_stack: list[dict[str, str]] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._self_attrs_stack.append(_self_attr_types(node, self.known))
        self.generic_visit(node)
        self._self_attrs_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._audit_function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._audit_function(node)
        self.generic_visit(node)

    def _audit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        var_types = _local_var_types(node, self.known)
        self_attrs = self._self_attrs_stack[-1] if self._self_attrs_stack else {}
        for child in _walk_own_scope(node):
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                self._audit_call(child, var_types, self_attrs)

    def _resolve_owner(self, receiver: ast.expr, var_types: dict[str, str], self_attrs: dict[str, str]) -> str | None:
        if isinstance(receiver, ast.Name):
            return var_types.get(receiver.id)
        if (
            isinstance(receiver, ast.Attribute)
            and isinstance(receiver.value, ast.Name)
            and receiver.value.id == "self"
        ):
            return self_attrs.get(receiver.attr)
        return None

    def _audit_call(self, call: ast.Call, var_types: dict[str, str], self_attrs: dict[str, str]) -> None:
        assert isinstance(call.func, ast.Attribute)  # noqa: S101 - 呼び出し元で確認済み
        method = call.func.attr
        owner = self._resolve_owner(call.func.value, var_types, self_attrs)
        note = ""
        if owner is None:
            candidates = self.method_owners.get(method, [])
            if len(candidates) == 1:
                owner, note = candidates[0], "型推定なし、メソッド名からの一意対応"
            elif len(candidates) > 1:
                self.sites.append(
                    CallSite(
                        file=self.file,
                        line=call.lineno,
                        owner=None,
                        method=method,
                        expr=ast.unparse(call),
                        note=f"複数のrepositoryクラスに同名メソッドあり: {', '.join(sorted(candidates))}",
                    )
                )
                return
            else:
                return  # repositoryのメソッド名と一致しないので監査対象外
        elif method not in self.repos[owner].methods:
            return  # 型は分かったがrepositoryの公開メソッドではない(無関係な同名メソッド)
        self.sites.append(
            CallSite(file=self.file, line=call.lineno, owner=owner, method=method, expr=ast.unparse(call), note=note)
        )


def main() -> None:
    """全repositoryメソッド呼び出しをクラス別・メソッド別にグルーピングして標準出力に一覧表示する."""
    repos = _load_repository_classes()
    method_owners: dict[str, list[str]] = {}
    for class_name, info in repos.items():
        for method in info.methods:
            method_owners.setdefault(method, []).append(class_name)

    repo_root = _SRC_ROOT.parent.parent
    all_sites: list[CallSite] = []
    for path in sorted(_SRC_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        collector = _CallCollector(path, repos, method_owners)
        collector.visit(tree)
        all_sites.extend(collector.sites)

    by_owner: dict[str, list[CallSite]] = {}
    unresolved: list[CallSite] = []
    for site in all_sites:
        bucket = unresolved if site.owner is None else by_owner.setdefault(site.owner, [])
        bucket.append(site)

    for owner in sorted(by_owner):
        print(f"## {owner}")
        by_method: dict[str, list[CallSite]] = {}
        for site in by_owner[owner]:
            by_method.setdefault(site.method, []).append(site)
        for method in sorted(by_method):
            print(f"  ### {method}")
            for site in by_method[method]:
                suffix = f"  # {site.note}" if site.note else ""
                print(f"    {site.file.relative_to(repo_root)}:{site.line}  {site.expr}{suffix}")
        print()

    if unresolved:
        print("## (未解決 — 手動確認が必要)")
        for site in unresolved:
            print(f"  {site.file.relative_to(repo_root)}:{site.line}  {site.method}: {site.expr}  # {site.note}")


if __name__ == "__main__":
    main()
