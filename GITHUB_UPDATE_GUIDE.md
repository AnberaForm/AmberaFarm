# v9.4.0 更新手順

対象: https://github.com/AnberaForm/AmberaFarm

今回は素材とプログラムの両方が必要です。3つのZIPを反映してからActionsを実行してください。

| ZIP | GitHubで開く場所 | アップロード内容 |
| --- | --- | --- |
| AmberaFarm_v9_4_0_Root_Upload.zip | main直下 | 展開した中身を、dataやtoolsのフォルダ構成を保ってアップロード |
| AmberaFarm_v9_4_0_Tests_Upload.zip | testsフォルダ | 展開したテストファイルをアップロード |
| AmberaFarm_v9_4_0_Assets_Upload.zip | main直下 | 展開したassetsフォルダを丸ごとアップロード |

AssetsのZIPは、先頭に `assets/` がある構成です。GitHubのassetsフォルダの中へそのまま入れると `assets/assets/` になるため、main直下へアップロードしてください。ブラウザで複数回に分けてアップロードしても構いません。

今回のRootにはv9.3.0で追加したモジュールも、Assetsには既存の歩行画像も含めています。v9.3.0が未反映の場合も、この3つをすべて反映してください。

`AmberaFarm_v9_4_0_GitHub_Update_Files.zip` は3つを正しいフォルダ位置へまとめた統合版です。gitで反映するときや、フォルダ構成を保って更新できる場合に利用できます。ブラウザではファイル数を分けられる上記3つが扱いやすい構成です。

`AmberaFarm_v9_4_0_FullSource.zip` はワークフローや過去の説明を含む全ソースのバックアップです。プレイヤー向けWindows実行ファイルは含みません。

## Actionsとリリース

1. Actionsの「Build Ambera Farm Windows EXE」をmainで実行。
2. テスト・Windowsビルド・EXEの起動テストが成功することを確認。
3. リリースタグを `v9.4.0` にします。`version.json` は `9.4.0` です。
4. タグのActionsでも成功し、以下の3ファイルが生成されたことを確認します。

- `AmberaFarm_Windows_v9.4.0.zip`
- `AmberaFarm_payload_v9.4.0.zip`
- `update_manifest.json`

## 遊ぶときの確認

- 自宅と温室で、室内が牧場画面へのダイアログではなく独立したゲームマップになる。
- WASDで歩き、家具やカウンターの近くでEを押して使う。
- 下の出口へ歩くと、入る前の入口付近へ戻る。
- 隣町のたね屋へ入り、買い物の後は店内 → 隣町 → アンベラ町と戻れる。
- Escでメニュー、バッグを閉じた後も同じマップに留まる。
- オンラインでは参加者全員をv9.4.0に揃える。
