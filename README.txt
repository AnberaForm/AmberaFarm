アンベラ牧場 v9.6.0 — 部屋検索・申請欄・部屋専用データ・Setup配布

【この版の変更】
部屋名・部屋主名で部屋を検索し、参加申請を送れます。
部屋主の「申請欄」で参加を承認・見送りできます。フレンド申請も全件表示。
通常・旧オンラインの所持金やアイテムを持ち込まず、部屋専用データを使用。
進行は部屋主の専用牧場へ保存。同じ牧場へ戻るとそこでの続きから再開。
日本語Setup、ショートカット、自動更新、セーブを残すアンインストールに対応。
導入は V9_6_ONLINE_GUIDE.md を参照してください。

【引き継いだ機能】
7キャラの4方向歩行（各16コマ）、停止時の待機、衣装の反映と動くプレビュー。
カブボールの操作不能とCPU停止を修正。CPU難易度3段階、Escで試合退出。
釣りの急な方向転換、魚が暴れる動作、糸の負担、ウキの慣性、28秒制限。
室内と隣町のプレイヤー同期、室内からの店・収納操作、メニューからの戻り方を改善。
オンラインの釣果はホストが判定し、一度の成功につき一匹だけ付与します。

既存セーブの初期化は不要です。以前の作物画像11枚はそのままです。
v9.2で追加したセーブ4枠、文字カーソル・範囲選択、食べ物画像、建物の室内を維持。
既存の画像、セーブ4枠、各施設・隣町の独立マップ、自動更新を維持。

【起動】
配布用Windows版: AmberaFarm_Setup_v9.6.0.exe を実行し、ショートカットから起動。
Pythonや設定ファイルの別添は不要です。従来の展開式ZIPも残しています。
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
ゲーム通信プロトコル14、中継プロトコル1。部屋全員を v9.6.0 にそろえてください。
「部屋を探して参加」で検索・参加申請。参加申請が承認されると部屋に入ります。
部屋主は「協力部屋を作る」で牧場1/2を選択。「検索に表示する」は公開・承認制です。
非公開の部屋は従来どおり招待コードで参加。公開部屋はコードがあっても承認が必要です。
通常データからオンラインへのコピーは廃止。既存の4枠のファイルは保管します。
「インターネット / 部屋コード」「同じLAN / IP指定」を選べます。
部屋主を含め8人まで。部屋主が起動している間に参加できます。
公開済みの中継サーバーへ接続します。接続先はonline_config.jsonに同梱しています。
室内と隣町では同じ場所にいる参加者だけを表示します。
詳細は V9_6_ONLINE_GUIDE.md と SECURITY_AND_SAVES.md を参照してください。

【セーブ】
%APPDATA%\AmberaFarm\save_slots\offline_1.json / offline_2.json
%APPDATA%\AmberaFarm\save_slots\online_1.json / online_2.json
通常の終了・保存操作で配置や所持品を保持します。
旧 save.json は初回に通常1へコピーされ、元のファイルは残ります。
専用牧場: %APPDATA%\AmberaFarm\room_worlds\farm_1.json / farm_2.json
バックアップ・PC移行では %APPDATA%\AmberaFarm フォルダ全体を保管してください。

【検証】
python -m pytest -q tests
python -m unittest -q verify_online_rooms verify_room_lobby
python ambera_farm.py --smoke-test
python verify_release_tag.py --tag v9.6.0
Windows CIでは build_windows_setup.py と verify_windows_setup.py も実行します。
公開サーバーの実通信は verify_public_relay.py を必要なときに手動実行します。
別々のPC・回線での実操作は確認が必要です。

履歴: V9_2_RELEASE_NOTES.md / V9_1_LIFE_UI_RELEASE_NOTES.md / V9_0_RELEASE_NOTES.md
