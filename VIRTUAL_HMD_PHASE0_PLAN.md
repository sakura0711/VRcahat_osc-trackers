# Phase 0 延伸：Windows 10 無實體頭顯的 VR 模式可行性

**狀態（2026-11-04）：環境與候選工具已調查；SteamVR、虛擬驅動、VRChat 校正與遠端同步均尚未實測。**

## 已有證據與邊界

- 本專案 `windows/tracker_probe.py` 的 Hip + Feet OSC 封包已在 VRChat 的 OSC Debug 畫面出現；Desktop Avatar 沒有跟著抬腳。這只證明接收，不證明 FBT 啟用。
- 使用者沒有實體 HMD。VRChat 官方 FBT 流程要求在 VR 模式按 Calibrate FBT，並以頭顯及控制器完成校正。[官方 FBT 文件](https://docs.vrchat.com/docs/full-body-tracking)。
- 這台電腦是 Windows 10 Home；已檢查 Steam 的 C:、D:、E: library，沒有發現 SteamVR（app 250820）的 manifest 或安裝目錄。SteamVR 本身列 Windows 10 為支援系統。[SteamVR](https://store.steampowered.com/app/250820/SteamVR/)。
- [AnyaDance](https://github.com/anyapipira/AnyaDance) 的文件列 Windows 10、SteamVR，提供虛擬 HMD、雙控制器、髖與雙腳，並有可還原的驅動註冊流程；目前發行版為 v0.0.6。它的完整六點驅動可先驗證「無頭顯 VR + FBT」。其自帶的三個 SteamVR tracker 可能和本專案 OSC tracker 競爭，不應把兩路一起送出的結果當成 OSC 單獨通過。
- 另有 [Virtual VR Emulator](https://github.com/sasaken1102r/Virtual-VR-Emulator/blob/main/README.en.md) 僅提供虛擬 HMD + 雙控制器，較適合隔離測試 OSC tracker；但作者的建置需求列 Windows 11，Windows 10 相容性尚未確認。
- 不修改或注入 VRChat client。虛擬裝置由 SteamVR 驅動提供；Avatar 保持未修改。

## 依序執行的閘門

1. **SteamVR 基礎（預估 15–30 分鐘，取決於下載速度）：** 安裝官方 SteamVR；確認它能啟動並記錄版本與偵測狀態。未安裝時選擇 VRChat「Steam VR 模式」不足以證明已在 VR 模式。
2. **虛擬裝置（預估 20–40 分鐘）：** 核對 AnyaDance 發行包、授權與還原說明，記錄原始 SteamVR 設定，註冊驅動。SteamVR 必須顯示虛擬 HMD、左右控制器及三個 tracker；結束後能解除註冊並還原。此步只驗證 SteamVR，不開 VRChat。
3. **VRChat 校正（預估 20–40 分鐘）：** 用虛擬裝置啟動 VRChat VR 模式，確認快速選單出現 Calibrate FBT。先使用 AnyaDance 自帶的六點資料完成校正；記錄按鈕是否可用、球是否出現及 Avatar 是否被 IK 帶動。若無法完成，停止該候選方案，不把「有按鈕」當成通過。
4. **遠端驗收（預估 15–30 分鐘，需另一位玩家）：** 私人房間用未修改的 Humanoid Avatar，切換靜止／抬腳，讓另一位玩家辨認。記錄本機與遠端結果、影片及是否有長時間卡住。未取得遠端確認時標示「未完成」。
5. **本專案 OSC 隔離測試（預估 20–40 分鐘）：** 確認可停用 AnyaDance 的三個 SteamVR tracker，或改用僅提供虛擬 HMD／控制器且支援 Windows 10 的驅動，才執行 `tracker_probe.py`。以 OSC Debug、FBT 校正、本機姿勢及遠端觀察逐項驗收。若無法隔離，AnyaDance 的成功只能證明虛擬 SteamVR 路線，不能證明 OSC Tracker 路線；另評估由 Windows receiver 輸出至已文件化的 AnyaDance loopback UDP 作替代 backend。

## 記錄欄位與後續決策

每一閘門記錄日期、SteamVR／VRChat／驅動版本、執行模式、虛擬裝置狀態、校正結果、本機動作、遠端玩家觀察與失敗訊息。所有結論分開標示「虛擬 SteamVR FBT」和「OSC Tracker FBT」。

Phase 0 只有在 **未修改 Avatar 可校正，且遠端玩家可見持續的下半身姿勢變化**時通過。通過後才決定 Windows `TrackerOutput` 使用 OSC 或 SteamVR 驅動 backend；在此之前保留現有 `parameters` 模式。

AnyaDance 作者在 [README](https://github.com/anyapipira/AnyaDance#disclaimer) 提醒：在連線遊戲使用虛擬裝置有帳號風險；其驅動註冊也會更動 SteamVR 設定。實際測試前須核對這項風險與還原步驟，不將工具作者的聲明當成 VRChat 官方政策結論。
