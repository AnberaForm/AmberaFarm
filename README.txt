アンベラ牧場 v9.3.0 — 歩行・ミニゲーム・室内オンライン改善

【この版の変更】
7キャラの4方向歩行（各16コマ）、停止時の待機、衣装の反映と動くプレビュー。
カブボールの操作不能とCPU停止を修正。CPU難易度3段階、Escで試合退出。
釣りの急な方向転換、魚が暴れる動作、糸の負担、ウキの慣性、28秒制限。
室内と隣町のプレイヤー同期、室内からの店・収納操作、メニューからの戻り方を改善。
オンラインの釣果はホストが判定し、一度の成功につき一匹だけ付与します。

既存セーブの初期化は不要です。以前の作物画像11枚はそのままです。
v9.2で追加したセーブ4枠、文字カーソル・範囲選択、食べ物画像、建物の室内を維持。
今回の詳細と残る制限は V9_3_RELEASE_NOTES.md を参照してください。

【起動】
配布用Windows版: AmberaFarm.exe から起動（Python不要）。
この全ソースZIP: Windowsで START_GAME.cmd、または依存を入れて python ambera_farm.py。
Windows EXEは既存のGitHub Actions「Build Ambera Farm Windows EXE」で生成します。
このソースZIP自体にWindows EXEは含まれません。

【操作】
WASD / 矢印: 歩く    E / Space: 調べる・畑の作業
I / Tab: 持ち物    1～9: ホットバー    M: ミッション
T: チャット（室内・隣町も可）    C: 衣装    F9: 緊急脱出    F11: 全画面
建物: カウンターに近づきE。メニューでEsc→室内、室内でEsc→屋外。
隣町: お店の近くでE。買い物でEsc→町、町でEsc→帰る。
カブボール: WASD移動、Shiftダッシュ、マウス照準、Jをためて離すとシュート、
             Kで奪取、Qでフェイント、Lでクイックキック、Escで試合から退出。
釣り: W/Sまたは上下でウキを操作し、SPACEで巻く。
      魚が暴れている間や糸の負担が高いときはSPACEを離す。

【オンライン】
通信プロトコル12。全員を v9.3.0 にそろえてください。
タイトル「セーブ枠」でオンライン枠を選び、部屋作成／参加。
通常2枠＋オンライン2枠。通常データは空きオンライン枠へコピーできます。
同じLAN／直接IP接続方式です。全体マッチングやクラウドアカウントではありません。
室内と隣町では同じ場所にいる参加者だけを表示します。
詳細は ONLINE_GUIDE.md と SECURITY_AND_SAVES.md を参照してください。

【セーブ】
%APPDATA%\AmberaFarm\save_slots\offline_1.json / offline_2.json
%APPDATA%\AmberaFarm\save_slots\online_1.json / online_2.json
通常の終了・保存操作で配置や所持品を保持します。
旧 save.json は初回に通常1へコピーされ、元のファイルは残ります。
オンライン枠のバックアップは save_slots フォルダ全体をコピーしてください。

【検証】
python -m pytest -q tests
python ambera_farm.py --smoke-test
python verify_release_tag.py --tag v9.3.0
実行結果は VALIDATION_V9_3_0.txt を参照。
WindowsのEXE起動・実機操作・別PC間の通信は、この作成環境では未検証です。

履歴: V9_2_RELEASE_NOTES.md / V9_1_LIFE_UI_RELEASE_NOTES.md / V9_0_RELEASE_NOTES.md
