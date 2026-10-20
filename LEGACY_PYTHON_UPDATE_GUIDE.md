# AmberaFarm / 起動時自動アップデートの配信設定

**現状：更新機構は実装済みですが、配信先は未設定です。** 配信URLを用意してから初めて起動時更新が有効になります。今後、ユーザーは同じフォルダの `START_GAME.cmd` を起動するだけで更新を受け取れます。ソース版（Python実行）に対応しています。

## 配布側で最初の一度だけ設定

1. GitHub PagesやHTTPSで静的ファイルを置けるサーバーを用意します。`update_manifest.json` を常に同じURLで公開してください。
2. 配布する `update_config.json` に設定します。

```json
{
  "manifest_url": "https://YOUR-HOST.example/ambera/update_manifest.json",
  "auto_update": true
}
```

3. 配布時のゲームは展開フォルダ内で書き込みできる必要があります。ユーザーのセーブは `%APPDATA%\AmberaFarm` に別保存されます。
4. 更新時は `version.json` を上げます（例：`0.4.1`）。
5. 開発者が **MAKE_UPDATE.cmd** を実行し、実際に公開する更新ZIPのHTTPS URLを入力すると `release/` に更新ZIPと `update_manifest.json` が作られます。
6. 両方をURL先へアップロードします。ZIPのURLは `MAKE_UPDATE.cmd` で入力したものと同じにしてください。
7. 利用者が次回ゲームを起動すると、**ゲームプロセスが開始する前**に更新情報を確認し、新版をダウンロード、SHA-256照合後に更新します。更新失敗時はエラーをログに残して旧版の起動を続けます。

## 更新manifestの例

```json
{
  "version": "0.4.1",
  "package_url": "https://YOUR-HOST.example/ambera/AmberaFarm_update_0_4_1.zip",
  "sha256": "<MAKE_UPDATE.cmd が自動生成した64文字のSHA-256>",
  "notes": "マップを修正"
}
```

### 更新で保護するデータ

- `%APPDATA%\AmberaFarm\save.json` とバックアップ
- `%APPDATA%\AmberaFarm\story_events.json` （ストーリー管理画面で追加したユーザー作品）
- `update_config.json`（利用者の更新先設定）

許可されたゲームコードと配布用の画像ファイル以外は更新ZIPに含められません。HTTPS URLとダウンロードしたZIPのハッシュを確認します。**ただし、配信先アカウントが侵害された場合まで防ぐ電子署名システムではありません。信頼できる配信先だけを設定してください。**

### 制限

現状の更新は Python版専用です。`.exe` にパッケージ化した場合は別のブートストラップや差分更新配信の設計が必要です。GitHubへの公開や実際のアップデートURL設定はまだ済んでいません。サーバーへの自動アップロード機能もありません。
