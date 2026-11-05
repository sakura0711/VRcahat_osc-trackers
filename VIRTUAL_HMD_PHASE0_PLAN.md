# Phase 0 延伸：Windows 10 無實體頭顯的 VR 模式可行性

**狀態（2026-11-05）：隔離並停用 AnyaDance 自帶 SteamVR trackers 後，本專案的髖＋雙腳 OSC 探針已在 VRChat 完成校正、本機腳部動作與私人房間遠端盲測。使用者確認目標為未修改的購買 Humanoid Avatar；遠端玩家在不知道切換時間與腳別時，正確回報兩輪腳部抬起／放下。虛擬 HMD 的 VR 模式 Phase 0 已通過；左右腳映射曾對調，SteamVR -202 仍在，手機姿勢輸出尚未實作。**

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
- 先前 VRChat 日誌雖出現 `Initialize SixPoint Avatar` 與 `Applying calibration to avatar... type: 8`，當時仍未以腳部動作或遠端觀察確認；後續本機與遠端動作已另行驗證，見下列紀錄。
- 2026-11-05 使用者已在 VRChat 找到 `Calibrate FBT`，完成校正後拖動 AnyaDance 的髖及雙腳，確認本機 Avatar 下半身跟著動。當次 VRChat 日誌明列 `anyadance_hip_001`、`anyadance_left_foot_001`、`anyadance_right_foot_001` 參與校正，並分別映射為 13、11、12。這證實 **AnyaDance SteamVR tracker 的本機 FBT 動作**；當時尚未測本專案 OSC tracker，後續 OSC 隔離測試另列於下。`-202` 在可用的 VR 畫面與 FBT 動作下仍存在，不能把它視為本機 FBT 校正失敗的證據。
- 2026-11-05 OSC 隔離準備：把原 SteamVR 設定備份到 `E:\10_DevTool\steamvr-before-osc-isolation-20261105.json`（SHA-256 `D0ED14BC030EC4B899F16EED94B74A821E9CA9004C4780BE84C1E9973EE993DE`），只將 `driver_anyadance.enable_trackers` 設為 `false`。重啟後 `vrserver.txt` 顯示 `trackers=disabled`，並逐一記錄跳過三個 AnyaDance tracker；HMD、控制器及 2560×1440 設定保留。新 VRChat 日誌顯示左右控制器，未見 AnyaDance tracker 連線。還原時須先關閉 SteamVR，再從備份恢復設定並重啟。
- OSC 狀態複核：VRChat 啟動日誌早期印出 `OSC enabled: False`，但同次啟動隨後宣告 OSC UDP 9000 與 OSCQuery 52766；當時 VRChat 行程確實監聽 UDP 9000，使用者登錄設定 `UI.Settings.Osc_h1043380067=1`，OSCQuery `/?HOST_INFO` 回報 `OSC_PORT=9000`，並列出 `/tracking/trackers/1/position`、`rotation` 為 `fff` 寫入路徑。這些服務資訊當時只證明 OSC 已啟用；後續封包接收、校正與本機動作證據見下。從 [VRChat Main Menu 的 Settings > OSC](https://wiki.vrchat.com/wiki/Settings) 可開啟 OSC Debug Panel，不必先打開圓形 Action Menu。
- OSC 隔離短探針：`tracker_probe.py --height 1.70 --calibration-seconds 8 --pose-seconds 5 --cycles 1` 對 `127.0.0.1:9000` 發送站姿、左腳抬起、站姿，共約 18 秒；使用者看著 VRChat 畫面，沒有看到變化。當時沒有開 OSC Debug Panel，也沒有進行 OSC tracker 校正；後續實測補上這兩項。
- OSC 接收驗證：使用者開啟 OSC Debug Panel 後，36 秒的 Hip＋雙腳 20 Hz 探針太快而看不清。改用既有 `tracker_probe.vector_message` 每秒只送一次固定 `(0, 0.9, 0)` 至 `/tracking/trackers/1/position`，連續 45 秒；使用者確認該路徑持續閃爍，數值不變符合固定封包。這證明 VRChat 接收 OSC tracker 位址；後續校正與本機動作另行驗證。
- OSC FBT 本機驗證：使用者提供身高 1.67 公尺。先以 `--calibration-seconds 120 --pose-seconds 20 --cycles 2` 發送髖＋雙腳，VRChat 日誌於 03:29:18 記錄 `OSCTracker1/3/4` 校正並分別映射髖 13、左腳 11、右腳 12；使用者確認完成校正。該輪接近停止時才校正，日誌於 03:29:20 顯示活動 tracker 從 3 變 0，使用者沒有看到腳部切換。隨後用 `python -B tracker_probe.py --height 1.67 --calibration-seconds 60 --pose-seconds 30 --cycles 2` 重測；03:31:10 三個 OSC tracker 再度活動並沿用相同映射，直到 03:34:20 探針停止才變 0。使用者在本機鏡子確認 **兩輪左腳抬起並放下**。AnyaDance SteamVR trackers 全程維持停用，因此這是本專案 OSC tracker 的本機 FBT 動作證據；仍未證明其他玩家可見。
- 圓形 Action Menu 仍未能操作：AnyaDance v0.0.6 原版只提供搖桿 X/Y；獨立實驗版加入 `R → 右搖桿按下`，AnyaDance 自帶測試通過，使用者截圖證實 UI 顯示多次 `R down/up` 並標記 `Sent`，SteamVR 日誌也檢查了 `joystick::click` 綁定，但使用者在 VRChat 畫面按 `R` 仍無反應。尚未證實按鍵抵達 VRChat，不能把此實驗列為成功；測試後已還原原版 exe、DLL 與 profile。補丁與原版備份位置見 [AnyaDance 操作參考](ANYADANCE_CONTROLS.md)。
- 註冊前的 `steamvr.vrsettings` 與 `openvrpaths.vrpath` 已另存於 `E:\10_DevTool\steamvr-baseline-2026-11-04`，供還原核對。
- 另有 [Virtual VR Emulator](https://github.com/sasaken1102r/Virtual-VR-Emulator/blob/main/README.en.md) 僅提供虛擬 HMD + 雙控制器，較適合隔離測試 OSC tracker；但作者的建置需求列 Windows 11，Windows 10 相容性尚未確認。
- 不修改或注入 VRChat client。虛擬裝置由 SteamVR 驅動提供；Avatar 保持未修改。

## 依序執行的閘門

1. **SteamVR 基礎（已完成）：** 官方 SteamVR 已安裝並啟動；未有 HMD 時回報 `Hmd Not Found (108)`。先前只選擇 VRChat「Steam VR 模式」不足以證明已在 VR 模式。
2. **虛擬裝置（已完成）：** AnyaDance 驅動已註冊；SteamVR 顯示虛擬 HMD、左右控制器及三個 tracker。原始設定已有備份；頭顯視窗尺寸依使用者要求設為 2560×1440。解除註冊尚未執行，以便繼續 Phase 0。
3. **VRChat 校正與本機動作（已完成，僅 AnyaDance SteamVR trackers）：** 使用者完成 FBT 校正，拖動髖與雙腳時 Avatar 下半身跟著動；日誌確認三個 tracker 的校正映射。`-202` 尚未解除，但未阻斷這項本機測試。
4. **本專案 OSC 隔離本機測試（已完成）：** 已停用 AnyaDance 的三個 SteamVR tracker，保留虛擬 HMD／控制器；OSC 接收、三個 OSC tracker 的 FBT 校正映射、兩輪本機左腳抬起與放下皆已確認。全身六點由虛擬 HMD（頭）、兩支虛擬控制器（雙手）及三個 OSC tracker（髖、雙腳）組成，無須送六個額外 OSC tracker。此閘門不代表遠端通過。
5. **遠端驗收（已完成，限本次虛擬 HMD VR 模式）：** 使用者確認穿著未修改的購買 Humanoid Avatar；另一位玩家在同一私人房間，不知道切換時間與腳別，正確回報兩輪右腳抬起與放下。本機鏡子亦確認。AnyaDance SteamVR trackers 全程停用，VRChat 日誌顯示目前 Avatar 的三個 OSC tracker 活動與校正映射。這通過 Phase 0 的遠端可見性閘門，並不驗證純 Desktop 或手機姿勢輸出。

2026-11-05 遠端測試進度：使用者與另一位玩家已進同一私人房間，使用者表示目標是未修改的購買 Humanoid Avatar；另一位玩家可見 AnyaDance 的一般移動，這不等於 OSC FBT。第一次隔離探針開始後使用者回報 VRChat 當掉並重啟，探針已停止；該次輸出日誌有 graceful quit 與結束時例外，尚不足以判定原因。第二次固定時間探針期間，使用者操作校正，但 VRChat 日誌沒有 `OSCTracker1/3/4` 映射，本機及遠端均未見腳部變化，不能據此判定遠端 OSC 同步失敗。為等到確定校正才切換姿勢，`tracker_probe.py` 已加入手動模式，並以本機 UDP 測試驗證指令切換。第三次手動探針於 12:03:37 有效校正三個 OSC tracker，但這次 `OSCTracker4` 映射左腳 11、`OSCTracker3` 映射右腳 12，與先前本機測試左右相反；12:05:59 使用者切換 Avatar，活動 tracker 從 3 變 0，新 Avatar 到 12:06:32 才重新校正，探針於 12:06:43 停止。遠端玩家回報「沒看到」，本機當時正在調整 OSC、沒有觀察鏡子；切換 Avatar 後沒有完整姿勢循環，**當次無法判定**。隨後使用者固定目標 Avatar，完成下列完整重測。

2026-11-05 完整遠端盲測：AnyaDance `enable_trackers=false`，HMD／雙控制器與 2560×1440 保留。手動探針以使用者身高 1.67 公尺，對 `127.0.0.1:9000` 以 20 Hz 持續送 Hip＋Feet；VRChat 日誌於 12:12:04 顯示活動 OSC tracker 從 0 變 3，12:12:05 記錄 `OSCTracker1 → 髖 13`、`OSCTracker4 → 左腳 11`、`OSCTracker3 → 右腳 12`。當前 Avatar 在兩輪切換期間未變更；探針依序於 12:12:40 升高 tracker 3、12:13:12 回站姿、12:13:54 再升高 tracker 3、12:14:28 回站姿，結束後活動 tracker 於 12:15:04 降為 0。遠端玩家事先不知道時間與腳別，原樣回報「右 → 放下 → 右 → 放下」；使用者在本機鏡子也確認兩輪。遠端另提到手從 T 字變為自然垂下，僅列為附帶觀察，不歸因於 OSC 腳部訊號。使用者確認 Avatar 為未修改的購買 Humanoid；日誌中目標 Avatar 名稱為 `チセ -chise-`。**此結果證實本機及遠端能看到 OSC tracker 驅動的腳部變化，Phase 0 的 VR 模式閘門通過。** ID 3/4 左右映射與探針暫定慣例相反，需於下一階段處理；純 Desktop 與手機姿勢端到端仍未通過。

AnyaDance v0.0.6 原始碼中的 `driver_anyadance.enable_trackers` 控制是否註冊三個虛擬 tracker；目前已設為 `false` 且重啟日誌確認跳過。執行 OSC 探針時不得重新開啟此設定。恢復 AnyaDance 原本的本機 FBT 時，先關閉 VRChat／SteamVR，還原上述設定備份，再依正常流程啟動並重新校正。

## 記錄欄位與後續決策

每一閘門記錄日期、SteamVR／VRChat／驅動版本、執行模式、虛擬裝置狀態、校正結果、本機動作、遠端玩家觀察與失敗訊息。所有結論分開標示「虛擬 SteamVR FBT」和「OSC Tracker FBT」。

Phase 0 只有在 **未修改 Avatar 可校正，且遠端玩家可見持續的下半身姿勢變化**時通過。通過後才決定 Windows `TrackerOutput` 使用 OSC 或 SteamVR 驅動 backend；在此之前保留現有 `parameters` 模式。

AnyaDance 作者在 [README](https://github.com/anyapipira/AnyaDance#disclaimer) 提醒：在連線遊戲使用虛擬裝置有帳號風險；其驅動註冊也會更動 SteamVR 設定。實際測試前須核對這項風險與還原步驟，不將工具作者的聲明當成 VRChat 官方政策結論。
