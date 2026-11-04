// Optional non-interactive local Build & Test. It never invokes an upload API.
using System;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using VRC.Core;
using VRC.SDK3.Avatars.Components;
using VRC.SDK3A.Editor;

internal static class RobotMvpBatchBuild
{
    private static GameObject target;
    private static double deadline;

    public static void Run()
    {
        if (!Application.isBatchMode)
            throw new InvalidOperationException("Use this entry point only in Unity batch mode.");
        try
        {
            var scene = EditorSceneManager.OpenScene("Assets/VRChatTrackRobot.unity");
            target = scene.GetRootGameObjects()
                .SelectMany(root => root.GetComponentsInChildren<VRCAvatarDescriptor>(true)).Single().gameObject;
            deadline = EditorApplication.timeSinceStartup + 90;
            EditorApplication.ExecuteMenuItem("VRChat SDK/Show Control Panel");
            EditorApplication.update += WaitForSdk;
        }
        catch (Exception error)
        {
            Fail(error);
        }
    }

    private static async void WaitForSdk()
    {
        if (EditorApplication.timeSinceStartup > deadline)
        {
            EditorApplication.update -= WaitForSdk;
            Fail(new TimeoutException("SDK panel or login did not become ready."));
            return;
        }
        if (!APIUser.IsLoggedIn || VRCSdkControlPanel.window == null) return;
        if (!VRCSdkControlPanel.TryGetBuilder<IVRCSdkAvatarBuilderApi>(out var builder)) return;
        EditorApplication.update -= WaitForSdk;
        try
        {
            Debug.Log("VRCHAT_TRACK_BATCH_BUILD: STARTING local BuildAndTest");
            await builder.BuildAndTest(target);
            Debug.Log("VRCHAT_TRACK_BATCH_BUILD: PASS");
            EditorApplication.Exit(0);
        }
        catch (Exception error)
        {
            Fail(error);
        }
    }

    private static void Fail(Exception error)
    {
        Debug.LogError("VRCHAT_TRACK_BATCH_BUILD: FAIL " + error);
        EditorApplication.Exit(1);
    }
}
