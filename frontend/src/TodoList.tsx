export interface TodoSummary {
  id: string;
  title: string;
  description: string;
  scale: "day" | "month" | "life";
  done: boolean;
  updated_at: string;
  completed_at: string | null;
}

export interface TodoListResult {
  todos: TodoSummary[];
}

const SCALE_ORDER: TodoSummary["scale"][] = ["day", "month", "life"];

const SCALE_LABELS: Record<TodoSummary["scale"], string> = {
  day: "1日以内",
  month: "1ヶ月以内",
  life: "一生のうち",
};

/**
 * list_todos ツールの結果を、バケット(day/month/life)ごとにグルーピングした
 * 専用リストとして描画する(generative UI)。PaperList.tsx と同じ考え方で、
 * LLM にテキストで一覧を列挙させない代わりにこの構造化データをそのまま表示する。
 *
 * バックエンド側で既に「熟成度(最終更新日からの経過が長い順)」にソート済みの
 * 配列が返るため、ここではバケットごとに filter するだけで順序は保たれる。
 * v1は表示のみで、完了・編集・削除は引き続きチャットのテキストで行う。
 */
export function TodoList({ todos }: TodoListResult) {
  if (todos.length === 0) {
    return <p className="todo-list-empty">TODOはまだありません。</p>;
  }

  return (
    <div className="todo-list-wrapper">
      {SCALE_ORDER.map((scale) => {
        const bucket = todos.filter((todo) => todo.scale === scale);
        if (bucket.length === 0) {
          return null;
        }
        return (
          <div key={scale} className="todo-bucket">
            <h4>{SCALE_LABELS[scale]}</h4>
            <ul className="todo-list">
              {bucket.map((todo) => (
                <li key={todo.id} className={todo.done ? "todo-done" : undefined}>
                  <span className="todo-title">{todo.title}</span>
                  {todo.description !== "" && <span className="todo-description">{todo.description}</span>}
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </div>
  );
}
