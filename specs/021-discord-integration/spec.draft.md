# 021. Discord連携

## ステータス

方向性3(Discordから読み取る)のみ✔️実装完了(2026-09-02)。方向性1(通知先)・方向性2
(代替フロントエンド)は引き続き💤未着手。

実装は下記「方向性3の設計たたき台」どおり: `adapters/discord/client.py`(自前httpxクライアント、
`GET /channels/{channel_id}/messages`)、`GET /api/discord/recent`(永続化なし、都度ライブ取得)、
`DiscordSidebar.tsx`(`NewsSidebar.tsx`と同型、クリックで`このDiscordメッセージについて
詳しく教えて: {本文}`を送信)。`DiscordSettings.bot_token`/`channel_id`が未設定の場合は
`/api/discord/recent`が空リストを返し、フロントはセクションごと非表示にする(未設定の
利用者に空セクションを見せないための挙動、NewsSidebarとの唯一の表示上の差分)。

## 概要

Discordとの連携。用途はまだ絞れていない(2026-08-23、雑談から着想)。考えられる方向性は3つ。

1. **通知先として使う**: `008-daily-digest-domain`の配信、TODOのリマインド通知など、Polarisから一方的にDiscordへメッセージを送る
2. **代替フロントエンドとして使う**: Discord bot経由でチャットエージェントと会話する。既存のReact UI(001)・将来のmobile-pwa(010)と並ぶ、もう1つのチャネルという位置づけ
3. **Discordから読み取る(inbound read、2026-09-02追記)**: 特定チャンネル(例: 「後で読む」チャンネル)の最新メッセージをPolaris側で読み取り、008の「ニュースピックアップサイドバー」と同じ見せ方(`Sidebar.tsx`/`NewsSidebar.tsx`)で画面に表示する。クリックすると、pickupの「『{タイトル}』について詳しく教えて {URL}」と同型のメッセージを送信してチャットの会話に繋げる導線を踏襲する

3方向とも独立して着手できるため、どれから先にやるかは未定のまま。

## 方向性3「Discordから読み取る」の設計たたき台(2026-09-02)

- **接続方式**: Discord bot token + REST APIの`GET /channels/{channel_id}/messages`(単一エンドポイント・bot token 1本の単純な認証)。`specs/IDEAS.md`の「MCP vs 自前adapter」判断基準(単一エンドポイント・簡単なAPIキー程度なら自前adapter)に従い、`018-web-search-tool`のSearXNGと同じく自前adapter(`adapters/discord/client.py`)を想定。サードパーティのDiscord MCPサーバーを挟むメリットは薄そう(ただし公式MCPの有無は未調査のまま)
- **永続化しない**: `NewsRecord`のようにDBへIngestする設計にはしない。「後で読む」チャンネルの**今の最新**を見せたいだけなので、サイドバー表示のたびにDiscord APIをライブに叩くだけの薄い実装にする(`web_fetch`と同種の「ステートレスに取得して見せるだけ」方針)。既読管理やチャンネル内の過去メッセージ一覧が欲しくなったら、その時点でNewsRecord同様のIngest+DB化を検討する
- **表示件数**: 最新5件(2026-09-02決定)。008のpickupと同じ並び数に揃える。ただしpickupは「取り込み済みニュースからランダムに5件」だが、こちらは`GET /channels/{channel_id}/messages?limit=5`で単純に直近5件を新しい順に取得するだけ(ランダム選出は不要、そもそも母集団が「未読キュー」的な性質のチャンネルなので新しい順の方が自然)
- **クリック時の送信文面**: Discordメッセージにはpickupの記事のような明確な「タイトル」が無い(自由記述のテキスト、URLが本文に含まれることもあれば無いこともある)。メッセージ本文をそのまま使って「このDiscordメッセージについて詳しく教えて: {本文}」のような文面を想定(URLが本文に含まれていれば、そのままweb_fetchに繋がる)
- **設定**: `DiscordSettings`(`settings.py`、`SearxngSettings`と同型)にbot token・監視対象チャンネルIDを持たせる

## 未決定事項

- 通知先/代替フロントエンド/Discordから読み取る、どれを優先するか(あるいは全部やるか)
- 既存のDiscord向けMCPサーバーの有無・成熟度は未調査(着手時に`018`と同様の調査が要る)
- 代替フロントエンドにする場合、既存のAG-UIベースのチャットエージェントをどう繋ぐか(Discord bot側でAG-UIプロトコルをどこまで再現する必要があるか)
- 方向性3: 表示件数を1件から増やしたい欲求が出るか、既読管理(同じメッセージを何度も表示しない)が要るか

## 依存

- 通知先として使う場合、`008-daily-digest-domain`・`007-todo-domain`のリマインド機能(将来spec)に依存しうる
- 方向性3(Discordから読み取る)は`008-daily-digest-domain`の「ニュースピックアップサイドバー」(`Sidebar.tsx`/`NewsSidebar.tsx`)のUIパターンに依存
