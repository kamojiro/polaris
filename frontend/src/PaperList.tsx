export interface PaperSummary {
  title: string;
  authors: string[];
  year: number | null;
  arxiv_id: string | null;
}

export interface PaperListResult {
  papers: PaperSummary[];
  total_count: number;
}

/**
 * list_papers ツールの結果を専用テーブルとして描画する(generative UI)。
 * LLM にテキストで一覧を列挙させない代わりに、この構造化データをそのまま表示する。
 *
 * 件数の絞り込み(直近N件)はバックエンド側(SQL LIMIT)で行っており、ここでは
 * 受け取った件数をそのまま表示するだけ。省略した件数は total_count との差分で出す。
 */
export function PaperList({ papers, total_count: totalCount }: PaperListResult) {
  if (papers.length === 0) {
    return <p className="paper-list-empty">保存済みの論文はまだありません。</p>;
  }

  const hiddenCount = totalCount - papers.length;

  return (
    <div className="paper-list-wrapper">
      <table className="paper-list">
        <thead>
          <tr>
            <th>タイトル</th>
            <th>著者</th>
            <th>年</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {papers.map((paper) => (
            <tr key={paper.arxiv_id ?? paper.title}>
              <td>{paper.title}</td>
              <td>{paper.authors.join("、")}</td>
              <td>{paper.year ?? "-"}</td>
              <td>
                {paper.arxiv_id !== null && (
                  <a href={`https://arxiv.org/abs/${paper.arxiv_id}`} target="_blank" rel="noreferrer">
                    arXiv ↗
                  </a>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {hiddenCount > 0 && <p className="paper-list-more">他 {hiddenCount} 件</p>}
    </div>
  );
}
