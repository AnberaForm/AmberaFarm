# v9.3.0 更新手順

1. `AmberaFarm_v9_3_0_Root_Upload.zip` を展開し、中のファイルを GitHub の main 直下へアップロードしてコミット。
2. `AmberaFarm_v9_3_0_Tests_Upload.zip` を展開し、中のファイルを `tests` フォルダへアップロードしてコミット。
3. `AmberaFarm_v9_3_0_Avatars_Upload.zip` を展開し、歩行画像7枚を `assets/avatars` へ追加してコミット。以前の表情画像28枚はそのまま使用します。
4. 3つを反映してから Actions の **Build Ambera Farm Windows EXE → Run workflow → main** を実行。

`version.json` は **9.3.0**。今回のリリースタグは **v9.3.0** を使用します。
ソースの変更と画像の追加を済ませてからビルドします。

ActionsはPythonのテストに加え、生成したWindows EXEで112コマの読み込み、画面表示、キー入力、CPU移動、シュートのスモークテストを行います。

タグのビルドでは次の配布ファイルを生成する既存の仕組みを利用します。

- `AmberaFarm_Windows_v9.3.0.zip`
- `AmberaFarm_payload_v9.3.0.zip`
- `update_manifest.json`

この作成環境ではWindows EXEはビルドしていません。Actionsの成功後、Windowsでキャラ移動・カブボール・釣りと、別PCとのオンラインプレイを確認してください。

`AmberaFarm_v9_3_0_FullSource.zip` はすべてのソースと画像を含む、バックアップ・開発・Python実行向けの一式です。
`AmberaFarm_v9_3_0_GitHub_Update_Files.zip` はフォルダ構成を維持した統合差分です。上記の分割3ファイルとゲームの変更内容は同じです。追加のプレビュー生成スクリプトは `tools` に入っていますが、ゲーム起動には不要です。

オンラインの通信プロトコルは12。参加者全員を同じ版へ更新してください。セーブの初期化は不要です。
