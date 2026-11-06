# 目前狀態（2026-11-07）

各項目「已證實 / 待驗證」的單一來源。詳細數據與實驗見 [docs/logs/](logs/)。

| 項目 | 結果 |
| --- | --- |
| VR 模式 Phase 0 | **通過**。AnyaDance 的 SteamVR trackers 停用後，合成 OSC 髖與雙腳完成校正；本機及遠端玩家都看到兩輪右腳抬起／放下。遠端玩家不知道切換時間與腳別。 |
| Phase 1 | OSC Vector3 encoder、`TrackerOutput` 與 receiver 的安全 tracker 模式已完成隔離 UDP／自動測試；預設不送 OSC。2026-11-06 本機手機即時測試已看到 VRChat 角色動作，詳見 [測試紀錄](logs/windows-tests.md)。 |
| 即時 tracker 失追與恢復 | 已實作 350 ms 判定失追、保留校正、最多重送最後已校正姿勢 8 秒，可信姿勢恢復時以 300 ms 過渡；超時停止輸出並要求手動重校正。新 session、突變及輸出錯誤仍清除校正；正常追蹤不使用持續濾波。自動測試與限制見 [失追測試紀錄](logs/2026-11-07-tracker-recovery.md)。VRChat 中的凍結、恢復觀感、停止效果及門檻仍待實測。 |
| 手機到 VRChat Tracker | **本機即時鏈路已首次接通**：手機姿勢經 Windows 轉為 OSC，VRChat 記錄三個活動 tracker；使用者確認 OSC Debugger 更新且角色跟著動作。起初全身未入鏡，校正前 `osc_updates=0`；重新入鏡後校正與輸出正常。已存 ZIP 回放另在本機看到右腳抬起。前鏡頭離線複驗已確認左右腳與右轉方向；較早的 20 cm 箱面資料只估出 6.9–7.8 cm，後續含照片輪約 5.1 cm，尺度仍未驗證。即時動作的腳別、公尺精度、HMD 對齊、遠端效果與長時間穩定性待驗證。 |
| 選用影像對照工具 | App **0.2.0** 的真手機擷取／ZIP 匯出與 Windows 匯入已確認；新 22 組影像完整拍到右腳上箱與放回。手機原始結果仍只上升約 **5.1 cm**，詳見 [影像調查](logs/2026-11-06-image-pair-review.md)。APK 建置／lint 通過。GPU delegate、保存負載與背景停止仍待實測。預設不保存影像、不啟用 OSC。 |
| 固定影像模型比對 | 同圖桌面 CPU IMAGE：Full 各自校正約 **16.2–16.3 cm**、共用手機校正約 **14.3 cm**，明顯高於原始約 5.1 cm；交叉替換定位到來源 3D 幾何差異。仍未達 20 cm，也不能當作 Android LIVE_STREAM 驗收；未更新手機或正式算法。詳見 [離線模型研究](logs/2026-11-06-offline-model-comparison.md)。 |
| Android 離線回放 | 獨立 Replay **0.1.0** 已建置／lint，最終 APK 無網路／相機等任何權限。同批 PNG 在唯讀模擬器 CPU IMAGE 的 Lite／Full 結果接近桌面；VIDEO 前站姿 0／5 有效、校正失敗，不能當有效高度比較。手機未安裝；[操作、84 項檢查與待驗證項目](../android/REPLAY_GUIDE.md)。 |
| ZIP tracker 探索回放 | 2026-11-06 站姿模式下，以同一連續發送器完成合成探針、20 cm 放大版與原始 ZIP 三輪；使用者回報三輪正常，確認後兩輪均為角色自己的右腳，原始 ZIP 動作清楚可見。依使用者評估，未達 20 cm 對**本次抬腳視覺可見性**列為低風險；公尺精度、即時追蹤與遠端效果仍待驗證。此前坐姿校正錯誤及無動作的結果仍保留，原因未單獨證明。手機 App 不變；[實驗紀錄](logs/windows-tests.md)。 |
| SteamVR `-202` | 仍在。VRChat 的 VR 畫面與選單可用；AnyaDance 的桌面顯示路徑是待驗證的可能原因。Headset Window 保持 **2560×1440**。診斷見 [reference/steamvr-202.md](../reference/steamvr-202.md)。 |
| 其他 | 純 Desktop 的原生 FBT 未通過；長時間穩定性與手機姿勢的遠端同步未驗證。Unity smoke test 受 License Client IPC timeout 阻擋。 |

Phase 0 的遠端驗收仍只證實**合成 OSC tracker**；新手機即時結果目前僅有本機觀察。VRChat 曾把 tracker 3 映射為右腳，之後須以當次校正結果設定左右 ID。

舊六參數 Puppet／Robot 路線已從現行程式與操作文件移除。`pose_receiver.py` 的 OSC 輸出只透過 `--output trackers` 啟用；`tracker_replay.py --osc` 仍是另一個原生 tracker 回放指令。移除前檔案可在 Git commit `36061e1` 查閱；歷史測試紀錄保留為證據。
