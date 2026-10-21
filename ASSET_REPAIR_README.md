# v9.4.0 画像読み込み・Actions 修正

2026-10-22

画像で確認できた失敗箇所は、`game.pixel_art.complete()` の検査です。
必要な背景・小物・魚画像の読み込みが揃っていない状態で止まっています。元のログにはファイル名が出ていなかったため、画像の再同梱と診断の改善をまとめました。

## 反映する場所

1. `AmberaFarm_v9_4_0_AssetRepair.zip` を展開します。
2. https://github.com/AnberaForm/AmberaFarm/upload/main を開きます。
3. 展開した中のファイルとフォルダを、GitHubのmain直下へまとめて上書きし、コミットします。
4. Actionsの「Build Ambera Farm Windows EXE」で、mainを指定して「Run workflow」を新しく実行します。

ZIP内では、最初からリポジトリ直下へ置く構成になっています。
`assets`フォルダはmain直下へ反映してください。追加画像は次の場所に入ります。

- `assets/scenes/` — 自宅・温室など9施設と隣町の背景10枚
- `assets/scenery/props.png` — 小物16種
- `assets/scenery/fish.png` — 魚8種

今回のZIPには、ゲーム側の読み込み診断、自動テスト、Actionsの事前確認も含みます。
バージョン番号は9.4.0のままです。

## 修正した診断

- 画像が不足している場合、その正確なパスを表示。
- `assets/assets/scenes/` などの配置違いが見つかると、移動先を表示。
- 壊れたPNGは、ファイル名と読み込みエラーを表示。
- アトラスの該当部分が透明な場合、元画像と該当する小物・魚を表示。
- Actionsでテスト前に背景10枚・スプライト24種の読み込みを確認。

画像の検査は維持しています。
同梱する12枚のPNGは、前回生成した正しい画像をそのまま使用しています。
既存の作物・キャラ・建物画像やセーブ形式は変更していません。

## ローカルで確認する場合

```bash
python tools/check_pixel_assets.py
python -m pytest -q tests
python ambera_farm.py --smoke-test
```

不足時の出力例:

```text
Pixel-art assets: backgrounds 9/10, sprites 24/24
  assets/scenes/home.png: missing file
```
