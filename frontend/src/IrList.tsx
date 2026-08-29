export interface IrSummary {
  filer_name: string;
  doc_type_code: string | null;
  period_start: string | null;
  period_end: string | null;
  submit_datetime: string;
  doc_id: string;
}

export interface IrListResult {
  documents: IrSummary[];
  total_count: number;
}

/**
 * list_ir_documents ツールの結果を専用テーブルとして描画する(generative UI)。
 * PaperList.tsx と同じパターンだが、013-ir-analysis-domain のv1には「IR文書モード」が
 * 無い(spec「未決定事項」で見送り)ため、行クリックでの選択操作は持たない読み取り専用の一覧。
 *
 * 件数の絞り込み(直近N件)はバックエンド側(SQL LIMIT)で行っており、ここでは
 * 受け取った件数をそのまま表示するだけ。省略した件数は total_count との差分で出す。
 */
export function IrList({ documents, total_count: totalCount }: IrListResult) {
  if (documents.length === 0) {
    return <p className="ir-list-empty">保存済みのIR文書はまだありません。</p>;
  }

  const hiddenCount = totalCount - documents.length;

  return (
    <div className="ir-list-wrapper">
      <table className="ir-list">
        <thead>
          <tr>
            <th>提出者</th>
            <th>書類種別</th>
            <th>対象期間</th>
            <th>提出日</th>
          </tr>
        </thead>
        <tbody>
          {documents.map((doc) => (
            <tr key={doc.doc_id}>
              <td>{doc.filer_name}</td>
              <td>{doc.doc_type_code ?? "-"}</td>
              <td>
                {doc.period_start ?? "-"} 〜 {doc.period_end ?? "-"}
              </td>
              <td>{doc.submit_datetime.slice(0, 10)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {hiddenCount > 0 && <p className="ir-list-more">他 {hiddenCount} 件</p>}
    </div>
  );
}
