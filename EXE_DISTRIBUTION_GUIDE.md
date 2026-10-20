# アンベラ牧場 v0.6.0 — Windows EXE配布・自動更新ガイド

## 仕組み

初回配布は `AmberaFarm_Windows_v0.6.0.zip`。プレイヤーはZIPを展開し、**`AmberaFarm.exe` をダブルクリック**するだけで遊べます。Python/Pygameのインストールは不要です。

```text
AmberaFarm/
  AmberaFarm.exe                  ← 更新確認してからゲームを起動（固定ランチャー）
  update_config.json              ← 更新URL（配布者が指定）
  version.json                    ← 現在のゲームバージョン
  app/
    AmberaGame.exe               ← Pygameゲーム本体・作物画像を内蔵
    AmberaStoryEditor.exe        ← ストーリー管理画面
```

`AmberaFarm.exe` → GitHub Releasesの `update_manifest.json` をHTTPSで確認 → 新版があればゲームEXEをダウンロード → SHA-256検証 → **ゲームが動く前に**旧ゲームEXEを更新 → ゲームを起動します。ネットがない場合・更新エラーの場合は、既存ゲームを起動します。セーブ・カスタムストーリーは `%APPDATA%\AmberaFarm` にあり、更新対象外です。

**更新されるのは `app/` 内のゲーム本体EXEとストーリー編集EXEです。** 安定したランチャー `AmberaFarm.exe` 自体の自動更新は今回実装していません。将来的にランチャー自体を変更する場合は再配布が必要です。

## 配布側の最初の設定（GitHubを利用）

1. **公開GitHubリポジトリ**を作る。例 `yourname/AmberaFarm`。公開ゲームの配信を意図しているので公開リポジトリが必要です。ZIP内にはゲームコード・画像が含まれるため、著作権や秘匿情報がある場合は確認してください。
2. このフォルダにあるソース、`.github/workflows/windows_release.yml`、`assets/crops/*.png` 等を、ディレクトリ構造を維持してGitHubにアップロードする。`.github` を欠かさないでください。
3. `version.json` の `version` を確認（初回は `0.6.0`）。
4. GitHubのリポジトリでリリースタグ `v0.6.0` を付けてプッシュする（コマンド例は下記）。
5. GitHub → **Actions** → **Build Ambera Farm Windows EXE** で成功したことを確認。
6. GitHub → **Releases** → `v0.6.0` から `AmberaFarm_Windows_v0.6.0.zip` をダウンロードして動作確認し、プレイヤーにURLを配布する。

```bash
git add .
git commit -m "AmberaFarm v0.6.0"
git tag v0.6.0
git push origin main
git push origin v0.6.0
```

ブランチ名が `master` の場合は `git push origin master` としてください。実際の初回リリースにはGitHub側のリポジトリ作成・pushが必要です。

### 次の更新を公開するとき

1. ソースコードを変更。必要なら`assets/crops/`の追加やストーリーデータの変更を行う。元のドット絵は勝手に変更しないこと。
2. `version.json` の数値を一段階上げる。例 `0.6.0` → `0.6.1`。
3. 変更をGitHubにpushした上で、同じ数値のリリースタグ `v0.6.1` を付けてpush。
4. GitHub ActionsがWindows用EXE、新版ZIP、固定名の `update_manifest.json` を自動生成してReleasesに公開。
5. プレイヤーは **今までどおり `AmberaFarm.exe` を起動するだけ**で新版を取得できます。再度ZIPをダウンロードしてもらう必要はありません。

**重要：** リリースを `draft` や `prerelease` にすると `/releases/latest/` には反映されません。通常の公開リリースにしてください。GitHubの公開リポジトリ・Releasesを使用するため、接続できない場合は更新をスキップします。

### 手動でWindows上でビルドするとき

1. `BUILD_EXE_WINDOWS.cmd` を実行。`build_output/exe/` 内に3つのEXEができます。
2. `python pack_windows_release.py --repo YOURNAME/REPO --version 0.6.0` を実行。
3. `build_output/release/` の配布ZIP、更新ZIP、manifestを同じGitHub Releaseの添付ファイルとしてアップロードしてください。

Windows上で実行しないとWindows向けEXEはビルドされません。このチャットの実行環境はLinuxのため**実EXEの生成とWindows起動検証はしていません**。GitHub ActionsのWindows環境での生成・プレイヤーのWindows実機検証が必要です。

## セーブ・ストーリー・オンライン

- セーブファイルは `%APPDATA%\AmberaFarm\save.json`、手動ストーリーは `%APPDATA%\AmberaFarm\story_events.json` のままです。更新時に変更しません。
- ストーリー管理画面にはローカル簡易認証（コード admin / パスワード pass123）が付きます。配布EXEから認証情報を解析できるため、本格的なアクセス制御ではありません。
- ストーリー管理画面はゲームメニューまたは `app/AmberaStoryEditor.exe` から開けます。
- `assets/crops/` の11個のPNGはPyInstallerビルド時にEXEに埋め込まれます。現在 `kin_ringo.png` は未収録です。
- オンライン v0.6.0 は畑のみ共有し、所持金・種・作物・魚・ミッションは参加者ごとに独立します。v0.5.0以前とは通信互換性がありません。
- オンライン協力プレイは従来どおり、ホストとIP・PINで接続する方式です。自動更新はオンライン協力プレイの公開サーバー化ではありません。
- 配布後のセキュリティ警告を減らすにはコード署名証明書と署名手順の導入が推奨されます。**現時点のEXEは署名していません。**

## 更新に関する安全上の制約

- HTTPSを必須とし、`update_manifest.json` に記載されたSHA-256と更新ZIPを照合します。
- GitHub Releaseのmanifestと更新ZIPのリポジトリが一致することを確認します。
- ZIPに入れられる更新ファイルは `app/AmberaGame.exe`、`app/AmberaStoryEditor.exe`、`version.json` の3ファイルだけです。パスのすり替えやZIP展開時のディレクトリ脱出を拒否します。
- ファイルはステージング後に置換し、失敗時は変更済みファイルを可能な限り元へ戻します。
- 配信元GitHubアカウント自体の侵害やマルウェア付きの正規配布物にはSHA-256だけでは対抗できません。信頼できるリポジトリで運用し、可能ならコード署名を行ってください。
- EXEランチャーは、自分が起動したゲームの終了まで動作を待ちます。このためゲーム実行中に同じランチャーをもう一度起動しても更新を開始しません。

### ログ・問題が起きた場合

`%APPDATA%\AmberaFarm\exe_launcher.log` を開いてください。Pygameゲームエラーは `%APPDATA%\AmberaFarm\error.log` に記録されます。更新失敗時は前のゲームでプレイできます。正常な配布ZIPから手動で復旧することも可能です。
