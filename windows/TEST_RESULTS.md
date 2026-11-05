# Windows 接收端驗證紀錄

最後更新：2026-11-05

## 自動測試

`python -B -m unittest discover -v`：2026-11-05 最新 **26 項通過**。包含接收與 ACK、六參數校正與逾時、OSC 編碼、手動 tracker 探針，以及 `TrackerOutput` 的 ID 3／4 對調、UDP 封包與無效批次不送出。這些是本機自動測試；VRChat 的 OSC FBT 遠端盲測另見 [Phase 0 證據](../VIRTUAL_HMD_PHASE0_PLAN.md)。

## 10 分鐘合成 loopback

以中斷後重新計時的最終版本執行 `python -B -u soak_loopback.py --duration 600 --fps 15`：PASS。合成資料僅使用 `127.0.0.1` 與系統指定的本機 UDP 埠；接收端完成三秒校正後輸出六項 OSC，再由本機測試程式解析。

| 指標 | 結果 |
| --- | ---: |
| 合成封包送出／收到 ACK | 9,000／9,000 |
| schema 錯誤／序號缺口／亂序 | 0／0／0 |
| ACK 逾時／錯誤 ACK | 0／0 |
| 本機 OSC 發送／解析錯誤 | 0／0 |
| 六項參數各自解析數 | 各 8,957 |

這不是 Android、Wi-Fi 或 VRChat 遊戲內測試；資料中的手機處理時間是固定的合成值，不能作為手機效能結果。先前直接發送 OSC 到 VRChat 的動作及 WASD 確認，另見 `../VRChatTrackAvatar/TEST_RESULTS.md`。
