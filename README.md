# VRChat Track：單手機姿勢追蹤

目標：一支 Android 手機辨識人體姿勢，經私人 Wi-Fi 傳到 Windows，再透過 VRChat 原生 OSC Trackers 與 FBT／IK 驅動**未修改的購買 Humanoid Avatar**，讓私人房間的其他玩家看見。現階段使用 AnyaDance 提供虛擬 HMD 與雙控制器；不修改 VRChat client 或 Avatar。

## 目前狀態（2026-11-06）

| 項目 | 結果 |
| --- | --- |
| VR 模式 Phase 0 | **通過**。AnyaDance 的 SteamVR trackers 停用後，合成 OSC 髖與雙腳完成校正；本機及遠端玩家都看到兩輪右腳抬起／放下。遠端玩家不知道切換時間與腳別。 |
| Phase 1 | OSC Vector3 encoder 與可指定髖／左右腳 ID 的 `TrackerOutput` 已完成本機 UDP 測試。 |
| 手機到 VRChat Tracker | **尚未接通**。前鏡頭離線複驗已確認修正後的左右腳與右轉方向。較早的同影格 2D／3D 右腳紀錄已離線重播，20 cm 箱面只估出 6.9–7.8 cm 踝點增量；後續含照片的新輪仍只估出約 5.1 cm，尺度驗證未通過。兩輪演算法未改、取樣不同，不能當作改善或退步。手機 OSC 保持停用；精度、長時間穩定性及 HMD 對齊仍待解決。 |
| 選用影像對照工具 | App **0.2.0** 的真手機擷取／ZIP 匯出與 Windows 匯入已確認；新 22 組影像完整拍到右腳上箱與放回。手機原始結果仍只上升約 **5.1 cm**，詳見 [影像調查](windows/IMAGE_PAIR_REVIEW_2026-11-06.md)。最新 Windows **95 項測試通過**；APK 建置／lint 通過。GPU delegate、保存負載與背景停止仍待實測。預設不保存影像、不啟用 OSC。 |
| 固定影像模型比對 | 同圖桌面 CPU IMAGE：Full 各自校正約 **16.2–16.3 cm**、共用手機校正約 **14.3 cm**，明顯高於原始約 5.1 cm；交叉替換定位到來源 3D 幾何差異。仍未達 20 cm，也不能當作 Android LIVE_STREAM 驗收；未更新手機或正式算法。詳見 [離線模型研究](windows/OFFLINE_MODEL_COMPARISON_2026-11-06.md)。 |
| Android 離線回放 | 獨立 Replay **0.1.0** 已建置／lint，最終 APK 無網路／相機等任何權限。同批 PNG 在唯讀模擬器 CPU IMAGE 的 Lite／Full 結果接近桌面；VIDEO 前站姿 0／5 有效、校正失敗，不能當有效高度比較。手機未安裝；[操作、84 項檢查與待驗證項目](android/REPLAY_GUIDE.md)。 |
| ZIP tracker 探索回放 | 「站姿 → 右腳上箱 → 放回」工具與 11 項新增檢查完成，真 ZIP 預覽不送 OSC。原始 Lite landmarks 不放大；預設固定站姿旋轉、只比較位置影響。等待使用者就位後才啟用有時限的 OSC 遊戲內測試；尚未驗收。手機 App 不變。[回放指南](windows/TRACKER_REPLAY_GUIDE.md)。 |
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
