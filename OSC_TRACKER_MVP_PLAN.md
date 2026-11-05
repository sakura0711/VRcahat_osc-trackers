# 原生 OSC Tracker MVP 計畫

**現況（2026-11-05）：虛擬 HMD 的 VR 模式 Phase 0 已通過本機與私人房間遠端驗收；Phase 1 的 OSC 輸出元件已完成，手機姿勢尚未接到 tracker。純 Desktop 原生 FBT 未通過。**

## 目標與邊界

一支 Android 手機拍攝人體姿勢，在手機上以 MediaPipe 取得 landmarks，經私人 Wi-Fi UDP 傳給 Windows。Windows 將可信姿勢換算為 VRChat 原生 OSC Tracker 的公尺位置與 Euler 旋轉，由 VRChat FBT／IK 驅動未修改的購買 Humanoid Avatar，並在私人房間讓其他玩家看見。

現有六個 `Puppet/*` Avatar Parameters 保留供可編輯的自製 Avatar 使用；它們不是購買 Avatar 的通用 FBT 路線。不修改或注入 VRChat client，不要求修改購買 Avatar。虛擬 HMD 提供頭與雙手，OSC 只需先送髖與雙腳。單鏡頭的房間深度、遮擋與腳部朝向仍是待解問題。

## 已證實：Phase 0

2026-11-05，在 AnyaDance 自帶 SteamVR trackers 設為 `enable_trackers=false` 的情況下：

1. VRChat 以虛擬 HMD 與左右控制器進入 VR 模式；本專案探針以 20 Hz 向本機 UDP 9000 發送髖與雙腳 OSC。
2. VRChat 記錄三個 OSC tracker 活動並完成 FBT 校正。當次 `OSCTracker1 → 髖`、`OSCTracker4 → 左腳`、`OSCTracker3 → 右腳`。
3. 使用者在未修改的購買 Humanoid Avatar 上，於本機鏡子確認兩輪右腳抬起／放下。
4. 同房遠端玩家不知道切換時間與腳別，原樣回報「右 → 放下 → 右 → 放下」。

這證實**合成 OSC tracker 在此 VR 模式能驅動 IK 並遠端同步**。它不證明手機姿勢端到端、純 Desktop FBT 或長時間穩定性。詳細時間與設定見 [Phase 0 證據](VIRTUAL_HMD_PHASE0_PLAN.md)；重做步驟見 [探針操作](windows/TRACKER_PHASE0.md)。SteamVR `-202` 仍在，不影響上述實測成立，根因與修復仍待驗證。

## OSC 契約與目前程式

一般 tracker 使用 `/tracking/trackers/{1..8}/position` 與 `/tracking/trackers/{1..8}/rotation`，各帶三個 OSC float。位置為 Unity 左手系公尺；旋轉為 Euler 度。VRChat 不保證 ID 3、4 固定對應左／右腳，因此必須以**當次 FBT 校正映射**設定角色到 ID 的關係。[VRChat 官方 OSC Trackers 文件](https://docs.vrchat.com/docs/osc-trackers)。

`windows/tracker_output.py` 已提供 Vector3 編碼與只送本機的 `TrackerOutput`：呼叫端明確傳入髖、左腳、右腳的 ID 和已校正 transform；無效批次不送出。`tracker_probe.py` 共用編碼器。Loopback 測試覆蓋左右 ID 對調、OSC 位址／型別與無效資料。

`windows/tracker_pose.py` 是**離線**的手機姿勢轉換基礎。站姿樣本建立身體右、上、前軸，實測站姿髖高決定尺度；每幀以可見腳底估計地面，輸出髖與雙腳的位置及 yaw。校正前、低信心或缺點時不產生 transform；失追超過 250 ms 會清除校正，須重新站姿校正。合成影格測試涵蓋站姿、單腳抬起、蹲下、轉身、鏡像、yaw 與失追。**這些是數學與保護條件測試，不是手機或 VRChat 實測。**

`windows/tracker_preview.py` 已提供不送 OSC 的手機 UDP 離線預覽：沿用 receiver 的封包驗證與 ACK，顯示計算出的髖／雙腳公尺位置及 yaw。仍須用真實手機影格確認方向、地面與尺度，才能考慮接到 VRChat tracker 輸出。

`pose_receiver.py` 目前只在 `--osc` 下送六個 Avatar 參數，預設不送 OSC。它**沒有**手機 landmarks 的 tracker 座標、朝向、相機鏡像、地面與 yaw 校正，也沒有 tracker 失追／超時策略。不得把現有 receiver 當作手機 FBT。

## 接下來的階段

| 階段 | 工作與驗收 |
| --- | --- |
| Phase 1：輸出整合 | 建立安全的 `--output parameters|trackers` 選擇；預設不送 OSC。只有座標校正完成且身體部位 ID 經確認才允許 tracker 輸出。加入停止、超時及 loopback 測試；保留六參數模式。 |
| Phase 2：單手機姿勢 | 將 MediaPipe world landmarks 以身高、地面、相機面向／鏡像和初始 yaw 校正為髖與雙腳的 VRChat 座標；處理低信心、遮擋與失追。先驗證站立、抬腳、蹲下與轉身。 |
| Phase 3：自然度 | 測量腳部抖動與延遲，再選擇濾波及是否增加胸、肘、膝等點。只加入品質足以改善 IK 的 tracker。 |
| Phase 4：實機驗收 | 以單手機在未修改的購買 Avatar 上完成本機與遠端盲測，並記錄 10 分鐘 FPS、封包、姿勢有效率、漂移及延遲。 |

**下一個實作點：** 以真實手機影格確認鏡像、前向、腳底與 yaw；再設計接收端的安全輸出選擇與失追後 VRChat tracker 的清除／停止行為。未確認前不把手機資料接到 `TrackerOutput`。
