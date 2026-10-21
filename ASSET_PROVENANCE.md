# v9.3.0 歩行素材の作成記録

既存の7キャラの `assets/avatars/<キャラID>_0.png` を参考画像として、組み込みの **Imagegen** で各1枚ずつ生成しました。CLI/APIのフォールバックは使っていません。元の表情画像28枚と作物画像11枚は変更していません。

保存先は `assets/avatars/<キャラID>_walk.png`。各シートは4列×4行の透過RGBA PNGで、出力は1254×1254ピクセルです。ゲームでは端数を考慮して16セルに分け、全セルで共通の領域を切り出して足元の基準を保ちます。

キャラID: `original_girl`, `mint_girl`, `blue_girl`, `blonde_girl`, `farmer_boy`, `cafe_boy`, `silver_boy`。

## 各画像に使用したプロンプト

下の `<キャラID>` を上記7種それぞれに置き換え、同名の既存の待機画像を参考画像に指定しました。画像サイズは生成時の希望値であり、実際の出力サイズは上記のとおりです。

```text
Use case: identity-preserve. Asset type: game animation sprite sheet. Input image is the identity and costume reference for <キャラID>, not a sheet to reproduce. Create ONE TRANSPARENT PNG sprite sheet of THIS SAME character, preserving face, hair color, hairstyle, decorations, clothes and boots precisely. 1024x1024 square with a strict 4-column by 4-row grid of equal 256x256 cells, no gaps, no labels, no grid lines. In each cell place exactly one small full-body chibi farm-game sprite, identical consistent size, body centered at x=128 within the cell and feet baseline at y=224. Each character must fit inside x=48..208 and y=32..224. ROWS: row1 front/down view, row2 left profile facing left, row3 right profile facing right, row4 back/up view (back of head visible, NO face). COLUMNS: 1 neutral standing feet together, 2 walking left leg forward and right arm forward with visibly separated boots, 3 neutral standing feet together, 4 walking right leg forward and left arm forward. Maintain same camera elevation, identity, costume and body scale. Genuine articulated walk poses with arm and leg motion; not simply a bouncing or sliding standing portrait. Clean small-pixel JRPG chibi sprite style suitable for nearest-neighbor scaling at 48x64. Fully transparent background and no floor, no cast shadow, no UI, no text. All 16 cells fully drawn, none cropped, no overlapping adjacent cells.
```

`tools/render_v930_preview.py` は生成した画像をゲーム本体と同じ描画経路でアニメーション確認するスクリプトです。
