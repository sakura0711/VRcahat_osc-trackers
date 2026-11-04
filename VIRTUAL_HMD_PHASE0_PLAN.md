# Phase 0 延伸：Windows 10 無實體頭顯的 VR 模式可行性

**狀態（2026-11-05）：AnyaDance 三個 SteamVR tracker 已完成 VRChat FBT 校正；使用者拖動髖與雙腳時，本機 Avatar 會跟著動。SteamVR -202 仍在；本專案 OSC tracker 隔離與私人房間遠端同步尚未驗收。**

## 已有證據與邊界

- 本專案 `windows/tracker_probe.py` 的 Hip + Feet OSC 封包已在 VRChat 的 OSC Debug 畫面出現；Desktop Avatar 沒有跟著抬腳。這只證明接收，不證明 FBT 啟用。
- 使用者沒有實體 HMD。VRChat 官方 FBT 流程要求在 VR 模式按 Calibrate FBT，並以頭顯及控制器完成校正。[官方 FBT 文件](https://docs.vrchat.com/docs/full-body-tracking)。
- 這台電腦是 Windows 10 Home；SteamVR 已安裝在 `C:\Program Files (x86)\Steam\steamapps\common\SteamVR`，版本 `2.18.4`。未安裝虛擬驅動前回報 `Hmd Not Found (108)`；安裝後虛擬裝置成功載入。SteamVR 本身列 Windows 10 為支援系統。[SteamVR](https://store.steampowered.com/app/250820/SteamVR/)。
- [AnyaDance](https://github.com/anyapipira/AnyaDance) v0.0.6 發行包已下載並解壓至 `E:\10_DevTool\AnyaDance-v0.0.6`，ZIP SHA-256 為 `11E81EBDF1CA059DF88DD2FFD698C3C2243FFECE8684FF9D47A0A3BEE5D68417`；可執行檔未經數位簽署。發行包缺少 README 提及的 `register_driver.ps1`，已從同一版本標籤下載該腳本並核對 Git blob SHA 後執行。SteamVR 日誌顯示虛擬 HMD、左右 Index 控制器、髖部與雙腳 tracker 均已載入。它的三個 SteamVR tracker 可能和本專案 OSC tracker 競爭，不應把兩路一起送出的結果當成 OSC 單獨通過。
- VRChat 以 SteamVR 模式啟動後，輸出日誌顯示 `StartVRSDK: OpenVRLoader`、連線至 `AnyaDance Virtual HMD`、左右控制器及三個 AnyaDance tracker。這證明 VR 執行環境與裝置辨識，不證明使用者已進入 FBT 校正或 Avatar 動作成功。日誌中的一般 avatar calibration 訊息不能取代畫面及遠端驗收。
- AnyaDance 以 60 Hz 對 `127.0.0.1:39570` 發送六裝置封包；驅動回報接受封包。使用者在 AnyaDance 按住／放開 `M` 時，驅動日誌的右控制器 `b_click` 依序為 `true`／`false`；重開機後已在 VRChat 看見快速選單。
- SteamVR 狀態與日誌持續顯示 `-202`（compositor not fullscreen）及 `SteamVRSystemState_NotReady`。點選「開啟全螢幕模式」、`Alt+Enter`、主螢幕 2048×1152 或 2560×1440，以及第二螢幕 1920×1080，均未解除。2026-11-05 再次把 AnyaDance 的 `headset_window_width/height` 設為主螢幕 2560×1440 並重啟，仍回報 `-202`。依使用者要求，保留 2560×1440 作為方便操作的視窗尺寸；這不代表 `-202` 已解除。
- `vrcompositor.txt` 明確記錄 `Forcing debug mode for anyadance driver because of Prop_DisplayDebugMode_Bool` 與 `Headset display is on desktop`。AnyaDance v0.0.6 [驅動原始碼](https://github.com/anyapipira/AnyaDance/blob/v0.0.6/src/driver/virtual_device.cpp) 將 `Prop_DisplayDebugMode_Bool`、`Prop_IsOnDesktop_Bool` 與 `IsDisplayOnDesktop()` 固定為 `true`；[Valve OpenVR 驅動文件](https://github.com/ValveSoftware/openvr/blob/master/docs/Driver_API_Documentation.md) 說明此模式使用桌面視窗，虛擬顯示則有獨立介面。這支持 `-202` 與驅動顯示模式有關的推論；單純改視窗解析度未能解決，尚未驗證改用真正虛擬顯示介面的效果。
- 2026-11-05 驅動實驗：將 v0.0.6 原始碼複製到 `E:\10_DevTool\AnyaDance-source-v0.0.6`，以 OpenVR SDK 2.2.3 建置獨立 DLL；唯一原始碼變更為 `Prop_DisplayDebugMode_Bool` 改成 `false`，保留桌面顯示與 2560×1440 設定。重新啟動後，compositor 不再記錄「Forcing debug mode」，仍記錄 `Headset display is on desktop`；`vrmonitor.txt` 仍報 `-202` 並轉為 `SteamVRSystemState_NotReady`。因此**單獨關閉 debug 旗標不是修復**，不能據此判定其餘顯示路徑的根因。畫面擷取逾時，未驗證該實驗版的 VRChat 畫面。原 DLL 已還原，SHA-256 為 `5D8DA376EE6B079CC66FB94AA8A67DD2767CA8823B2E5B22F95A7E854CF28AFB`；備份位於 `E:\10_DevTool\AnyaDance-v0.0.6\driver_anyadance.before-debug-experiment.dll`。
- 真正的虛擬顯示路徑仍待研究：[OpenVR 文件](https://github.com/ValveSoftware/openvr/blob/master/docs/Driver_API_Documentation.md#ivrvirtualdisplay)要求處理 compositor 影像與同步時序；不能只關閉警告或宣稱切換旗標已實作虛擬顯示。
- 2026-11-05 重開機後，SteamVR 仍回報 `-202`／`SteamVRSystemState_NotReady`；`Headset Window` 以 1920×1080 顯示在 2560×1440 主螢幕中央，`Alt+Enter` 沒有切成全螢幕。儘管如此，VRChat 再次以 OpenVR 載入全部虛擬裝置，並實際顯示於 `Headset Window`。使用者以 AnyaDance 的 `M` 開啟 VRChat 快速選單，亦能用虛擬右控制器操作 SteamVR 暫停面板返回遊戲。這證明 VR 畫面及輸入可用，尚未證明 FBT 已校正。
- 先前 VRChat 日誌雖出現 `Initialize SixPoint Avatar` 與 `Applying calibration to avatar... type: 8`，當時仍未以腳部動作或遠端觀察確認；後續本機動作已由使用者確認，遠端仍待驗證。
- 2026-11-05 使用者已在 VRChat 找到 `Calibrate FBT`，完成校正後拖動 AnyaDance 的髖及雙腳，確認本機 Avatar 下半身跟著動。當次 VRChat 日誌明列 `anyadance_hip_001`、`anyadance_left_foot_001`、`anyadance_right_foot_001` 參與校正，並分別映射為 13、11、12。這證實 **AnyaDance SteamVR tracker 的本機 FBT 動作**；未測本專案 OSC tracker，亦未取得遠端玩家觀察。`-202` 在可用的 VR 畫面與 FBT 動作下仍存在，不能把它視為本機 FBT 校正失敗的證據。
- 註冊前的 `steamvr.vrsettings` 與 `openvrpaths.vrpath` 已另存於 `E:\10_DevTool\steamvr-baseline-2026-11-04`，供還原核對。
- 另有 [Virtual VR Emulator](https://github.com/sasaken1102r/Virtual-VR-Emulator/blob/main/README.en.md) 僅提供虛擬 HMD + 雙控制器，較適合隔離測試 OSC tracker；但作者的建置需求列 Windows 11，Windows 10 相容性尚未確認。
- 不修改或注入 VRChat client。虛擬裝置由 SteamVR 驅動提供；Avatar 保持未修改。

## 依序執行的閘門

1. **SteamVR 基礎（已完成）：** 官方 SteamVR 已安裝並啟動；未有 HMD 時回報 `Hmd Not Found (108)`。先前只選擇 VRChat「Steam VR 模式」不足以證明已在 VR 模式。
2. **虛擬裝置（已完成）：** AnyaDance 驅動已註冊；SteamVR 顯示虛擬 HMD、左右控制器及三個 tracker。原始設定已有備份；頭顯視窗尺寸依使用者要求設為 2560×1440。解除註冊尚未執行，以便繼續 Phase 0。
3. **VRChat 校正與本機動作（已完成，僅 AnyaDance SteamVR trackers）：** 使用者完成 FBT 校正，拖動髖與雙腳時 Avatar 下半身跟著動；日誌確認三個 tracker 的校正映射。`-202` 尚未解除，但未阻斷這項本機測試。
4. **本專案 OSC 隔離測試（進行中，預估 20–40 分鐘）：** 停用 AnyaDance 的三個 SteamVR tracker，保留虛擬 HMD／控制器，再執行 `tracker_probe.py`。分別記錄 OSC Debug、FBT 校正與本機腳部動作。若無法隔離，AnyaDance 的成功只能證明虛擬 SteamVR 路線；另評估由 Windows receiver 輸出至已文件化的 AnyaDance loopback UDP 作替代 backend。
5. **遠端驗收（待驗證，預估 15–30 分鐘，需另一位玩家）：** 私人房間用未修改的 Humanoid Avatar，切換靜止／抬腳，讓另一位玩家辨認。分開記錄 AnyaDance SteamVR tracker 與隔離後的 OSC tracker 結果；記錄本機與遠端觀察、影片及是否有長時間卡住。未取得遠端確認時標示「未完成」。

AnyaDance v0.0.6 原始碼中的 `driver_anyadance.enable_trackers` 會控制是否註冊三個虛擬 tracker，預設為 `true`。這提供隔離測試候選方式；尚未設定為 `false` 或驗證重啟後的裝置列表。進行時應先備份目前設定、保留 HMD／控制器及 2560×1440，重啟後以日誌和 VRChat 裝置列表確認三個 tracker 確實不存在，再啟動 OSC 探針並重新校正。

## 記錄欄位與後續決策

每一閘門記錄日期、SteamVR／VRChat／驅動版本、執行模式、虛擬裝置狀態、校正結果、本機動作、遠端玩家觀察與失敗訊息。所有結論分開標示「虛擬 SteamVR FBT」和「OSC Tracker FBT」。

Phase 0 只有在 **未修改 Avatar 可校正，且遠端玩家可見持續的下半身姿勢變化**時通過。通過後才決定 Windows `TrackerOutput` 使用 OSC 或 SteamVR 驅動 backend；在此之前保留現有 `parameters` 模式。

AnyaDance 作者在 [README](https://github.com/anyapipira/AnyaDance#disclaimer) 提醒：在連線遊戲使用虛擬裝置有帳號風險；其驅動註冊也會更動 SteamVR 設定。實際測試前須核對這項風險與還原步驟，不將工具作者的聲明當成 VRChat 官方政策結論。
