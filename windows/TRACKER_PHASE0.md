# Phase 0 — OSC Tracker 可行性實測

此測試不需要手機，也不修改 Avatar 或 VRChat client。它只驗證固定合成 tracker 能否被目前環境接收、校正、驅動 IK 並讓遠端玩家看到；**目前尚未完成任何 VRChat 實測，Phase 0 尚未通過**。

## 準備

- 電腦上的 VRChat、Python 3.12；VR 測試需要可正常使用的 HMD、控制器和 VR runtime。Desktop 測試使用同一台電腦的 Desktop 模式。請在舒適、安全的空間進行，站姿校正時避免撞到周圍物品。
- 一位遠端玩家，在同一個私人房間；使用正常、未為本專案修改的 Humanoid Avatar。紀錄 Avatar 名稱／是否為購買 Avatar；不需提供 Unity 原始檔。
- 在 VRChat 啟用 OSC，確認本機輸入 UDP 埠（預設 9000），並關閉其他 OSC tracker 發送程式及可能競爭的實體 tracker 輸入；記錄實際環境。不要同時執行本專案 receiver 的 OSC 輸出。
- 在 VRChat 將身高設定為實際身高，保留預設 playspace 或記錄偏移；校正時保持站直、面向前方。先開鏡子並在 Tracking & IK 中尋找 tracker 顯示設定。介面名稱會隨版本變更。

## 探針

在 PowerShell 執行（身高改為自己的公尺數，若 VRChat OSC 輸入埠不同，加 `--port 埠號`）：

```powershell
cd E:\10_DevCode\VRchat-track\windows
python -B tracker_probe.py --height 1.70 --calibration-seconds 90 --pose-seconds 15 --cycles 2
```

探針以 20 Hz 送到 `127.0.0.1:9000`。先固定站姿 90 秒供找 tracker 與校正；接著兩次循環，每次抬左腳 15 秒、站姿 15 秒。終端機會顯示階段；需要更多校正時間可調整 `--calibration-seconds`（1–600 秒），每次姿勢時間可調整 `--pose-seconds`（1–600 秒）。提前按 Ctrl+C 停止；停止後不再發送，VRChat 可能暫時保留最後一筆 tracker 資料，請觀察並記錄實際行為。

合成點使用 ID 1 髖、3 左腳、4 右腳，旋轉均為零；這些 ID 是探針自訂標記，**官方頁面沒有指定 ID 與人體部位的固定對應**。位置為左手系、公尺，使用身高比例估計；沒有傳送 head 對齊資訊。校正可能因座標原點、面向、Avatar 比例或其他追蹤來源而失敗；不可把單次對齊失敗直接當作 VRChat 不支援。若出現 tracker 但位置不符，記錄位置及可用的對齊方式，並先檢查身高與其他追蹤來源。官方的舊版 Auto-center 說明已標註過時，不保證目前介面存在該按鈕。參考 [VRChat OSC Trackers](https://docs.vrchat.com/docs/osc-trackers) 與 [FBT 校正](https://docs.vrchat.com/docs/full-body-tracking)。

## VR 模式與 Desktop 模式分別執行

1. 進入私人房間，請遠端玩家就位；開啟本機鏡子，確認 Avatar 與身高。先執行 VR 模式，再以 Desktop 重新啟動 VRChat、重新執行探針。若沒有 VR 環境，明確標記 VR「未測試」，不要將 Desktop 結果代替 VR 結果。
2. 在站姿階段觀察是否有三個 tracker 模型／球及其位置。若 VR 模式出現 FBT 校正功能，進入校正並依當前 VRChat 指示操作；官方目前的 FBT 說明要求站直面向前，雙控制器同時按互動鍵。記錄 Desktop 是否出現相同功能；若沒有可用校正功能，記錄「無法校正」，不聲稱成功。
3. 校正完成後，保持 HMD／控制器及身體大致不動。依終端機時間提示讓遠端玩家觀察並**在不知道目前階段時**說出左腳抬起或站姿；記錄每一階段是否正確及本機鏡子觀察。避免只以自身動作或既有動畫判斷。若姿勢沒有變化、左右相反或未配對，記下現象與 tracker 位置。
4. 用 Ctrl+C 或等待結束，記下停止後行為。若要重測，確認其他來源與 VRChat tracker 狀態，再重新執行並重新校正。UDP 本機送出成功不是 VRChat 收到、校正成功或遠端同步的證據。

## 結果紀錄（每次測試複製一份）

- 日期／VRChat 版本：
- 模式：VR / Desktop；HMD、控制器、VR runtime：
- Avatar／身高／輸入埠／其他追蹤來源或 playspace 偏移：
- 指令及實際執行時間：
- 本機是否看到 3 個 tracker、位置與朝向：
- 校正入口是否存在、步驟、是否完成：
- 本機站姿 → 左腳抬起 → 站姿的結果（含左右是否正確）：
- 遠端玩家盲測逐次回答及實際階段：
- 停止傳送後的行為／其他問題：
- 結論：通過 / 失敗 / 未完成；證據與待排除原因：

**Phase 0 通過**須在使用者實際可用的環境，以未修改的 Humanoid Avatar 成功校正，且遠端玩家能辨認探針造成的髖／腿姿勢改變。本機畫面、UDP 發送及自動化測試都不能取代遠端確認。VR 與 Desktop 分開記錄；Desktop 未完成或失敗不代表 VR 結果，反之亦然。未通過前不進入手機 tracker 輸出實作。
