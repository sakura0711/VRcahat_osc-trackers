# SteamVR `-202` 與虛擬 HMD 環境

**狀態（2026-11-05）：SteamVR `-202` 仍在；VRChat 的 VR 畫面、選單與 FBT 盲測仍可用。** 驅動顯示路徑是待驗證的可能原因，尚非已證實的修復。Phase 0 驗收紀錄見 [2026-11-05 Phase 0](../docs/logs/2026-11-05-phase0.md)。

## 目前環境

- Windows 10、SteamVR 2.18.4、AnyaDance v0.0.6，位於 `<工具目錄>\AnyaDance-v0.0.6\anyadance`。
- AnyaDance 提供虛擬 HMD 與左右控制器。為隔離 OSC，SteamVR 設定 `driver_anyadance.enable_trackers=false`；重啟後 `vrserver.txt` 記錄三個 AnyaDance tracker 已跳過。**測 OSC 時保持這項設定。**
- Headset Window 保持使用者指定的 **2560×1440**。VRChat VR 畫面與快速選單可操作；`-202`／NotReady 尚未解除。
- 不修改或注入 VRChat client；目標 Avatar 未為本專案修改。恢復 AnyaDance 自帶 tracker 時，先結束 VRChat／SteamVR，再還原設定並重啟。

## `-202` 診斷與邊界

- SteamVR compositor 記錄 `Forcing debug mode for anyadance driver because of Prop_DisplayDebugMode_Bool` 與 `Headset display is on desktop`。AnyaDance v0.0.6 [驅動原始碼](https://github.com/anyapipira/AnyaDance/blob/v0.0.6/src/driver/virtual_device.cpp) 固定使用桌面顯示相關旗標；[OpenVR 驅動文件](https://github.com/ValveSoftware/openvr/blob/master/docs/Driver_API_Documentation.md) 另有真正的虛擬顯示介面。**驅動顯示路徑是可能原因，尚非已證實的修復。**
- 已試 SteamVR 全螢幕按鈕、Alt+Enter、主螢幕及第二螢幕尺寸；均未消除 `-202`，無須重做。
- 曾在獨立 DLL 實驗中只把 `Prop_DisplayDebugMode_Bool` 設為 `false`；「Forcing debug mode」日誌消失，`Headset display is on desktop` 與 `-202` 仍在。因此只關掉 debug 旗標不是修復。原 DLL 已還原；沒有改動 VRChat client。
- 真正修復需另外驗證符合 OpenVR 的虛擬顯示路徑與同步；不能只隱藏警告。`-202` 仍在時，VRChat 畫面、選單和 FBT 盲測仍可用。

## 設定與備份

| 用途 | 位置 |
| --- | --- |
| SteamVR 原始設定 | `<工具目錄>\steamvr-baseline-2026-11-04` |
| 尺寸試驗前設定 | `%TEMP%\steamvr.vrsettings.before-anyadance-fullscreen-20261105.json` |
| 關閉 AnyaDance trackers 前的設定 | `<工具目錄>\steamvr-before-osc-isolation-20261105.json` |
| AnyaDance 原版 DLL 備份 | `<工具目錄>\AnyaDance-v0.0.6\driver_anyadance.before-debug-experiment.dll` |

目前測試方式見 [Phase 0 探針操作](../windows/TRACKER_PHASE0.md)。鍵盤校正操作見 [AnyaDance 操作參考](anyadance-controls.md)。
