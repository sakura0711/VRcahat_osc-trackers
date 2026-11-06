# 原生 OSC Tracker MVP 計畫

**現況（2026-11-06）：虛擬 HMD 的 VR 模式 Phase 0 已通過本機與私人房間遠端驗收；Phase 1 的 OSC 輸出元件已完成，手機姿勢尚未接到 tracker。同影格 2D／3D 記錄與重播已完成，實測高度幅度仍不足。純 Desktop 原生 FBT 未通過。**

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

`windows/tracker_pose.py` 是**離線**的手機姿勢轉換基礎。站姿樣本建立身體右、上、前軸，實測站姿髖高決定尺度；每幀以可見腳底估計地面，輸出髖與雙腳的位置及 yaw。校正前、低信心或缺點時不產生 transform；world landmark 低信心與校正期間明顯蹲下也會拒絕。失追超過 250 ms 會清除校正，須重新站姿校正。合成影格測試涵蓋站姿、單腳抬起、蹲下、轉身、鏡像、yaw 與失追。**這些是數學與保護條件測試，不是手機或 VRChat 實測。**

`windows/tracker_preview.py` 已提供不送 OSC 的手機 UDP 離線預覽。2026-11-05 後續以實測髖高 **0.90 m** 和語音時間標記，發現早期手動觀察的左右映射結論不可靠：真人右腳對應到模型左腳。已加入獨立的 `--swap-left-right`，本次前鏡頭採 `--mirror yes --swap-left-right --forward-sign -1 --yaw 0`，使用者確認完整依自己的左右腳完成複驗，左右腳與向右轉再回正的方向成立。**手機資料仍未送進 VRChat**；動作公尺幅度與角度精度沒有獨立量測，不能宣稱準確。數值與限制見 [Windows 驗證紀錄](windows/TEST_RESULTS.md)。

預覽器另提供拒絕原因與品質統計。修正後語音複驗共接受 2,321 幀、產生 1,866 組完整 transforms（80.40%，含就位及校正），一次校正、零次失追。從首次已校正且拒絕計數穩定的快照至結束，後續 1,811／1,811 幀均通過目前檢查；這不是追蹤時間比例或十分鐘穩定性驗收。

後續固定鏡頭離地 125 cm、人到手機 300 cm，以使用者確認穩固的 20 cm 行李箱踏面檢查高度。右踝相對前／後地面基準只增加 5.8／3.5 cm，左踝只增加 4.2／4.1 cm，**高度幅度驗證未通過**。消除共用地面平移後的兩踝差值仍不足，尚不能區分模型估計與校正軸投影。整輪 2,932 個有效封包、一次校正、零失追、零 OSC；資料通過檢查不代表公尺準確。已保留分段衍生樣本並補上可選的離線高度分解診斷，不能把本輪資料直接放大後接到 VRChat。詳細設定與數據見 [Windows 驗證紀錄](windows/TEST_RESULTS.md)。

不需實機的安全檢查已補上數值邊界、水平髖朝向與超時後時間高水位保護；2026-11-06 最新 69 項 Windows 測試通過，包含 32 組已知相機座標變換、明確左右標籤設定、高度診斷分解、同封包 2D／3D 記錄重播與測試工具提前停止。預覽器只有明確指定 `--record PATH` 才保存來源 landmarks、診斷及完整精度輸出；離線重播不開 socket。`soak_tracker_loopback.py` 的 60 秒合成 UDP 情境也通過，涵蓋失追與新工作階段，沒有 OSC 輸出。這些結果不替代實測尺度、腳部 yaw 品質或 HMD 對齊。

`pose_receiver.py` 目前只在 `--osc` 下送六個 Avatar 參數，預設不送 OSC。離線 tracker 校正尚未接入它，也沒有 tracker 模式的失追／超時策略。不得把現有 receiver 當作手機 FBT。

2026-11-06 已完成同影格 2D／3D 右腳 20 cm 箱面語音量測，使用者確認全程照做。三段保持區間 568／568 幀有效、零失追；全檔 1,542 幀與 2,060 次 tick 離線重播一致，零手機 OSC。右踝只增加 6.87／7.84 cm；共用地面修正前已只增加約 7.7–7.8 cm。代表來源兩踝 3D 向量的變化乘尺度後長度僅 11.91／14.77 cm，支持低估不只出在地面平移；單改固定上軸投影也不足。2D 點有移動，但缺少影像真值，仍不能區分 2D 定位與三維估計誤差。原始資料留在本機 `captures`，設定、統計與 SHA-256 見 [驗證紀錄](windows/TEST_RESULTS.md)。姿勢演算法未改動，不能把兩輪數字差異當成改善。

## 接下來的階段

| 階段 | 工作與驗收 |
| --- | --- |
| Phase 1：輸出整合 | 建立安全的 `--output parameters|trackers` 選擇；預設不送 OSC。只有座標校正完成且身體部位 ID 經確認才允許 tracker 輸出。加入停止、超時及 loopback 測試；保留六參數模式。 |
| Phase 2：單手機姿勢 | 將 MediaPipe world landmarks 以身高、地面、相機面向／鏡像和初始 yaw 校正為髖與雙腳的 VRChat 座標；處理低信心、遮擋與失追。先驗證站立、抬腳、蹲下與轉身。 |
| Phase 3：自然度 | 測量腳部抖動與延遲，再選擇濾波及是否增加胸、肘、膝等點。只加入品質足以改善 IK 的 tracker。 |
| Phase 4：實機驗收 | 以單手機在未修改的購買 Avatar 上完成本機與遠端盲測，並記錄 10 分鐘 FPS、封包、姿勢有效率、漂移及延遲。 |

後續 [離線追查](windows/HEIGHT_INVESTIGATION_2026-11-06.md) 顯示，抬腳時模型右大腿段長約由 38.7 cm 變成 34.7 cm，肩寬幾乎不變；腳跟與腳尖也同樣低估。固定地面、改上軸或直接固定骨長的試算皆不足，時間戳／序列化精度也不足以解釋主要誤差。2D 假設性比例換算同樣偏小，不能先認定影像點完全正確。這些定位了來源幾何問題，仍未證明 2D 定位或三維估計哪一項是主因。

已完成 [選用影像對照工具](windows/IMAGE_PAIR_GUIDE.md)：App 0.2.0 只有手動啟用才限時保存同一回呼影像與 landmarks，附影格識別、尺寸、已套用旋轉／鏡像及模型資訊；資料先留在手機私有 no-backup 目錄，再由使用者匯出 ZIP。Windows 驗證雜湊與來源後產生離線疊點頁，可精確連結同輪 tracker JSONL；不開 socket、不送 OSC。APK 建置／lint、獨立 Kotlin 檢查、Kotlin 合成 ZIP 交換與 Windows 69 項通過；真手機影像擷取／GPU 回呼／匯出仍待驗證。

**下一個實作點：** 先語音通知需要更新 App 或實測，確認 0.2.0 的手動擷取、停止與匯出可用，再取得必要的同影格影像，核對腳點與箱面／地面的真實位置。既有座標檔未保存影像，不能靠純座標還原這項真值。只測新工具與待查項目，不例行重做左右方向或 Phase 0。高度問題解決後，仍須量化角度精度、腳部 yaw／地面偏移，設計接收端安全輸出選擇及失追／停止行為。HMD 絕對 yaw 對齊也須實測。後鏡頭與超廣角尚未實作，切換後須獨立驗證。這些完成前不把手機資料接到 `TrackerOutput`。
