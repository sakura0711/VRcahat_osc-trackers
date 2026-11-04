# 單手機 VRChat 姿勢控制 MVP

使用一台 Android 手機辨識定點姿勢，經私人 Wi-Fi 傳給 Windows，再以 OSC 嘗試控制桌面模式的 VRChat Avatar。角色移動仍使用鍵盤。

目前已完成 Android 辨識、手機到 Windows 的短時間 Wi-Fi 實測、Windows 六個姿勢參數的校正／濾波／OSC 輸出、官方 Robot 的 Unity Animator 骨骼測試，以及 SDK 本機 Build & Test。VRChat 已回傳六個 OSC 測試參數；使用者確認手臂、彎膝與 WASD 共存正常，先前的彎膝滑行已修正並在遊戲內重測。手機到遊戲的完整流程、10 分鐘穩定性與完整視覺延遲尚未驗證。六個單軸參數不是完整 3D 全身追蹤。

- [計畫書及進度](PROJECT_PLAN.md)
- [Android 建置、安裝與操作](android/README.md)
- [Android 與 Wi-Fi 實測紀錄](android/TEST_RESULTS.md)
- [Windows 接收端與 OSC 測試](windows/README.md)
- [Windows 自動測試與合成壓力測試紀錄](windows/TEST_RESULTS.md)
- [Unity 測試 Avatar 專案](VRChatTrackAvatar/)
- [Unity Avatar 設定與測試](VRChatTrackAvatar/AVATAR_SETUP.md)
- [Unity Animator 實測紀錄](VRChatTrackAvatar/TEST_RESULTS.md)

Windows 接收端使用 Python 3.12 標準函式庫。執行自動測試：

~~~powershell
cd windows
python -B -m unittest discover -v
~~~

Git 倉庫已建立；首次提交前請先檢查 `git status --short --untracked-files=all` 與各檔案內容。

## Unity 測試環境

Unity Hub、Creator Companion、VPM 與 VRChat 指定的 Unity 2022.3.22f1 已安裝在 `E:\UnityTools`。`VRChatTrackAvatar` 是官方 Avatar 範本，VPM manifest 固定 VRChat SDK 3.10.6。SDK 套件由 VPM 還原，不存入 Git；Resolver 保留在專案內。

Unity Hub 登入及授權已完成。官方 Robot PC 範例已另存為 `Assets/VRChatTrackRobot.unity`，並建立六參數 Animator；Unity 骨骼及圖層測試通過，VRChat SDK 本機 **Build & Test** 已完成。使用者已確認直接 OSC 驅動六個動作、自然待機和 WASD 共存；下一步需依 [Avatar 設定](VRChatTrackAvatar/AVATAR_SETUP.md) 以手機輸入重新驗證。該測試 Avatar 僅供本機測試，尚未驗證遠端同步。

參考：[VRChat 目前支援的 Unity 版本](https://creators.vrchat.com/sdk/upgrade/current-unity-version/)、[Avatar 本機測試](https://creators.vrchat.com/avatars/#local-avatar-testing)、[VPM 原始碼管理](https://vcc.docs.vrchat.com/vpm/source-control/)。

## 原生 OSC Tracker 新主線

目前目標已改為使用手機姿勢驅動 VRChat 原生 FBT／IK，讓未修改的正常或購買 Avatar 可由遠端玩家看到；先前六參數 Animator 保留作為自製 Avatar 的 fallback。詳見 [OSC Tracker MVP 計畫](OSC_TRACKER_MVP_PLAN.md) 與 [Phase 0 實測步驟](windows/TRACKER_PHASE0.md)。2026-11-05 已在虛擬 HMD 的 VR 模式、停用 AnyaDance 自帶 SteamVR tracker 後，以合成 OSC 髖與雙腳完成 VRChat FBT 校正；使用者在本機鏡子確認兩輪左腳抬起並放下。手機姿勢尚未接入原生 tracker，購買 Avatar 類型與私人房間遠端同步仍待驗收，因此 Phase 0 尚未通過，也尚未實作 TrackerOutput；純 Desktop 支援亦未確認。舊計畫及本頁上述段落是既有六參數成果紀錄。
