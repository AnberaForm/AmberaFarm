# アンベラ牧場 v9.7 アカウントの公開手順

既存の AmberaFarm Render Web Service で v14（旧Windows版）を維持しながら、v15 のアカウント・ゲーム処理を追加する。v9.7のWindows配布はサーバーを検証した後に行う。

1. ゲーム専用の永続PostgreSQLを用意する。Render Free の一時ディスクにプレイヤーのデータを置かない。既存の別サービスのDBを変更しない。
2. DB管理者で、ランダムなパスワードを持つ `LOGIN NOINHERIT` ロール `ambera_game_service` を作る。一度だけ `deployment/account_schema.sql` を適用する。アプリはこの専用ロールだけを使う。公開Data APIに `ambera_game` を追加しない。
3. Renderの本番サービスに `AMBERA_DATABASE_URL` をSecretとして設定する。URLは専用ロールのPostgreSQL接続先。Supabaseの共有トランザクションプールの場合は組織の接続情報にあるホスト、ポートと `ambera_game_service.<project-ref>` を使う。クライアントへ渡さない。DB通信はサーバー名とTLS証明書を検証する。
4. ゲームとサーバーの同じ更新コミットを、現在の Render サービスにデプロイする。既存のビルド・起動コマンドは `pip install -r requirements-relay.txt` / `python relay_server.py`。アカウントDBが設定されている場合、起動時に3テーブルへアクセスできることを確認する。
5. HTTPS `/health` が `accounts: true` であること、合成データだけを使った登録・再ログイン・旧セーブ移行・公開部屋の承認・別の部屋でのオンライン進行の再開・サービス再起動後の保存保持を確認する。それからタグ `v9.7.0` でWindows CIを実行する。CIはサーバーの準備ができていないと更新マニフェストを公開しない。

通常・オンラインの各データはDBの `(account_id, mode)` 主キーで1件に制限する。クライアントから書き込めるのは自分の通常セーブだけ。オンラインの登録・更新はゲームサーバーが行う。パスワードはソルト付きscrypt、セッショントークンはハッシュを保管する。アカウント・セーブのバックアップを定期的に取得し、同じ版のテストDBに復元できることを検証する。ログにパスワードやDB接続文字列を記録しない。

## ローカルで試す

`python -m pip install -r requirements.txt -r requirements-relay.txt` を実行し、`python deployment/preview_account_game.py` を起動します。SQLiteを使う試用環境が立ち上がり、試用版専用のサンプル牧場で、登録・引き継ぎ・オンラインモードを試せます。公開サーバーへのログインや製品版の旧セーブには触れません。

```text
python -m pytest -q tests
python -m unittest -q verify_online_rooms verify_room_lobby
python ambera_farm.py --smoke-test
python verify_release_tag.py --tag v9.7.0
```
