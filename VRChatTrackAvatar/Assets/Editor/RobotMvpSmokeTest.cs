// Run manually with Unity -batchmode -executeMethod RobotMvpSmokeTest.Run.
using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.Animations;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Animations;
using UnityEngine.Playables;
using UnityEngine.SceneManagement;
using VRC.SDK3.Avatars.Components;
using VRC.SDK3.Avatars.ScriptableObjects;
using VRC.SDKBase;

internal static class RobotMvpSmokeTest
{
    private const string Sample = "Packages/com.vrchat.avatars/Samples/Dynamics/Robot Avatar/Avatar Dynamics Robot Avatar PC.unity";
    private const string ScenePath = "Assets/VRChatTrackRobot.unity";
    private const string OutputFolder = "Assets/VRChatTrackMVP";

    public static void Run()
    {
        try
        {
            var existing = File.Exists(ScenePath);
            if (!existing && AssetDatabase.IsValidFolder(OutputFolder))
                throw new InvalidOperationException("Generated assets already exist without a test scene; refusing to overwrite.");
            var scene = EditorSceneManager.OpenScene(existing ? ScenePath : Sample, OpenSceneMode.Single);
            if (!existing && !EditorSceneManager.SaveScene(scene, ScenePath))
                throw new InvalidOperationException("Could not save a separate test scene.");
            var avatars = scene.GetRootGameObjects()
                .SelectMany(root => root.GetComponentsInChildren<VRCAvatarDescriptor>(true)).ToArray();
            if (avatars.Length != 1)
                throw new InvalidOperationException("Expected one Robot Avatar in the sample scene.");
            var avatar = avatars[0];
            if (!existing)
            {
                Selection.activeGameObject = avatar.gameObject;
                if (!EditorApplication.ExecuteMenuItem("Tools/VRChat Track/Create Robot MVP Controls"))
                    throw new InvalidOperationException("Could not run the MVP setup menu item.");
                if (!AssetDatabase.IsValidFolder(OutputFolder))
                    throw new InvalidOperationException("The MVP setup did not generate its assets.");
                if (!EditorSceneManager.SaveScene(scene))
                    throw new InvalidOperationException("Could not save the test scene after setup.");
            }
            Validate(avatar);
            Debug.Log("VRCHAT_TRACK_SMOKE_TEST: PASS");
        }
        catch (Exception error)
        {
            Debug.LogError("VRCHAT_TRACK_SMOKE_TEST: FAIL " + error);
            EditorApplication.Exit(1);
        }
    }

    [MenuItem("Tools/VRChat Track/Open Robot Test Scene")]
    public static void OpenForTesting()
    {
        if (!Application.isBatchMode && !EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo())
            return;
        var scene = EditorSceneManager.OpenScene(ScenePath, OpenSceneMode.Single);
        var avatar = scene.GetRootGameObjects()
            .SelectMany(root => root.GetComponentsInChildren<VRCAvatarDescriptor>(true)).Single();
        Selection.activeGameObject = avatar.gameObject;
        EditorApplication.delayCall += () => EditorApplication.ExecuteMenuItem("VRChat SDK/Show Control Panel");
    }

    private static void Validate(VRCAvatarDescriptor avatar)
    {
        var names = new[] { "LeftArmRaise", "RightArmRaise", "LeftElbowFlex", "RightElbowFlex", "LeftKneeFlex", "RightKneeFlex" };
        var parameters = avatar.expressionParameters;
        if (parameters == null || names.Any(name => !parameters.parameters.Any(parameter =>
                parameter.name == "Puppet/" + name && parameter.valueType == VRCExpressionParameters.ValueType.Float)))
            throw new InvalidOperationException("Missing Float expression parameters.");
        var gesture = avatar.baseAnimationLayers.Single(layer => layer.type == VRCAvatarDescriptor.AnimLayerType.Gesture);
        var controller = gesture.animatorController as AnimatorController;
        if (gesture.isDefault || controller == null || controller.layers.Length != 3)
            throw new InvalidOperationException("Missing generated Gesture controller or layers.");
        var baseLayer = avatar.baseAnimationLayers.Single(layer => layer.type == VRCAvatarDescriptor.AnimLayerType.Base);
        var locomotion = baseLayer.animatorController as AnimatorController;
        if (baseLayer.isDefault || locomotion == null || locomotion.layers.Length != 3)
            throw new InvalidOperationException("Missing locomotion controller or knee layers.");
        var mask = controller.layers[0].avatarMask;
        var enabledParts = new[] { AvatarMaskBodyPart.LeftArm, AvatarMaskBodyPart.RightArm };
        if (mask == null || Enumerable.Range(0, (int)AvatarMaskBodyPart.LastBodyPart)
                .Any(i => mask.GetHumanoidBodyPartActive((AvatarMaskBodyPart)i) != enabledParts.Contains((AvatarMaskBodyPart)i)))
            throw new InvalidOperationException("Gesture's first layer must mask only the arms.");
        foreach (var side in new[] { "Left", "Right" })
        {
            var layer = locomotion.layers.Single(item => item.name == side + "KneeFlex");
            if (layer.blendingMode != AnimatorLayerBlendingMode.Additive)
                throw new InvalidOperationException(side + " knee layer must be additive.");
            foreach (var stateName in new[] { "Tracked", "Moving" })
            {
                var state = layer.stateMachine.states.Single(item => item.state.name == stateName).state;
                var behavior = state.behaviours.OfType<VRCAnimatorTrackingControl>().Single();
                var actual = side == "Left" ? behavior.trackingLeftFoot : behavior.trackingRightFoot;
                var expected = stateName == "Tracked" ? VRC_AnimatorTrackingControl.TrackingType.Animation
                    : VRC_AnimatorTrackingControl.TrackingType.Tracking;
                if (actual != expected) throw new InvalidOperationException(side + " foot tracking is incorrect in " + stateName);
            }
        }

        var bones = new[] { HumanBodyBones.LeftUpperArm, HumanBodyBones.RightUpperArm,
            HumanBodyBones.LeftLowerArm, HumanBodyBones.RightLowerArm,
            HumanBodyBones.LeftLowerLeg, HumanBodyBones.RightLowerLeg };
        if (parameters.parameters.Length != names.Length || parameters.parameters.Any(parameter => !parameter.networkSynced || parameter.saved))
            throw new InvalidOperationException("Expected six unsaved, network-synced parameters.");
        foreach (var name in names)
        {
            var expected = name.EndsWith("ArmRaise", StringComparison.Ordinal) ? -1f : 0f;
            var expression = parameters.parameters.Single(parameter => parameter.name == "Puppet/" + name);
            var animatorParameter = controller.parameters.Single(parameter => parameter.name == "Puppet/" + name);
            if (Math.Abs(expression.defaultValue - expected) > 0.001f || Math.Abs(animatorParameter.defaultFloat - expected) > 0.001f)
                throw new InvalidOperationException("Unexpected idle default for " + name);
        }
        ValidateAnimator(avatar, locomotion, controller, names, bones);
    }

    // Exercise the actual controller, including masks and simultaneously active layers.
    // This cannot simulate VRChat's playable layers, tracking or locomotion.
    private static void ValidateAnimator(VRCAvatarDescriptor avatar, AnimatorController locomotion, AnimatorController controller,
        string[] names, HumanBodyBones[] bones)
    {
        var allZero = Evaluate(avatar, locomotion, controller, names, bones, -1, false);
        var idle = Evaluate(avatar, locomotion, controller, names, bones, -1, false, 1f, true);
        if (idle.Angles[0] > 25f || idle.Angles[1] > 25f)
            throw new InvalidOperationException("Idle arms are not lowered near the torso.");
        Debug.Log(string.Format("VRCHAT_TRACK_IDLE_TEST left={0:F1} right={1:F1}", idle.Angles[0], idle.Angles[1]));
        var combined = Evaluate(avatar, locomotion, controller, names, bones, -1, true);
        var errors = new System.Collections.Generic.List<string>();
        for (var i = 0; i < names.Length; i++)
        {
            var individual = Evaluate(avatar, locomotion, controller, names, bones, i, false);
            var delta = Quaternion.Angle(allZero.Rotations[i], individual.Rotations[i]);
            var combinationError = Quaternion.Angle(individual.Rotations[i], combined.Rotations[i]);
            Debug.Log(string.Format("VRCHAT_TRACK_ANIMATOR_TEST {0} rotation={1:F1} neutralAngle={2:F1} activeAngle={3:F1} combinedError={4:F1}",
                names[i], delta, allZero.Angles[i], individual.Angles[i], combinationError));
            if (delta < 1f)
                errors.Add("Animator parameter did not move expected bone: " + names[i]);
            if (combinationError > 1f)
                errors.Add("Animator layers interfere on " + names[i]);
            if (i < 2 && (allZero.Angles[i] < 80f || allZero.Angles[i] > 100f || individual.Angles[i] < allZero.Angles[i] + 25f))
                errors.Add("Arm is not near T-pose at zero or fails to raise: " + names[i]);
            if (i >= 2 && (allZero.Angles[i] < 160f || individual.Angles[i] > allZero.Angles[i] - 45f))
                errors.Add("Elbow or knee is not straight at zero or fails to bend: " + names[i]);
            var negative = Evaluate(avatar, locomotion, controller, names, bones, i, false, -1f);
            if (i < 2 && negative.Angles[i] > allZero.Angles[i] - 35f)
                errors.Add("Arm fails to lower with a negative input: " + names[i]);
            if (i >= 2 && Math.Abs(negative.Angles[i] - allZero.Angles[i]) > 2f)
                errors.Add("Negative flex should clamp at straight: " + names[i]);
            for (var j = 0; j < names.Length; j++)
            {
                if (j != i && Quaternion.Angle(allZero.Rotations[j], individual.Rotations[j]) > 1f)
                    errors.Add(names[i] + " unexpectedly moved the local rotation of " + names[j]);
            }
        }
        ValidateKneeTransitions(avatar, locomotion);
        ValidateWalkingRelease(avatar, locomotion, controller);
        if (errors.Count != 0)
            throw new InvalidOperationException(string.Join("; ", errors));
    }

    private sealed class Evaluation
    {
        public Quaternion[] Rotations;
        public float[] Angles;
    }

    private static Evaluation Evaluate(VRCAvatarDescriptor avatar, AnimatorController locomotion, AnimatorController controller,
        string[] names, HumanBodyBones[] bones, int active, bool allActive, float value = 1f, bool useDefaults = false)
    {
        var clone = UnityEngine.Object.Instantiate(avatar.gameObject);
        var graph = PlayableGraph.Create("VRChat Track smoke test");
        try
        {
            var animator = clone.GetComponent<Animator>();
            animator.runtimeAnimatorController = null;
            // Batch mode has no visible renderer; otherwise Unity can cull bone updates.
            animator.cullingMode = AnimatorCullingMode.AlwaysAnimate;
            graph.SetTimeUpdateMode(DirectorUpdateMode.Manual);
            var basePlayable = AnimatorControllerPlayable.Create(graph, locomotion);
            var gesturePlayable = AnimatorControllerPlayable.Create(graph, controller);
            var mixer = AnimationLayerMixerPlayable.Create(graph, 2);
            mixer.ConnectInput(0, basePlayable, 0, 1f);
            mixer.ConnectInput(1, gesturePlayable, 0, 1f);
            mixer.SetLayerMaskFromAvatarMask(1, controller.layers[0].avatarMask);
            var output = AnimationPlayableOutput.Create(graph, "Animation", animator);
            output.SetSourcePlayable(mixer);
            basePlayable.SetBool("Grounded", true);
            basePlayable.SetFloat("Upright", 1f);
            graph.Play();
            graph.Evaluate(0.1f);
            var rootPosition = clone.transform.position;
            var rootRotation = clone.transform.rotation;
            for (var i = 0; i < names.Length && !useDefaults; i++)
            {
                var parameter = "Puppet/" + names[i];
                var current = allActive || i == active ? value : 0f;
                if (i < 4) gesturePlayable.SetFloat(parameter, current);
                else basePlayable.SetFloat(parameter, current);
            }
            graph.Evaluate(0.1f);
            if (Vector3.Distance(rootPosition, clone.transform.position) > 0.0001f ||
                Quaternion.Angle(rootRotation, clone.transform.rotation) > 0.01f)
                throw new InvalidOperationException("Animator unexpectedly moved the avatar root.");
            var rotations = bones.Select(bone => animator.GetBoneTransform(bone).localRotation).ToArray();
            var angles = Enumerable.Range(0, names.Length).Select(i => AngleForJoint(animator, i)).ToArray();
            return new Evaluation { Rotations = rotations, Angles = angles };
        }
        finally
        {
            graph.Destroy();
            UnityEngine.Object.DestroyImmediate(clone);
        }
    }

    private static void ValidateWalkingRelease(VRCAvatarDescriptor avatar, AnimatorController locomotion,
        AnimatorController gesture)
    {
        var clone = UnityEngine.Object.Instantiate(avatar.gameObject);
        var graph = PlayableGraph.Create("VRChat Track walking release");
        try
        {
            var animator = clone.GetComponent<Animator>();
            animator.runtimeAnimatorController = null;
            animator.cullingMode = AnimatorCullingMode.AlwaysAnimate;
            graph.SetTimeUpdateMode(DirectorUpdateMode.Manual);
            var basePlayable = AnimatorControllerPlayable.Create(graph, locomotion);
            var gesturePlayable = AnimatorControllerPlayable.Create(graph, gesture);
            var mixer = AnimationLayerMixerPlayable.Create(graph, 2);
            mixer.ConnectInput(0, basePlayable, 0, 1f);
            mixer.ConnectInput(1, gesturePlayable, 0, 1f);
            mixer.SetLayerMaskFromAvatarMask(1, gesture.layers[0].avatarMask);
            var output = AnimationPlayableOutput.Create(graph, "Animation", animator);
            output.SetSourcePlayable(mixer);
            basePlayable.SetBool("Grounded", true);
            basePlayable.SetFloat("Upright", 1f);
            graph.Play();
            graph.Evaluate(0.1f);
            basePlayable.SetFloat("Puppet/LeftKneeFlex", 1f);
            basePlayable.SetFloat("Puppet/RightKneeFlex", 1f);
            graph.Evaluate(0.1f);
            basePlayable.SetFloat("VelocityMagnitude", 1f);
            basePlayable.SetFloat("VelocityZ", 1f);
            graph.Evaluate(0.5f);
            var indices = new[] { Array.FindIndex(locomotion.layers, layer => layer.name == "LeftKneeFlex"),
                Array.FindIndex(locomotion.layers, layer => layer.name == "RightKneeFlex") };
            if (indices.Any(index => index < 0 || !basePlayable.GetCurrentAnimatorStateInfo(index).IsName("Moving")))
                throw new InvalidOperationException("Knees did not enter Moving in the playable graph.");
            var bones = new[] { HumanBodyBones.LeftLowerLeg, HumanBodyBones.RightLowerLeg }
                .Select(animator.GetBoneTransform).ToArray();
            var withKnees = bones.Select(bone => bone.localRotation).ToArray();
            foreach (var index in indices) basePlayable.SetLayerWeight(index, 0f);
            graph.Evaluate(0f);
            for (var i = 0; i < bones.Length; i++)
                if (Quaternion.Angle(withKnees[i], bones[i].localRotation) > 1f)
                    throw new InvalidOperationException("Moving knee layer still overrides locomotion: " + i);
            Debug.Log("VRCHAT_TRACK_WALKING_RELEASE: PASS (Unity playable graph only)");
        }
        finally
        {
            graph.Destroy();
            UnityEngine.Object.DestroyImmediate(clone);
        }
    }

    private static void ValidateKneeTransitions(VRCAvatarDescriptor avatar, AnimatorController controller)
    {
        var clone = UnityEngine.Object.Instantiate(avatar.gameObject);
        try
        {
            var animator = clone.GetComponent<Animator>();
            animator.runtimeAnimatorController = controller;
            animator.cullingMode = AnimatorCullingMode.AlwaysAnimate;
            animator.Rebind();
            animator.Update(0.1f);
            var kneeLayers = new[] { animator.GetLayerIndex("LeftKneeFlex"), animator.GetLayerIndex("RightKneeFlex") };
            if (kneeLayers.Any(index => index < 0 || !animator.GetCurrentAnimatorStateInfo(index).IsName("Tracked")))
                throw new InvalidOperationException("Knees did not start in Tracked state.");
            animator.SetFloat("VelocityMagnitude", 1f);
            animator.Update(0.1f);
            if (kneeLayers.Any(index => !animator.GetCurrentAnimatorStateInfo(index).IsName("Moving")))
                throw new InvalidOperationException("Knees did not switch to Moving state.");
            animator.SetFloat("VelocityMagnitude", 0f);
            animator.Update(0.1f);
            if (kneeLayers.Any(index => !animator.GetCurrentAnimatorStateInfo(index).IsName("Tracked")))
                throw new InvalidOperationException("Knees did not return to Tracked state.");
            Debug.Log("VRCHAT_TRACK_KNEE_TRANSITIONS: PASS (Unity state transitions only)");
        }
        finally
        {
            UnityEngine.Object.DestroyImmediate(clone);
        }
    }

    private static float AngleForJoint(Animator animator, int i)
    {
        var triples = new[] {
            new[] { HumanBodyBones.LeftLowerArm, HumanBodyBones.LeftUpperArm, HumanBodyBones.LeftUpperLeg },
            new[] { HumanBodyBones.RightLowerArm, HumanBodyBones.RightUpperArm, HumanBodyBones.RightUpperLeg },
            new[] { HumanBodyBones.LeftUpperArm, HumanBodyBones.LeftLowerArm, HumanBodyBones.LeftHand },
            new[] { HumanBodyBones.RightUpperArm, HumanBodyBones.RightLowerArm, HumanBodyBones.RightHand },
            new[] { HumanBodyBones.LeftUpperLeg, HumanBodyBones.LeftLowerLeg, HumanBodyBones.LeftFoot },
            new[] { HumanBodyBones.RightUpperLeg, HumanBodyBones.RightLowerLeg, HumanBodyBones.RightFoot },
        };
        var parts = triples[i];
        var a = animator.GetBoneTransform(parts[0]).position;
        var b = animator.GetBoneTransform(parts[1]).position;
        var c = animator.GetBoneTransform(parts[2]).position;
        return Vector3.Angle(a - b, c - b);
    }
}
