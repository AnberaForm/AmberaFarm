# v9.4.0 画像の配置を自動修復する修正版

2026-10-22

## 今回確認した原因

実際のGitHub main（2f2181a1044e3dcbd6080ca3632a39a7a678511e）を取得して調査しました。
画像はアップロードされていましたが、home.png等がmain直下にあり、プログラムが探すassets/scenes/とassets/scenery/がありませんでした。
修正版テストもmain直下に置かれ、testsフォルダ内では以前の検査が実行されていました。

## 反映するファイル

このZIPに含まれる次の4つのPythonファイルを、GitHubのmain直下へ上書きしてください。

- asset_layout.py
- pixel_art.py
- build_windows.py
- updater.py

アップロード画面:
https://github.com/AnberaForm/AmberaFarm/upload/main

Commit changesで保存後、Actionsの「Build Ambera Farm Windows EXE」でmainを選び、Run workflowを新しく実行してください。

## 動作

ゲームの起動時とWindows用EXEの作成前に、main直下にあるPNG12枚を正しいassets/scenes/・assets/scenery/へ自動コピーします。
既に正しい場所にあるファイルを維持し、コピー元のPNGも残します。
元画像と内容が一致する場合だけ復元するため、同じ名前の建物外観画像と室内画像を区別できます。
home (6).png等の番号付きの名前にも対応しています。

## 確認した結果

GitHub版の失敗していたテストをそのまま実行して再現した後、今回の4ファイルだけを修正しました。
実際にGitHubで実行対象となっている180件のテストと12サブテスト、起動テストが成功しました。
画像の不足を無視する変更は加えていません。
Windows実機でのEXE操作は未検証です。
