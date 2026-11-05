# 虛擬 HMD：Phase 0 證據與 SteamVR 顯示診斷

**狀態（2026-11-05）：本專案合成 OSC 髖與雙腳已在虛擬 HMD 的 VR 模式完成 FBT 校正、本機腳部動作及私人房間遠端盲測。Phase 0 通過。SteamVR `-202` 仍在；手機姿勢輸出尚未完成。**

## 目前環境

- Windows 10、SteamVR 2.18.4、AnyaDance v0.0.6，位於 `E:\10_DevTool\AnyaDance-v0.0.6\anyadance`。
- AnyaDance 提供虛擬 HMD 與左右控制器。為隔離 OSC，SteamVR 設定 `driver_anyadance.enable_trackers=false`；重啟後 `vrserver.txt` 記錄三個 AnyaDance tracker 已跳過。**測 OSC 時保持這項設定。**
- Headset Window 保持使用者指定的 **2560×1440**。VRChat VR 畫面與快速選單可操作；`-202`／NotReady 尚未解除。
- 不修改或注入 VRChat client；目標 Avatar 未為本專案修改。恢復 AnyaDance 自帶 tracker 時，先結束 VRChat／SteamVR，再還原設定並重啟。

## 已證實的 OSC FBT

1. 先前以 AnyaDance 自帶 SteamVR tracker 完成的本機 FBT 校正，只證明該工具的 tracker 可用；之後已停用它們，避免與 OSC 混淆。
2. 本專案 `windows/tracker_probe.py` 送出髖與雙腳的合成 OSC。使用者在本機鏡子確認兩輪腳抬起／放下；這次校正將 `OSCTracker3` 映射為左腳。
3. 完整遠端盲測使用身高 1.67 公尺、20 Hz、`127.0.0.1:9000`。VRChat 日誌在 **12:12:04** 記錄活動 OSC tracker 由 0 變 3；**12:12:05** 將 `OSCTracker1 → 髖 13`、`OSCTracker4 → 左腳 11`、`OSCTracker3 → 右腳 12`。探針於 **12:12:40 右腳抬起 → 12:13:12 站姿 → 12:13:54 右腳抬起 → 12:14:28 站姿**；停止後活動 tracker 於 12:15:04 回到 0。
4. 使用者確認當次穿著未修改的購買 Humanoid Avatar；日誌中的 Avatar 名稱為 `チセ -chise-`。本機鏡子確認兩輪。遠端玩家事先不知道時間與腳別，原樣回報「右 → 放下 → 右 → 放下」。另觀察到手從 T 字變自然垂下，未證實這由腳部 OSC 造成。

**結論：** 此環境的虛擬 HMD VR 模式，合成 OSC tracker 可經 FBT／IK 驅動 Avatar 並讓遠端玩家看到。左右腳映射曾對調，不得硬編碼 ID 3／4。這不證明手機姿勢、純 Desktop 原生 FBT 或長時間穩定性。Desktop 模式只觀察到 OSC Debug 封包，沒有完成 FBT 校正或 Avatar 腳部動作。

## `-202` 診斷與邊界

- SteamVR compositor 記錄 `Forcing debug mode for anyadance driver because of Prop_DisplayDebugMode_Bool` 與 `Headset display is on desktop`。AnyaDance v0.0.6 [驅動原始碼](https://github.com/anyapipira/AnyaDance/blob/v0.0.6/src/driver/virtual_device.cpp) 固定使用桌面顯示相關旗標；[OpenVR 驅動文件](https://github.com/ValveSoftware/openvr/blob/master/docs/Driver_API_Documentation.md) 另有真正的虛擬顯示介面。**驅動顯示路徑是可能原因，尚非已證實的修復。**
- 已試 SteamVR 全螢幕按鈕、Alt+Enter、主螢幕及第二螢幕尺寸；均未消除 `-202`，無須重做。
- 曾在獨立 DLL 實驗中只把 `Prop_DisplayDebugMode_Bool` 設為 `false`；「Forcing debug mode」日誌消失，`Headset display is on desktop` 與 `-202` 仍在。因此只關掉 debug 旗標不是修復。原 DLL 已還原；沒有改動 VRChat client。
- 真正修復需另外驗證符合 OpenVR 的虛擬顯示路徑與同步；不能只隱藏警告。`-202` 仍在時，VRChat 畫面、選單和上述 FBT 盲測仍可用。

## 設定與備份

| 用途 | 位置 |
| --- | --- |
| SteamVR 原始設定 | `E:\10_DevTool\steamvr-baseline-2026-11-04` |
| 尺寸試驗前設定 | `C:\Users\user\AppData\Local\Temp\steamvr.vrsettings.before-anyadance-fullscreen-20261105.json` |
| 關閉 AnyaDance trackers 前的設定 | `E:\10_DevTool\steamvr-before-osc-isolation-20261105.json` |
| AnyaDance 原版 DLL 備份 | `E:\10_DevTool\AnyaDance-v0.0.6\driver_anyadance.before-debug-experiment.dll` |

目前測試方式見 [Phase 0 探針操作](windows/TRACKER_PHASE0.md)。鍵盤校正操作見 [AnyaDance 操作參考](ANYADANCE_CONTROLS.md)。
