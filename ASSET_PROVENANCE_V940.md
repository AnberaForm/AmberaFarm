# v9.4.0 画像素材・生成プロンプト

組み込みのImagegenで12枚のPNGを新規生成しました。CLI/APIのフォールバックは使っていません。10枚の背景と、16種の小物・8種の魚を含む2枚の透過アトラスです。生成したPNGのバイト列をそのままゲームに配置し、拡大・縮小やアトラスの切り出しはゲームの描画時に行います。元の作物やキャラ画像は変更していません。

背景の9施設とみずほ町は各1枚の生成です。みずほ町のたね屋は、たね屋の背景を使う独立したマップです。素材一覧とゲーム内での配置は下記のとおりです。小物シートは各物体の領域を指定して切り出し、隣の物体や脚の一部が混ざらないよう実際の表示で確認しました。

| 画像 | 保存先 | 内容 |
| --- | --- | --- |
| home | `assets/scenes/home.png` | 自宅 |
| greenhouse | `assets/scenes/greenhouse.png` | 温室 |
| shop | `assets/scenes/shop.png` | たね屋（みずほ町店内も使用） |
| cafe | `assets/scenes/cafe.png` | カフェ |
| hall | `assets/scenes/hall.png` | 集会所 |
| workshop | `assets/scenes/workshop.png` | 衣装工房 |
| shipping | `assets/scenes/shipping.png` | 出荷所 |
| fish_market | `assets/scenes/fish_market.png` | 魚市場 |
| general_store | `assets/scenes/general_store.png` | 道具・雑貨屋 |
| mizuho | `assets/scenes/mizuho.png` | みずほ町 |
| props | `assets/scenery/props.png` | 小物16種 |
| fish | `assets/scenery/fish.png` | 魚8種 |

作業時の配置先: `/workspace/scratch/6a909b1813a4/work_v940/assets/`。同じ相対パスでAssets用ZIP・統合更新ZIP・全ソースZIPに同梱しています。

参照画像の役割: 最初の4施設は添付スクリーンショットの配置・配色と既存の自宅外観を参照。次の施設・小物・隣町は生成した自宅の配色と画風を参照しました。魚は新規生成です。参照画像に含まれるUIや人物は背景へ描かない指示を入れています。

## home — 自宅

- 実行方法: 組み込みImagegen
- transparent_background: false
- 出力先: `assets/scenes/home.png`

使用したプロンプト:

```text
Use case: stylized-concept. Asset type: finished walkable 2D game interior background PNG for the existing Japanese pixel farm game AmberaFarm. Draw ONE single entire room map, overhead JRPG three-quarter top-down orthographic view, aligned upright, no perspective vanishing point and NO isometric diamonds. Landscape 1280x768 composition, equivalent to a 320x192 low resolution pixel canvas enlarged 4x using nearest neighbor. True visibly blocky pixel art with crisp square pixels, restrained warm cream/tan/brown/leaf green palette and dark brown pixel outlines like the attached game screenshots. No soft painterly rendering, no gradients, no photorealism. The screenshots are layout and palette references ONLY, remove all UI, text, labels, buttons, player characters. Fill the full frame with the room; solid dark brown border outside. Back wall y=0..155; walkable floor x=96..1184,y=160..704. An obvious open exit doorway at bottom center x=640,y=690 connects to floor. No ceiling. Important: bottom and middle floors must remain mostly open, flat and walkable. All decorative furniture except those specified stays against top and side walls. NO people. NO lettering anywhere. No watermark.
Room-specific composition: Cozy farmhouse bedroom with warm wood plank flooring. At coordinates x=290..430,y=180..300 place a complete wooden bed with cream pillow and muted rose blanket facing down into room. At x=760..860,y=240..300 a wooden storage chest. At x=510..600,y=190..260 small furniture/craft table. At x=865..955,y=370..440 wooden writing desk with a closed journal. Green curtains, small potted plants, bookshelf along back wall. Empty open floor y=340..670 except the writing desk at right.
```

## greenhouse — 温室

- 実行方法: 組み込みImagegen
- transparent_background: false
- 出力先: `assets/scenes/greenhouse.png`

使用したプロンプト:

```text
Use case: stylized-concept. Asset type: finished walkable 2D game interior background PNG for the existing Japanese pixel farm game AmberaFarm. Draw ONE single entire room map, overhead JRPG three-quarter top-down orthographic view, aligned upright, no perspective vanishing point and NO isometric diamonds. Landscape 1280x768 composition, equivalent to a 320x192 low resolution pixel canvas enlarged 4x using nearest neighbor. True visibly blocky pixel art with crisp square pixels, restrained warm cream/tan/brown/leaf green palette and dark brown pixel outlines like the attached game screenshots. No soft painterly rendering, no gradients, no photorealism. The screenshots are layout and palette references ONLY, remove all UI, text, labels, buttons, player characters. Fill the full frame with the room; solid dark brown border outside. Back wall y=0..155; walkable floor x=96..1184,y=160..704. An obvious open exit doorway at bottom center x=640,y=690 connects to floor. No ceiling. Important: bottom and middle floors must remain mostly open, flat and walkable. All decorative furniture except those specified stays against top and side walls. NO people. NO lettering anywhere. No watermark.
Room-specific composition: Beautiful glass greenhouse interior with pale turquoise glass window walls, visible grid of glass panels, wooden beams. Earth-and-stone floor with moss in grout. Planting benches and wooden raised beds full of readable pixel vegetables and leaves along back and side walls; the central walkway and bottom half unobstructed. A request noticeboard and small gardening workbench at x=450..550,y=210..280. Keep center x=320..960,y=320..680 clear. Watering cans, seed boxes, climbing vines, sunlit gentle farm atmosphere. NO text.
```

## shop — たね屋（みずほ町店内も使用）

- 実行方法: 組み込みImagegen
- transparent_background: false
- 出力先: `assets/scenes/shop.png`

使用したプロンプト:

```text
Use case: stylized-concept. Asset type: finished walkable 2D game interior background PNG for the existing Japanese pixel farm game AmberaFarm. Draw ONE single entire room map, overhead JRPG three-quarter top-down orthographic view, aligned upright, no perspective vanishing point and NO isometric diamonds. Landscape 1280x768 composition, equivalent to a 320x192 low resolution pixel canvas enlarged 4x using nearest neighbor. True visibly blocky pixel art with crisp square pixels, restrained warm cream/tan/brown/leaf green palette and dark brown pixel outlines like the attached game screenshots. No soft painterly rendering, no gradients, no photorealism. The screenshots are layout and palette references ONLY, remove all UI, text, labels, buttons, player characters. Fill the full frame with the room; solid dark brown border outside. Back wall y=0..155; walkable floor x=96..1184,y=160..704. An obvious open exit doorway at bottom center x=640,y=690 connects to floor. No ceiling. Important: bottom and middle floors must remain mostly open, flat and walkable. All decorative furniture except those specified stays against top and side walls. NO people. NO lettering anywhere. No watermark.
Room-specific composition: Village seed shop interior, honey wooden flooring, seed packets and glass jars of seeds displayed on shelves across back wall, bundles of herbs, sacks, potted sprouts. Wood counter x=330..530,y=210..280 with seed packets and cashbox; approachable from below at x=430,y=320. Leave middle and bottom floor open; baskets and sacks only along outside walls. Inviting small rural seed store. Bottom-center open exit doorway.
```

## cafe — カフェ

- 実行方法: 組み込みImagegen
- transparent_background: false
- 出力先: `assets/scenes/cafe.png`

使用したプロンプト:

```text
Use case: stylized-concept. Asset type: finished walkable 2D game interior background PNG for the existing Japanese pixel farm game AmberaFarm. Draw ONE single entire room map, overhead JRPG three-quarter top-down orthographic view, aligned upright, no perspective vanishing point and NO isometric diamonds. Landscape 1280x768 composition, equivalent to a 320x192 low resolution pixel canvas enlarged 4x using nearest neighbor. True visibly blocky pixel art with crisp square pixels, restrained warm cream/tan/brown/leaf green palette and dark brown pixel outlines like the attached game screenshots. No soft painterly rendering, no gradients, no photorealism. The screenshots are layout and palette references ONLY, remove all UI, text, labels, buttons, player characters. Fill the full frame with the room; solid dark brown border outside. Back wall y=0..155; walkable floor x=96..1184,y=160..704. An obvious open exit doorway at bottom center x=640,y=690 connects to floor. No ceiling. Important: bottom and middle floors must remain mostly open, flat and walkable. All decorative furniture except those specified stays against top and side walls. NO people. NO lettering anywhere. No watermark.
Room-specific composition: Cozy rural cafe interior with warm wood flooring, cream plaster and green curtains. Service counter x=320..510,y=215..285 has coffee machine, teapot, cups and bread, approachable from below x=418,y=330. A second small reception table x=760..860,y=215..285 with message notebook, approachable from below x=815,y=330. Display cake cabinet back wall. Two round dining tables only far left x=140,y=400 and far right x=1100,y=400, leave main floor x=300..960,y=330..680 clear. Bottom-center exit doorway.
```

## hall — 集会所

- 実行方法: 組み込みImagegen
- transparent_background: false
- 出力先: `assets/scenes/hall.png`

使用したプロンプト:

```text
Use case: stylized-concept. Asset type: finished walkable 2D game interior background PNG for the existing Japanese pixel farm game AmberaFarm. Draw ONE single entire room map, overhead JRPG three-quarter top-down orthographic view, aligned upright, no perspective vanishing point and NO isometric diamonds. Landscape 1280x768 composition, equivalent to a 320x192 low resolution pixel canvas enlarged 4x using nearest neighbor. True visibly blocky pixel art with crisp square pixels, restrained warm cream/tan/brown/leaf green palette and dark brown pixel outlines like the attached game screenshots. No soft painterly rendering, no gradients, no photorealism. The screenshots are layout and palette references ONLY, remove all UI, text, labels, buttons, player characters. Fill the full frame with the room; solid dark brown border outside. Back wall y=0..155; walkable floor x=96..1184,y=160..704. An obvious open exit doorway at bottom center x=640,y=690 connects to floor. No ceiling. Important: bottom and middle floors must remain mostly open, flat and walkable. All decorative furniture except those specified stays against top and side walls. NO people. NO lettering anywhere. No watermark.
Room-specific composition: Village community hall for minigames. Wood floors, green and cream walls. At x=380..525,y=190..285 an attractive vintage game console/pedestal with small cabbages and soccer ball emblem, no text. At x=760..900,y=190..285 a second arcade/tournament table with playing cards and game tokens, no text. Trophy shelf back wall, banners with NO symbols/text, notice board, benches at extreme sides. Central space x=300..980,y=330..680 clear and walkable. Bottom-center exit doorway.
```

## workshop — 衣装工房

- 実行方法: 組み込みImagegen
- transparent_background: false
- 出力先: `assets/scenes/workshop.png`

使用したプロンプト:

```text
Use case: stylized-concept. Asset type: finished walkable 2D game interior background PNG for the existing Japanese pixel farm game AmberaFarm. Draw ONE single entire room map, overhead JRPG three-quarter top-down orthographic view, aligned upright, no perspective vanishing point and NO isometric diamonds. Landscape 1280x768 composition, equivalent to a 320x192 low resolution pixel canvas enlarged 4x using nearest neighbor. True visibly blocky pixel art with crisp square pixels, restrained warm cream/tan/brown/leaf green palette and dark brown pixel outlines like the attached game screenshots. No soft painterly rendering, no gradients, no photorealism. The screenshots are layout and palette references ONLY, remove all UI, text, labels, buttons, player characters. Fill the full frame with the room; solid dark brown border outside. Back wall y=0..155; walkable floor x=96..1184,y=160..704. An obvious open exit doorway at bottom center x=640,y=690 connects to floor. No ceiling. Important: bottom and middle floors must remain mostly open, flat and walkable. All decorative furniture except those specified stays against top and side walls. NO people. NO lettering anywhere. No watermark.
Room-specific composition: Tailor and clothing workshop. Wood floors, cream walls, spool and fabric shelves, dresses and shirts on hanging rails along back and side walls. Main sewing workbench at x=410..590,y=210..290 with antique sewing machine, thread and scissors. Clothing mannequins in corners only. Warm nostalgic pixel farm feeling. Leave x=300..980,y=330..680 empty walkable floor. Bottom-center exit doorway.
```

## shipping — 出荷所

- 実行方法: 組み込みImagegen
- transparent_background: false
- 出力先: `assets/scenes/shipping.png`

使用したプロンプト:

```text
Use case: stylized-concept. Asset type: finished walkable 2D game interior background PNG for the existing Japanese pixel farm game AmberaFarm. Draw ONE single entire room map, overhead JRPG three-quarter top-down orthographic view, aligned upright, no perspective vanishing point and NO isometric diamonds. Landscape 1280x768 composition, equivalent to a 320x192 low resolution pixel canvas enlarged 4x using nearest neighbor. True visibly blocky pixel art with crisp square pixels, restrained warm cream/tan/brown/leaf green palette and dark brown pixel outlines like the attached game screenshots. No soft painterly rendering, no gradients, no photorealism. The screenshots are layout and palette references ONLY, remove all UI, text, labels, buttons, player characters. Fill the full frame with the room; solid dark brown border outside. Back wall y=0..155; walkable floor x=96..1184,y=160..704. An obvious open exit doorway at bottom center x=640,y=690 connects to floor. No ceiling. Important: bottom and middle floors must remain mostly open, flat and walkable. All decorative furniture except those specified stays against top and side walls. NO people. NO lettering anywhere. No watermark.
Room-specific composition: Rural shipping depot and produce storehouse. Wooden plank floors, exposed timber beams, crates of vegetables, sacks and shelves along back and side walls. Main wooden shipping desk counter x=380..580,y=210..290 with scale, ledger, sealed parcels and wicker produce basket. NO text or writing on any box or page. Keep main central floor x=300..980,y=330..680 empty. Bottom-center exit doorway.
```

## fish_market — 魚市場

- 実行方法: 組み込みImagegen
- transparent_background: false
- 出力先: `assets/scenes/fish_market.png`

使用したプロンプト:

```text
Use case: stylized-concept. Asset type: finished walkable 2D game interior background PNG for the existing Japanese pixel farm game AmberaFarm. Draw ONE single entire room map, overhead JRPG three-quarter top-down orthographic view, aligned upright, no perspective vanishing point and NO isometric diamonds. Landscape 1280x768 composition, equivalent to a 320x192 low resolution pixel canvas enlarged 4x using nearest neighbor. True visibly blocky pixel art with crisp square pixels, restrained warm cream/tan/brown/leaf green palette and dark brown pixel outlines like the attached game screenshots. No soft painterly rendering, no gradients, no photorealism. The screenshots are layout and palette references ONLY, remove all UI, text, labels, buttons, player characters. Fill the full frame with the room; solid dark brown border outside. Back wall y=0..155; walkable floor x=96..1184,y=160..704. An obvious open exit doorway at bottom center x=640,y=690 connects to floor. No ceiling. Important: bottom and middle floors must remain mostly open, flat and walkable. All decorative furniture except those specified stays against top and side walls. NO people. NO lettering anywhere. No watermark.
Room-specific composition: Pretty rural lakeside fish market. Blue and cream ceramic tile floor, wooden walls and frosted windows, nets and buoys hanging back wall. Fresh fish on crushed ice in low counter x=370..570,y=210..280, approachable from below near x=470,y=320. Side-wall wooden crates, buckets and glass fish tanks, all fish readable small pixel details. Leave central walkable tile aisle x=300..980,y=330..680 clear. No letters or labels. Bottom-center exit doorway.
```

## general_store — 道具・雑貨屋

- 実行方法: 組み込みImagegen
- transparent_background: false
- 出力先: `assets/scenes/general_store.png`

使用したプロンプト:

```text
Use case: stylized-concept. Asset type: finished walkable 2D game interior background PNG for the existing Japanese pixel farm game AmberaFarm. Draw ONE single entire room map, overhead JRPG three-quarter top-down orthographic view, aligned upright, no perspective vanishing point and NO isometric diamonds. Landscape 1280x768 composition, equivalent to a 320x192 low resolution pixel canvas enlarged 4x using nearest neighbor. True visibly blocky pixel art with crisp square pixels, restrained warm cream/tan/brown/leaf green palette and dark brown pixel outlines like the attached game screenshots. No soft painterly rendering, no gradients, no photorealism. The screenshots are layout and palette references ONLY, remove all UI, text, labels, buttons, player characters. Fill the full frame with the room; solid dark brown border outside. Back wall y=0..155; walkable floor x=96..1184,y=160..704. An obvious open exit doorway at bottom center x=640,y=690 connects to floor. No ceiling. Important: bottom and middle floors must remain mostly open, flat and walkable. All decorative furniture except those specified stays against top and side walls. NO people. NO lettering anywhere. No watermark.
Room-specific composition: Rural farm tools and sundries store. Warm wood floors, cream plaster, sturdy wood shelves with gardening tools, ropes, watering cans, oil lanterns, bowls and picnic supplies around back and side walls. Wooden sales counter at x=390..590,y=210..290 with riceballs, tea bottle, little bento and cashbox. Shovels and hoes on wall. Keep middle and bottom floor x=300..980,y=330..680 empty and walkable. No labels. Bottom-center exit doorway.
```

## mizuho — みずほ町

- 実行方法: 組み込みImagegen
- transparent_background: false
- 出力先: `assets/scenes/mizuho.png`

使用したプロンプト:

```text
Use case: stylized-concept. Asset type: ONE complete playable neighboring town background PNG for AmberaFarm. Strict crisp blocky low resolution Japanese pixel farm RPG art, top-down three-quarter orthographic, no perspective vanishing point, no isometric. Match warm brown/cream, leafy green and muted turquoise reference interiors. Landscape 1600x1024 game-map composition, camera sees entire map, not a postcard or UI. No players, no text, labels, lettering, watermark. IMPORTANT collision/layout coordinates: main seed store occupies x=330..950,y=80..282, a charming cream timber shop with muted red roof and visible central doorway at x=637,y=304; a small closed decorative house x=1070..1370,y=100..310. A small decorative house/garden x=115..335,y=540..740. A fenced garden pond and trees x=1010..1410,y=590..820. Keep ALL center open walkable: wide dirt street from seed store doorway (637,304) south to (637,940) and horizontal street y=500 across town, cream cobblestone plaza around center(637,520), low flowers only at edge. Bottom center(637,930) is clearly open carriage return gate with two wood posts and an empty doorway; no solid building or vehicle blocks that opening. Trees, shrubs and wooden fences around outer perimeter. Shop doors and garden edges clearly visible, no buildings on central paths. Ground fills entire frame, no margins. Entire world should be 16-bit game tile art with flat square-pixel textures and simple consistent shadows, not painted concept art.
```

## props — 小物16種

- 実行方法: 組み込みImagegen
- transparent_background: true
- 出力先: `assets/scenery/props.png`

使用したプロンプト:

```text
Use case: stylized-concept. Asset type: transparent PNG game prop sprite atlas, ONE 4-column 4-row equal cell grid, all 16 cells filled, 1024x1024 square. Each cell256x256 contains ONE complete object centered, 24px clear padding, no object touches adjacent cell, fully transparent actual alpha background (not white, no checkerboard), NO text, NO labels, no grid lines. Consistent crisp very blocky pixel JRPG farm game art: 48x48 logical pixels per object, dark brown pixel outlines, muted warm brown cream green palette like reference. View all props from matching overhead three-quarter game camera, no photorealism/blur. ROW1 LEFT TO RIGHT: leafy mature green farm tree with trunk; round stone fountain with turquoise water; wooden village quest board with papers; small rustic horse-drawn carriage wagon with horse. ROW2: leafy potted plant; flat woven green-and-cream rectangular rug; rustic wooden small table; glowing star-shaped floor lamp. ROW3: wooden park bench; red rural mailbox on post; wooden shipping crate with vegetables; wooden signpost. ROW4: cozy single wooden bed with rose blanket; closed wooden storage chest; a wall-rack of shovel hoe watering-can tools; wooden fish crate with ice and fish. No characters, no extra decorative background, no cast shadow outside sprite. Readable silhouettes in tiny game sizes.
```

## fish — 魚8種

- 実行方法: 組み込みImagegen
- transparent_background: true
- 出力先: `assets/scenery/fish.png`

使用したプロンプト:

```text
Use case: stylized-concept. Asset type: transparent PNG inventory fish icon sprite atlas for AmberaFarm. ONE 4-column 2-row equal cell grid landscape2048x1024, every cell512x512. One complete fish centered per cell, 60px padding each cell, all face right in side view. Crisp true pixel game art with clearly square chunky pixels, 48x48 logical pixel style, dark brown outlines, cream highlights, natural muted colors. Background actual alpha transparent, no checkerboard, no labels/grid/text, no floor or shadows, no framing. Top row left to right exactly: small tan-gold medaka ricefish; silver-green crucian carp; slender silver-blue ayu sweetfish; orange-and-cream koi carp. Bottom row left to right exactly: long brown Japanese eel curving; rosy speckled trout; large coral-orange king salmon; luminous gold koi with tiny gold sparkle. Complete identifiable fins, tails and eyes, no cropped tails, no duplicate fish. Match farm game's rustic pixel sprites.
```
