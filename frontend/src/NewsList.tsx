export interface NewsSummary {
  title: string;
  source_name: string;
  source_label: string;
  summary: string;
  published_at: string;
  source_url: string;
}

export interface NewsListResult {
  news: NewsSummary[];
}

const LABEL_ORDER = ["ai_llm", "swe_general", "jp_tech_blog", "tech_industry_news"];

const LABEL_NAMES: Record<string, string> = {
  ai_llm: "AI/LLM",
  swe_general: "ソフトウェア工学一般",
  jp_tech_blog: "日本のテックブログ",
  tech_industry_news: "テック業界ニュース",
};

// バケットごとに常時表示する件数。これを超える分は<details>で折りたたむ
// (1バケットあたり最大15件ほどになりうるため、全部並べると読みづらい)。
const VISIBLE_COUNT = 5;

function NewsItems({ items }: { items: NewsSummary[] }) {
  return (
    <ul className="news-list">
      {items.map((n) => (
        <li key={n.source_url} className={n.summary ? "news-item" : "news-item news-item-compact"}>
          <a href={n.source_url} target="_blank" rel="noreferrer" className="news-title">
            {n.title}
          </a>
          <span className="news-source-name">{n.source_name}</span>
          {n.summary && <p className="news-summary">{n.summary}</p>}
        </li>
      ))}
    </ul>
  );
}

/**
 * list_news ツールの結果を、source_label(情報源のラベル、対立軸の定義方針を参照)
 * ごとにグルーピングした専用リストとして描画する(generative UI)。TodoList.tsx の
 * バケット(day/month/life)分けと同じ考え方だが、1バケットの件数が多くなりがち
 * (最大15件/ラベル)なため、上位数件だけ常時表示し残りは<details>に畳む。
 *
 * バックエンド側で既に公開日時の降順にソート済みの配列が返るため、ここでは
 * ラベルごとに filter するだけで順序は保たれる。
 */
export function NewsList({ news }: NewsListResult) {
  if (news.length === 0) {
    return <p className="news-list-empty">取り込み済みのニュースはまだありません。</p>;
  }

  return (
    <div className="news-list-wrapper">
      {LABEL_ORDER.map((label) => {
        const bucket = news.filter((n) => n.source_label === label);
        if (bucket.length === 0) {
          return null;
        }
        const visible = bucket.slice(0, VISIBLE_COUNT);
        const rest = bucket.slice(VISIBLE_COUNT);
        return (
          <section key={label} className={`news-bucket news-bucket-${label}`}>
            <h4>
              {LABEL_NAMES[label] ?? label}
              <span className="news-bucket-count">{bucket.length}</span>
            </h4>
            <NewsItems items={visible} />
            {rest.length > 0 && (
              <details className="news-more">
                <summary>他{rest.length}件を表示</summary>
                <NewsItems items={rest} />
              </details>
            )}
          </section>
        );
      })}
    </div>
  );
}
