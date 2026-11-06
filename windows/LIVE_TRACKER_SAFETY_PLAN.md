# 即時 Tracker 失追操作

目前狀態與驗證範圍見 [docs/STATUS.md](../docs/STATUS.md)；後續計畫見 [docs/PLAN.md](../docs/PLAN.md)。

先依 [Windows 接收端指南](README.md) 啟動 `--output trackers`，並確認當次髖與雙腳 ID、相機方向、鏡像及髖高。校正前不輸出姿勢。

- 最後有效姿勢超過 `--tracker-loss-ms`（預設 350 ms）判為失追，仍保留手機校正。
- `--tracker-hold-ms` 預設 8000 ms，從最後有效姿勢計時；正值介於失追門檻與 8000 ms，設為 0 不重送。無效影格及重送舊姿勢不重設時間。
- 有效姿勢在期限內恢復、並通過完整性、信心及突變檢查時，以 300 ms 從最後送出姿勢過渡到持續更新的新姿勢。yaw 走最短角度。
- 超出凍結上限後停止輸出；在 Windows 互動終端按 `R`，或重新啟動 receiver，重新站姿校正。相機位置、人物或鏡頭改變時也應重新校正。
- 超過每角色 0.5 m 或 yaw 90°、新 session、輸出錯誤均會中止舊校正。可用 `--tracker-max-jump-m` 和 `--tracker-max-yaw-jump-deg` 調整門檻。

停止發送不保證 VRChat 立即清除最後姿勢。真人配合前先語音通知並等待就位；測試結果記錄在 [docs/logs/](../docs/logs/)。
