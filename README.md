# Threads法人集客LINE Bot

LINEだけでThreads投稿候補の生成、選択、修正、最終確認、Threads投稿、投稿データ保存、反応データ分析を行うBotです。

## 今回の最適化方針

- サーバー: Render
- アプリ: Python + FastAPI
- 保存先: SQLite
- AI: OpenAI API
- 操作画面: LINE
- Threads投稿: Meta公式Threads API
- 対象アカウント: 法人向けThreadsアカウント1つ
- DM、競合調査、他人投稿収集、スクレイピング、管理画面は入れていません

## できること

- 毎朝7:00、LINEへThreads投稿候補を5案送信
- LINEで「候補」と送ると、いつでも5案生成
- ①〜⑤から1つ選択
- 作り直し
- 修正文の送信
- AIで整える
- 最終確認後だけThreadsへ投稿
- 投稿本文、カテゴリ、日時、Threads投稿ID、分析データをSQLiteに保存
- likes / replies / reposts / quotes / views / shares の取得を試み、交流重視でスコア化
- 翌日の候補生成に過去分析を反映

## 最初にやること

### 1. LINE Developersで設定する

1. [LINE Developers](https://developers.line.biz/console/) を開く
2. Providerを作る
3. Messaging APIチャネルを作る
4. 「Channel secret」をコピーする
5. 「Messaging API」タブで「Channel access token」を発行してコピーする
6. Webhookは、Render公開後に表示されるURLの末尾へ `/line/webhook` を付けて設定する
   - 例: `https://あなたのアプリ名.onrender.com/line/webhook`
7. 「Use webhook」をオンにする

### 2. OpenAI APIキーを用意する

1. [OpenAI Platform](https://platform.openai.com/api-keys) を開く
2. APIキーを作成する
3. 生成されたキーをコピーする

### 3. Meta Threads APIを設定する

Meta for DevelopersでThreads APIが使えるアプリを作り、少なくとも以下の権限を使える状態にしてください。

- `threads_basic`
- `threads_content_publish`
- `threads_manage_insights`

取得したアクセストークンを `THREADS_ACCESS_TOKEN` に入れます。

## Renderへ置く

1. このフォルダをGitHubへアップロードする
2. Renderで「New Web Service」を選ぶ
3. GitHubリポジトリを選ぶ
4. Environment Variablesに `.env.example` の中身を登録する
5. `LINE_CHANNEL_SECRET`、`LINE_CHANNEL_ACCESS_TOKEN`、`OPENAI_API_KEY`、`THREADS_ACCESS_TOKEN` を貼る
6. デプロイする
7. RenderのURL + `/line/webhook` をLINE DevelopersのWebhook URLへ貼る

## LINE_USER_IDについて

`LINE_USER_ID` は空でも大丈夫です。

BotをLINEで友だち追加すると、最初に届いたイベントから自動保存します。その後、毎朝7:00の配信先として使われます。

## 使い方

- 投稿候補が欲しい: `候補`
- 候補から選ぶ: `①` `②` `③` `④` `⑤`
- 作り直す: `作り直す`
- 選んだ候補をそのまま進める: `このまま投稿`
- 自分で直す: `修正する`
- AIに整えてもらう: `AIで整える`
- 最終投稿: `投稿する`
- 中止: `やめる`

## ローカルで試す

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

LINEからローカルへWebhookを送るにはngrokなどが必要です。初心者運用ではRenderに置いて試すほうが簡単です。

## 注意

- 承認前にThreadsへ自動投稿しません。
- 「投稿する」を押した時だけThreadsへ投稿します。
- DM関連機能はありません。
- 競合リサーチや他人投稿収集はありません。
- Threads APIの権限や指標はMeta側の仕様変更で変わることがあります。
