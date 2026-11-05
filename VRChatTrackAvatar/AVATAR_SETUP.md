# 官方 Robot Avatar 本機測試

目前 `Assets/VRChatTrackRobot.unity` 是從 VRChat SDK 3.10.6 的官方 Robot PC 範例另存的測試場景，六個參數及 Animator 資產位於 `Assets/VRChatTrackMVP`。先前的 Unity 骨骼測試及 SDK 本機 Build & Test 曾通過；VRChat 也曾回傳六個 OSC 參數，使用者確認手臂、彎膝與 WASD 共存。**目前重新執行 Unity smoke test 受 License Client IPC timeout 阻擋，未列為本次通過。** 手機到遊戲的六參數完整流程仍待實測。詳見 [測試紀錄](TEST_RESULTS.md)。

測試 Avatar 僅使用本機 Build & Test，不上傳或發布。此模式的 Avatar 僅對本機玩家可見，不能據此判斷遠端同步。

## 開啟及本機 Build & Test

1. 以 Unity 2022.3.22f1 開啟此專案，開啟 `Assets/VRChatTrackRobot.unity`；或選 `Tools > VRChat Track > Open Robot Test Scene`。
2. 在 `VRChat SDK > Show Control Panel` 自行登入 VRChat SDK。進入 Builder，確認選中場景中的 Robot Avatar。
3. 選擇 **Build & Test Your Avatar** 並執行 **Build & Test**。檢查 SDK 驗證訊息；不要選擇 Build & Publish。
4. 啟動 VRChat Desktop，進入場景，在 Avatar 清單的 **SDK Test Avatars** 選取並套用本機 Avatar。每次重新建置後需重新選取、套用，或自行使用 VRChat 的 `--watch-avatars` 啟動選項。
5. 開啟 VRChat 的 OSC；先依 `../windows/README.md` 使用單參數診斷，逐一觀察左右抬手、彎肘、彎膝，再使用手機及 receiver。記錄實際方向、動作與 WASD 同時操作結果。

## 目前的控制設計

- 六個 `Puppet/` Float 參數以 T 字站姿與手肘／膝蓋伸直為零點。雙臂的待機預設為 -1，即自然放下；手機 T 字校正完成仍輸出 0。正值抬高手臂或彎曲肘、膝；負的肘／膝值限制在伸直。
- 每一側手臂以同一個雙參數混合樹控制抬手與彎肘，避免一個 Humanoid 圖層覆蓋另一個；每一側膝蓋使用獨立圖層。曲線數值依官方 Robot 測試模型量測，不能直接假設適用其他 Avatar。
- Gesture 第一層的 Avatar Mask 只啟用雙臂。雙膝位於 SDK 官方 locomotion 控制器副本的獨立加算圖層，避免 Gesture 的腿部遮罩蓋住步態。
- 靜止時膝蓋圖層要求雙腳由 Animator 控制；`VelocityMagnitude > 0.10` 時進入 `Moving` 狀態、輸出零加算量並將腳部交回 Tracking，低於 0.07 時恢復姿勢。簡化 Unity PlayableGraph 已檢查移動狀態不改變底層腿部旋轉；使用者亦確認遊戲內走路及停下恢復彎膝正常。
- 六個姿勢參數的曲線不寫 Avatar Root；WASD 移動沿用 locomotion。六個單軸參數不等同完整 3D 追蹤。

## 重跑 Unity 測試

先關閉正在使用同一專案的 Unity Editor，再執行：

~~~powershell
& 'E:\UnityTools\Editors\2022.3.22f1\Editor\Unity.exe' -batchmode -nographics `
  -projectPath 'E:\10_DevCode\VRchat-track\VRChatTrackAvatar' `
  -executeMethod RobotMvpSmokeTest.Run -quit `
  -logFile 'E:\10_DevCode\VRchat-track\VRChatTrackAvatar\Logs\robot-mvp-smoke.log'
~~~

只有 log 實際包含 `VRCHAT_TRACK_SMOKE_TEST: PASS` 才算當次通過；目前 License Client IPC timeout 尚未排除。此測試重載場景，檢查參數、Animator 混合與骨骼角度、Root 不移動，以及以簡化 Unity PlayableGraph 驗證膝蓋狀態和底層動畫釋放；它不模擬 VRChat 的 IK、實際 Playable Layers、OSC 或鍵盤移動。

登入 VRChat SDK 後，也可在沒有其他 Unity Editor 開啟此專案時，以 CLI 執行本機測試建置：

~~~powershell
& 'E:\UnityTools\Editors\2022.3.22f1\Editor\Unity.exe' -batchmode `
  -projectPath 'E:\10_DevCode\VRchat-track\VRChatTrackAvatar' `
  -executeMethod RobotMvpBatchBuild.Run `
  -logFile 'E:\10_DevCode\VRchat-track\VRChatTrackAvatar\Logs\robot-mvp-build.log'
~~~

等待 Editor 結束，確認 log 含 `VRCHAT_TRACK_BATCH_BUILD: PASS`；登入未就緒時會逾時失敗。此方法只呼叫 SDK 的 `BuildAndTest`，不呼叫上傳 API。

`Tools > VRChat Track > Create Robot MVP Controls` 是給官方範例新場景使用的生成器。它會拒絕覆寫既有輸出或已自訂的 Avatar 設定；現有測試場景不需要重新執行它。

參考：[VRChat 本機 Avatar 測試](https://creators.vrchat.com/avatars/#local-avatar-testing)、[Playable Layers](https://creators.vrchat.com/avatars/playable-layers/)。
