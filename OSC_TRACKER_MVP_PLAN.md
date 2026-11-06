# 原生 OSC Tracker MVP 計畫

**現況（2026-11-06）：虛擬 HMD 的 VR 模式 Phase 0 已通過合成 tracker 的本機與遠端驗收；Phase 1 安全輸出已完成。本機手機即時姿勢已接到 OSC tracker，使用者確認 VRChat OSC Debugger 更新且 Avatar 跟著動作。已存 ZIP 回放另看到 Avatar 右腳抬起。公尺精度、即時腳別、遠端手機動作與長時間穩定性未驗證；純 Desktop 原生 FBT 未通過。**

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

`windows/tracker_preview.py` 已提供不送 OSC 的手機 UDP 離線預覽。2026-11-05 後續以實測髖高 **0.90 m** 和語音時間標記，發現早期手動觀察的左右映射結論不可靠：真人右腳對應到模型左腳。已加入獨立的 `--swap-left-right`，本次前鏡頭採 `--mirror yes --swap-left-right --forward-sign -1 --yaw 0`，使用者確認完整依自己的左右腳完成複驗，左右腳與向右轉再回正的方向成立。當輪手機資料沒有送進 VRChat；後續已存 ZIP 姿勢回放結果見下方。動作公尺幅度與角度精度沒有獨立量測，不能宣稱準確。數值與限制見 [Windows 驗證紀錄](windows/TEST_RESULTS.md)。

預覽器另提供拒絕原因與品質統計。修正後語音複驗共接受 2,321 幀、產生 1,866 組完整 transforms（80.40%，含就位及校正），一次校正、零次失追。從首次已校正且拒絕計數穩定的快照至結束，後續 1,811／1,811 幀均通過目前檢查；這不是追蹤時間比例或十分鐘穩定性驗收。

後續固定鏡頭離地 125 cm、人到手機 300 cm，以使用者確認穩固的 20 cm 行李箱踏面檢查高度。右踝相對前／後地面基準只增加 5.8／3.5 cm，左踝只增加 4.2／4.1 cm，**高度幅度驗證未通過**。消除共用地面平移後的兩踝差值仍不足，尚不能區分模型估計與校正軸投影。整輪 2,932 個有效封包、一次校正、零失追、零 OSC；資料通過檢查不代表公尺準確。已保留分段衍生樣本並補上可選的離線高度分解診斷，不能把本輪資料直接放大後接到 VRChat。詳細設定與數據見 [Windows 驗證紀錄](windows/TEST_RESULTS.md)。

不需實機的安全檢查已補上數值邊界、水平髖朝向與超時後時間高水位保護；2026-11-06 Android 回放階段 84 項 Windows 測試通過，後續完整 95 項通過，包含 32 組已知相機座標變換、明確左右標籤設定、高度診斷分解、同封包 2D／3D 記錄重播、離線模型／Android 回放結果驗證與測試工具提前停止。預覽器只有明確指定 `--record PATH` 才保存來源 landmarks、診斷及完整精度輸出；離線重播不開 socket。`soak_tracker_loopback.py` 的 60 秒合成 UDP 情境也通過，涵蓋失追與新工作階段，沒有 OSC 輸出。這些結果不替代實測尺度、腳部 yaw 品質或 HMD 對齊。

`pose_receiver.py` 已有明確的 `--output none|parameters|trackers`；預設不送 OSC，舊 `--osc` 仍送六個 Avatar 參數。Tracker 模式經 `tracker_bridge.py` 使用離線校正器與 `TrackerOutput`，要求明填角色 ID、髖高、鏡像、左右標籤、前向與 yaw。低信心／缺點不送新姿勢；`T` 預設 250 ms 可調，短暫保持 `H` 獨立且預設 0。隔離 UDP／合成自動測試已通過；**本機手機即時 OSC 與 Avatar 動作已由使用者確認**，其餘驗收界線見 [Windows 操作](windows/README.md) 與 [測試紀錄](windows/TEST_RESULTS.md)。

2026-11-06 已完成同影格 2D／3D 右腳 20 cm 箱面語音量測，使用者確認全程照做。三段保持區間 568／568 幀有效、零失追；全檔 1,542 幀與 2,060 次 tick 離線重播一致，零手機 OSC。右踝只增加 6.87／7.84 cm；共用地面修正前已只增加約 7.7–7.8 cm。代表來源兩踝 3D 向量的變化乘尺度後長度僅 11.91／14.77 cm，支持低估不只出在地面平移；單改固定上軸投影也不足。2D 點有移動，但缺少影像真值，仍不能區分 2D 定位與三維估計誤差。原始資料留在本機 `captures`，設定、統計與 SHA-256 見 [驗證紀錄](windows/TEST_RESULTS.md)。姿勢演算法未改動，不能把兩輪數字差異當成改善。

## 接下來的階段

| 階段 | 工作與驗收 |
| --- | --- |
| Phase 1：輸出整合 | 已建立 `--output none|parameters|trackers`，預設不送 OSC。只有座標校正完成且當次角色 ID 已明填才允許 tracker 輸出；停止、超時及 loopback 自動測試已完成。本機手機即時動作已初驗，遠端與品質驗收待完成。 |
| Phase 2：單手機姿勢 | 將 MediaPipe world landmarks 以身高、地面、相機面向／鏡像和初始 yaw 校正為髖與雙腳的 VRChat 座標；處理低信心、遮擋與失追。先驗證站立、抬腳、蹲下與轉身。 |
| Phase 3：自然度 | 測量腳部抖動與延遲，再選擇濾波及是否增加胸、肘、膝等點。只加入品質足以改善 IK 的 tracker。 |
| Phase 4：實機驗收 | 以單手機在未修改的購買 Avatar 上完成本機與遠端盲測，並記錄 10 分鐘 FPS、封包、姿勢有效率、漂移及延遲。 |

後續 [離線追查](windows/HEIGHT_INVESTIGATION_2026-11-06.md) 顯示，抬腳時模型右大腿段長約由 38.7 cm 變成 34.7 cm，肩寬幾乎不變；腳跟與腳尖也同樣低估。固定地面、改上軸或直接固定骨長的試算皆不足，時間戳／序列化精度也不足以解釋主要誤差。2D 假設性比例換算同樣偏小，不能先認定影像點完全正確。這些定位了來源幾何問題，仍未證明 2D 定位或三維估計哪一項是主因。

已完成 [選用影像對照工具](windows/IMAGE_PAIR_GUIDE.md)：App 0.2.0 只有手動啟用才限時保存同一回呼影像與 landmarks，附影格識別、尺寸、已套用旋轉／鏡像及模型資訊；資料先留在手機私有 no-backup 目錄，再由使用者匯出 ZIP。Windows 驗證雜湊與來源後產生離線疊點頁，可精確連結同輪 tracker JSONL；不開 socket、不送 OSC。APK 建置／lint、獨立 Kotlin 檢查、Kotlin 合成 ZIP 交換與 Windows 69 項通過。後續真手機擷取／匯出／Windows 匯入亦已確認：新 22 組影像拍到完整右腳箱面動作；純照片離線估計僅上升 5.05／5.13 cm，地面修正前為 6.11／6.53 cm，來源右大腿段長縮短 9.21%。2D 點跟隨抬腳但有局部偏差；透視與來源 2D／3D 的誤差比例仍未分離。詳見 [真手機影像調查](windows/IMAGE_PAIR_REVIEW_2026-11-06.md)。GPU delegate、保存負載與背景停止仍待實測；先前未收到 ACK 的網路問題也未解決，純照片成功不代表連線已修復。

後續 [固定影像模型比較](windows/OFFLINE_MODEL_COMPARISON_2026-11-06.md) 已完成：同一批 PNG 在桌面 CPU IMAGE 模式，Lite 上升約 6.0–6.6 cm、Full 約 16.2–16.3 cm、Heavy 約 6.7–7.1 cm。Full 共用手機原始上軸／尺度仍約 14.3 cm；只替換 2D、保留手機 3D 時仍為原始約 5.1 cm，替換 3D 才出現增量。這隔離了來源幾何的重要影響，沒有排除透視或證明 Full 已準確。Full 仍有段長變化；地面最低點會因模型而改變。新增 `offline_pose_compare.py` 與 7 項檢查，正式算法／手機 App 未改，Python 0.10.21 CPU 單張結果不能當 Android 1.0.0 LIVE_STREAM 的重播。

Android 隔離對照工具已備妥：獨立 `replay` App 0.1.0，MediaPipe 1.0.0、固定 Lite／Full、CPU／GPU 的 IMAGE／VIDEO 選項；無網路與相機權限，不覆蓋相機 App。已用同一批 22 張在唯讀 API 35 x86_64 模擬器完成 88 次 CPU 原生推論，IMAGE 選定 16 張全有效，Lite 上升 6.00／6.58 cm、Full 16.24／16.29 cm；共用手機校正的 Full 為 14.28／14.25 cm。VIDEO 前站姿兩者均 0／5 有效、獨立校正失敗，不當作有效高度比較。詳見 [回放指南與限制](android/REPLAY_GUIDE.md)。APK／lint、Kotlin 核心與跨語言交換、Windows 84 項已完成；手機未安裝，GPU／檔案選取／實體機生命週期仍待驗證。這不是手機 LIVE_STREAM 重建或精度驗收。

**目前狀態（2026-11-06 遊戲內探索）：** 使用者切回站姿模式後，同一發送程序與一次校正連續執行合成探針、20 cm 放大診斷與原始 ZIP 三輪；使用者回報三輪正常，確認放大與原始 ZIP 都是角色自己的右腳，原始 ZIP 的抬起清楚可見。本次映射 1＝髖、3＝左腳、4＝右腳；日誌在測試期間未見先前的坐姿校正錯誤。依使用者評估，未達 20 cm 對本次**抬腳視覺可見性**列為低風險；原始踝點估計增量仍約 6.54 cm，不代表公尺精度已通過。此前坐姿錯誤／無動作的紀錄仍成立；本輪同時更換模式、重新啟動遊戲及保持發送不中斷，不能把成功單獨歸因於某一改變。詳見 [實驗紀錄](windows/TEST_RESULTS.md)。

即時 receiver 的 tracker 模式與第一階段安全保護已實作並通過自動測試；預設不送 OSC。可調整的重校正門檻初始為 250 ms，短暫保持時間另有限制。2026-11-06 本機手機即時測試首次確認 OSC Debugger 更新與 Avatar 動作；平滑、速度限制、失追後過渡、即時腳別／精度及遠端驗收仍待後續階段。

後續須量化公尺／角度精度、腳部 yaw／地面偏移、HMD 絕對對齊及失追／停止行為。可沿用 CPU IMAGE 比對設計隔離實驗，不例行重做左右方向或 Phase 0。VIDEO 不能用稀疏照片當成原始串流。獨立腳點真值、相機內參／俯仰與腳部深度仍缺少；後鏡頭與超廣角尚未實作，切換後須獨立驗證。需要更新 App 或真人配合前先語音通知。
