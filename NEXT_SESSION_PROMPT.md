# 新對話交接 prompt

將下方整段貼到新的 Codex 對話：

~~~text
請接手 E:\10_DevCode\VRchat-track，僅使用 feat/osc-trackers。

先檢查 git status、目前 commit 與遠端狀態，保留既有變更。再讀：
1. README.md
2. OSC_TRACKER_MVP_PLAN.md
3. VIRTUAL_HMD_PHASE0_PLAN.md
4. windows/README.md
5. windows/TRACKER_PHASE0.md
6. windows/LIVE_TRACKER_SAFETY_PLAN.md
7. windows/TEST_RESULTS.md 最上方的最新紀錄

請使用 i-have-adhd 格式：先說下一步；用短句與編號；分清「已證實」與「待驗證」；最後給一個兩分鐘內可做的動作。技能檔：
C:\Users\user\.codex\plugins\cache\i-have-adhd\i-have-adhd\0.4.1\skills\i-have-adhd\SKILL.md

目標：一支 Android 手機的姿勢辨識，經 Windows 與 VRChat 原生 OSC Trackers／FBT，驅動未修改的購買 Humanoid Avatar，並讓私人房間其他玩家看見。

已證實：VR 模式 Phase 0 的合成 OSC tracker 本機與遠端盲測通過。AnyaDance 提供 HMD／雙控制器，並停用自身髖／雙腳 tracker。後續在站姿模式下，以同一程序連續測試合成、20 cm 放大、原始手機 ZIP 三輪：使用者確認三輪正常；後兩輪都是角色自己的右腳，原始 ZIP 的抬腳清楚可見。原始估計增量約 6.54 cm；依使用者評估，未達 20 cm 對這次抬腳視覺可見性列為低風險，不能宣稱公尺精度已達標。

當次 VRChat 映射是 1＝髖、3＝左腳、4＝右腳；上次曾相反，不能假設 3／4 固定。先前校正出現坐姿模式錯誤；之後成功輪同時切站姿、重啟遊戲／SteamVR 並保持同一發送程序，不能斷言唯一原因。Headset Window 保持 2560×1440；SteamVR -202 未修復，不重做已測顯示排查。Unity smoke test 仍受 License Client IPC timeout 阻擋，不能宣稱通過。

目前實作：手機即時 tracker 的低信心、失追與超時保護已完成；receiver 預設不送 OSC，明確 `--output trackers` 才輸出。六參數 Puppet 路線已移除；`tracker_replay.py --osc` 仍是原生 tracker 回放。失追重校正預設 250 ms，短暫保持預設 0；tracker 平滑、動作預測與失追後柔和過渡尚未實作。使用者觀察到失追後角色可能先站立再恢復動作，要求先分析「保留最後已校正姿勢並於恢復時平滑」的策略；需區分已實作與待驗證。

規則：
- 每次修改前先在 commentary 說明。程式變更後在 windows 執行 python -B -m unittest discover -v。
- 完成後 commit、push 到 origin/feat/osc-trackers，確認工作樹乾淨。
- 除非新變更確實需要，不重做已通過的 Phase 0、舊的長時間實機測試或 SteamVR 顯示診斷；程式變更仍須執行上列完整自動測試。
- 不修改或注入 VRChat client；不把原始／未校正手機資料送入 VRChat。
- 需要我更新手機 App 或配合實機前，先以語音通知並等待就位；若當輪我說不用語音則照辦。不要求我保持姿勢時打字。
- 區分已存 ZIP 回放和真正即時手機追蹤；本機即時 OSC Debugger 更新與角色動作已初驗，但遠端同步、腳別精度與 10 分鐘穩定性未通過。開始新一輪實機輸出前須確認本次 ID 映射。
~~~
