# VRChat Track：單手機姿勢追蹤

目標：一支 Android 手機辨識人體姿勢，經私人 Wi-Fi 傳到 Windows，再透過 VRChat 原生 OSC Trackers 與 FBT／IK 驅動**未修改的購買 Humanoid Avatar**，讓私人房間的其他玩家看見。現階段使用 AnyaDance 提供虛擬 HMD 與雙控制器；不修改 VRChat client 或 Avatar。

## 目前狀態（2026-11-06）

| 項目 | 結果 |
| --- | --- |
| VR 模式 Phase 0 | **通過**。AnyaDance 的 SteamVR trackers 停用後，合成 OSC 髖與雙腳完成校正；本機及遠端玩家都看到兩輪右腳抬起／放下。遠端玩家不知道切換時間與腳別。 |
| Phase 1 | OSC Vector3 encoder 與可指定髖／左右腳 ID 的 `TrackerOutput` 已完成本機 UDP 測試。 |
| 手機到 VRChat Tracker | **尚未接通**。前鏡頭離線複驗已確認修正後的左右腳與右轉方向。最新同影格 2D／3D 右腳測試已保存並離線重播，但已知 20 cm 箱面只估出 6.9–7.8 cm 踝點增量；來源 3D 變化也偏小，尺度驗證仍未通過。手機 OSC 保持停用；精度、長時間穩定性及 HMD 對齊仍待解決。 |
| SteamVR `-202` | 仍在。VRChat 的 VR 畫面與選單可用；AnyaDance 的桌面顯示路徑是待驗證的可能原因。Headset Window 保持 **2560×1440**。 |
| 其他 | 純 Desktop 的原生 FBT 未通過；長時間穩定性與手機姿勢的遠端同步未驗證。Unity smoke test 受 License Client IPC timeout 阻擋。 |

這次 Phase 0 驗收證實的是**合成 OSC tracker**，不能當作手機姿勢輸出已完成。VRChat 曾把 tracker 3 映射為右腳，之後須以當次校正結果設定左右 ID。

## 從這裡開始

1. [OSC Tracker MVP 計畫](OSC_TRACKER_MVP_PLAN.md)：目前主線、完成條件與下一步。
2. [虛擬 HMD 與 Phase 0 證據](VIRTUAL_HMD_PHASE0_PLAN.md)：`-202` 診斷、設定備份與遠端盲測紀錄。
3. [Windows 操作](windows/README.md)／[Phase 0 探針](windows/TRACKER_PHASE0.md)：接收端、測試指令與 OSC 隔離方式。
4. [Android 操作](android/README.md)：手機 App 建置與 LAN 傳輸。
5. [六參數舊路線](PROJECT_PLAN.md)：自製 Avatar 的保留功能；不適用於未修改的購買 Avatar。

Windows 自動測試在 `windows` 目錄執行：

~~~powershell
python -B -m unittest discover -v
~~~
