# 六參數 Avatar 模式（保留功能）

**狀態（2026-11-05）：此文件記錄已實作的自製 Avatar 路線；產品主線與最新進度見 [OSC Tracker MVP 計畫](OSC_TRACKER_MVP_PLAN.md)。**

Windows receiver 可把手機姿勢轉成六個 `Puppet/*` Float 參數，經 VRChat OSC Avatar Parameters 控制本機 Robot 測試 Avatar。這需要可編輯的 Avatar Animator，**不能直接驅動未修改的購買 Avatar**。此模式保留作為自製 Avatar 的選項。

## 已證實

- Android App 可從相機取得 33 個 pose landmarks，並以私人 LAN UDP 傳送；手機到 Windows 的短時間 Wi-Fi／ACK 測試已完成。
- Windows receiver 可驗證封包、校正六個局部角度、濾波並輸出 OSC。合成 loopback 曾連續運行 10 分鐘；最新 Windows 自動測試 26 項通過。
- VRChat Desktop 已透過獨立 OSC 診斷工具接收六個參數；使用者確認本機 Robot 的抬手、彎肘、彎膝與 WASD 共存。
- Unity 骨骼測試與 SDK 本機 Build & Test 曾通過；目前重新執行 Unity smoke test 遇到 License Client IPC timeout，不能列為本次通過。

## 尚未證實

手機 → Windows receiver → VRChat 的完整六參數流程、六參數 Avatar 的遠端同步、手機實機 10 分鐘穩定性及視覺端到端延遲。這些歷史測試不能替代 [原生 OSC Tracker Phase 0 的遠端驗收](VIRTUAL_HMD_PHASE0_PLAN.md)，也不能證明手機 FBT 已完成。

## 操作與紀錄

- [Windows receiver、OSC 參數及量測](windows/README.md)
- [Android 建置與 LAN 操作](android/README.md)
- [Robot Avatar 設定](VRChatTrackAvatar/AVATAR_SETUP.md)
- [Windows](windows/TEST_RESULTS.md)、[Android](android/TEST_RESULTS.md) 與 [Robot Avatar](VRChatTrackAvatar/TEST_RESULTS.md) 歷史測試紀錄

目前預設不發送 OSC；receiver 的 `--osc` 只啟用六參數模式。未完成手機 tracker 座標校正前，不將其當作 `--output trackers` 使用。

