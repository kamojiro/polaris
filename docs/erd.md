# ER図

`domain/entities.py`のSQLModelから`paracelsus`で自動生成する(ADR-0014)。コード変更のたびに手で更新する文書ではなく、`uv run nox -s erd`で再生成すること(通常の`uv run nox`にも組み込まれている)。手動で編集しないこと。

<!-- BEGIN_SQLALCHEMY_DOCS -->
```mermaid
erDiagram
  ambient_voice_chunk_records {
    VARCHAR id PK
    INTEGER attempts
    VARCHAR comment "nullable"
    DATETIME completed_at "nullable"
    DATETIME created_at
    VARCHAR error "nullable"
    VARCHAR previous_comment "nullable"
    DATETIME started_at "nullable"
    VARCHAR status "indexed"
    VARCHAR transcript
    BOOLEAN worth_reacting "nullable"
  }

  chunks {
    VARCHAR id PK
    VARCHAR item_id FK "indexed"
    INTEGER order
    VARCHAR section "nullable"
    VARCHAR text
  }

  daily_summary_records {
    VARCHAR id PK
    VARCHAR content
    DATETIME generated_at
    DATE summary_date UK "indexed"
  }

  diary_events {
    VARCHAR id PK
    DATE entry_date "indexed"
    VARCHAR raw_text
    DATETIME recorded_at
    VARCHAR source_conversation_turn
  }

  diary_records {
    VARCHAR id PK
    VARCHAR item_id FK "indexed"
    VARCHAR content
    DATE entry_date UK "indexed"
    DATETIME updated_at
  }

  ir_records {
    VARCHAR id PK
    VARCHAR item_id FK "indexed"
    VARCHAR doc_id UK "indexed"
    VARCHAR doc_type_code "nullable"
    VARCHAR edinet_code "nullable"
    VARCHAR filer_name
    DATETIME ingested_at
    VARCHAR pdf_path "nullable"
    DATE period_end "nullable"
    DATE period_start "nullable"
    DATETIME submit_datetime
  }

  items {
    VARCHAR id PK
    DATETIME created_at
    ENUM item_type
    VARCHAR source_ref
    VARCHAR summary
    VARCHAR title
  }

  memory_events {
    VARCHAR id PK
    DATETIME extracted_at
    VARCHAR raw_text
    VARCHAR source_conversation_turn
    VARCHAR theme "indexed"
  }

  memory_housekeeping_suggestions {
    VARCHAR id PK
    VARCHAR detail
    DATETIME generated_at "indexed"
    VARCHAR suggestion_type
    VARCHAR target_themes
  }

  memory_themes {
    VARCHAR slug PK
    VARCHAR description
    DATETIME updated_at
  }

  news_records {
    VARCHAR id PK
    VARCHAR item_id FK "indexed"
    DATETIME published_at
    VARCHAR source_label
    VARCHAR source_name
    VARCHAR source_url UK "indexed"
  }

  paper_deep_analysis_records {
    VARCHAR id PK
    VARCHAR item_id FK "indexed"
    DATETIME created_at
    VARCHAR problem
    VARCHAR solution
  }

  paper_records {
    VARCHAR id PK
    VARCHAR item_id FK "indexed"
    VARCHAR abstract
    VARCHAR arxiv_id UK "nullable,indexed"
    JSON authors "nullable"
    VARCHAR doi "nullable"
    DATETIME ingested_at
    VARCHAR pdf_path "nullable"
    VARCHAR source_url "nullable"
    VARCHAR text_path "nullable"
    VARCHAR venue "nullable"
    INTEGER year "nullable"
  }

  paper_research_discovered_papers {
    VARCHAR id PK
    VARCHAR item_id FK "indexed"
    VARCHAR research_id FK "indexed"
    DATETIME discovered_at
  }

  paper_research_records {
    VARCHAR id PK
    VARCHAR seed_item_id FK "indexed"
    INTEGER attempts
    DATETIME completed_at "nullable"
    DATETIME created_at
    VARCHAR error "nullable"
    VARCHAR result_summary "nullable"
    VARCHAR seed_title
    DATETIME started_at "nullable"
    VARCHAR status "indexed"
  }

  todo_records {
    VARCHAR id PK
    VARCHAR item_id FK "indexed"
    DATETIME completed_at "nullable"
    BOOLEAN done
    ENUM scale
    DATETIME updated_at
  }

  items ||--o{ chunks : item_id
  items ||--o{ diary_records : item_id
  items ||--o{ ir_records : item_id
  items ||--o{ news_records : item_id
  items ||--o| paper_deep_analysis_records : item_id
  items ||--o{ paper_records : item_id
  items ||--o| paper_research_discovered_papers : item_id
  paper_research_records ||--o{ paper_research_discovered_papers : research_id
  items ||--o{ paper_research_records : seed_item_id
  items ||--o{ todo_records : item_id

```
<!-- END_SQLALCHEMY_DOCS -->
