# Phase 0：合成 OSC Tracker 驗收

**結果（2026-11-05）：虛擬 HMD 的 VR 模式已通過。** AnyaDance 自帶 SteamVR trackers 停用後，本探針的 OSC 髖與雙腳完成 FBT 校正；本機鏡子與不知切換時間／腳別的遠端玩家都看到兩輪右腳抬起、放下。這只驗證合成 tracker；後續已存手機姿勢回放在本機可見，即時手機姿勢仍待接入。純 Desktop 只看到 OSC Debug 封包，未完成 FBT。

詳細的 VRChat 日誌映射與時間見 [Phase 0 證據](../docs/logs/2026-11-05-phase0.md)。**已通過的實機驗收不需例行重做。** 以下指令供迴歸或新環境重現。

## 準備

1. 讓 VRChat 進入有 HMD 與雙控制器的 VR 模式；在 AnyaDance 環境確認 `driver_anyadance.enable_trackers=false`，避免其 SteamVR 髖／腳與 OSC 競爭。
2. 啟用 VRChat OSC，確認本機輸入埠（預設 UDP 9000）；停止其他 OSC tracker 發送程式。使用未修改的 Humanoid Avatar，設定實際身高，開啟鏡子。
3. 若做遠端驗收，請另一位玩家進入同一私人房間，先不要告知切換時間或哪隻腳會動。

頭與雙手由虛擬 HMD／控制器提供，探針只需送髖及雙腳三點。[VRChat OSC Trackers](https://docs.vrchat.com/docs/osc-trackers)。

## 手動探針

在 `windows` 目錄執行，將身高換成自己的公尺數；若 OSC 輸入埠不同，加 `--port`：

~~~powershell
python -B tracker_probe.py --height 1.67 --interactive --max-seconds 600
~~~

探針以 20 Hz 向 `127.0.0.1:9000` 持續送站姿。待 VRChat 顯示三個 OSC tracker 後，使用快速選單的 **Calibrate FBT**；AnyaDance 焦點視窗中同時按 `Z`＋`X` 完成校正。確認當次 `OSCTracker1/3/4` 對應髖及雙腳，再在探針終端機逐行輸入：

~~~text
raise
stand
raise
stand
quit
~~~

`raise` 只升高 **tracker 3**；VRChat 可能把它校正為左腳或右腳，不能從 ID 推斷腳別。`quit` 或 Ctrl+C 停止發送，`--max-seconds` 也會自動停止。切換 Avatar 後須重新確認校正映射。記下本機鏡子與遠端玩家的原樣回答；UDP 封包送出本身不是 VRChat 接收或遠端同步的證據。

## 驗收紀錄

只需記錄日期、VRChat／Avatar、身高、是否停用其他 tracker、校正映射、探針命令與時間、本機鏡子觀察、遠端玩家在盲測中說出的姿勢順序。遇到左右反轉、校正失敗或失追時，記下現象與當時的映射，不把單次失敗推論成 OSC FBT 不支援。
