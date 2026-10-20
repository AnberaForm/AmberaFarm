アンベラ牧場 v0.6.0 〜 移動・個人別オンライン・チャット・管理画面ログイン改善

※ このZIPは「ソースコードとWindows EXEビルド設定」です。EXEそのものは含まれていません。

【いま遊ぶ】
  1. このZIPをすべて展開します。
  2. Windowsで START_GAME.cmd をダブルクリックします。
  3. 初回はPythonとpygame-ceの導入が必要です。
  4. ゲーム内で W/A/S/D または方向キーで移動します。

【改善】
  ・スタック原因になっていた初期位置を、柵の外の安全な位置に変更。
  ・旧セーブの障害物内座標は自動補正。F9で自宅近くへ緊急脱出できます。
  ・移動時は細かい分割で当たり判定を行い、壁に沿って移動します。
  ・オンライン: 24の畑区画のみ共有。所持金・種・作物・魚・統計・ミッション・ストーリーは個人別。
  ・ゲストの所持品はゲスト自身のPCへ保存。ホストのセーブと混ざりません。
  ・Tでオンラインチャット。Enterで送信。Escで閉じる。
  ・管理画面の開始時にコードとパスワードを入力（簡易ローカル認証）。

【EXEはどこ？】
  Windowsで BUILD_EXE_WINDOWS.cmd をダブルクリックし、完了後に
    build_output\exe\AmberaFarm.exe        ランチャー
    build_output\exe\AmberaGame.exe        ゲーム本体
    build_output\exe\AmberaStoryEditor.exe ストーリー管理
  が作られます。AmberaFarm.exe単体をコピーするだけでは配布できません。
  詳細は EXE_DISTRIBUTION_GUIDE.md を参照してください。
  GitHub Actionsでビルドすることも可能です。

【管理画面】
  タイトル画面の「ストーリー管理」または START_STORY_EDITOR.cmd
  コード: admin
  パスワード: pass123
  ※ 配布したEXEに埋め込まれた固定パスワードは解析可能です。
     これはローカル編集UIの簡易ロックであり、ネットワーク管理者認証ではありません。

【ゲームについて】
  現実20秒=ゲーム内1分。既存12種の育成時間を維持します。
  元の作物ドット絵11点をバイト単位で維持。kin_ringo.pngは元資料不足で未収録。
  オフラインのセーブ: %APPDATA%\AmberaFarm\save.json
  本バージョンはWindows実機でのGUI起動・EXE実行を未検証です。
