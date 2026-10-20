アンベラ牧場 v0.7.0 / Pygame Windows版ソース

【起動】
Windows: START_GAME.cmd をダブルクリック（Python + pygame-ce が必要）。
配布用EXE: GitHub ReleasesのAmberaFarm_Windows_v0.7.0.zipからAmberaFarm.exeを起動。
※ 上記の「AmberaFarm」は見た目が紛らわしいため、配布名の正確な英字表記は下記です:
AmberaFarm_Windows_v0.7.0.zip / AmberaFarm.exe

【変更】
・タイトル画面とポーズ画面に「お知らせ」ボタンが追加されました。
・公式GitHubの更新情報を取得し、通信できない場合は前回情報を表示。
・管理画面（従来の「ストーリー管理」）に、お知らせ管理・ゲーム配布タブが追加されました。
・公開操作には管理者PCでGitHub CLI認証が必要です。
・元の11点の作物PNGは変更していません。今までの育成/釣り/セーブ/マルチの仕様は維持します。

【詳しい手順】 ANNOUNCEMENTS_GUIDE.md を参照してください。

【セーブ】 %APPDATA%\AmberaFarm\save.json
【注意】 Windows用EXEはこのソースZIPには同梱されていません。GitHub Actionsで生成してください。
