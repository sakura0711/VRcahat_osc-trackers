// Editor-only helper for the VRChat SDK Robot Avatar. Experimental until tested in VRChat.
using System;
using System.Linq;
using UnityEditor;
using UnityEditor.Animations;
using UnityEditor.SceneManagement;
using UnityEngine;
using VRC.SDK3.Avatars.Components;
using VRC.SDK3.Avatars.ScriptableObjects;
using VRC.SDKBase;

internal static class RobotMvpSetup
{
    private const string OutputFolder = "Assets/VRChatTrackMVP";
    private const string LocomotionSample = "Packages/com.vrchat.avatars/Samples/AV3 Demo Assets/Animation/Controllers/vrc_AvatarV3LocomotionLayer.controller";

    private sealed class Joint
    {
        public readonly string Name;
        public readonly string Muscle;
        public readonly AvatarMaskBodyPart BodyPart;

        public Joint(string name, string muscle, AvatarMaskBodyPart bodyPart)
        {
            Name = name;
            Muscle = muscle;
            BodyPart = bodyPart;
        }
    }

    private static readonly Joint[] Joints =
    {
        new Joint("LeftArmRaise", "Left Arm Down-Up", AvatarMaskBodyPart.LeftArm),
        new Joint("RightArmRaise", "Right Arm Down-Up", AvatarMaskBodyPart.RightArm),
        new Joint("LeftElbowFlex", "Left Forearm Stretch", AvatarMaskBodyPart.LeftArm),
        new Joint("RightElbowFlex", "Right Forearm Stretch", AvatarMaskBodyPart.RightArm),
        new Joint("LeftKneeFlex", "Left Lower Leg Stretch", AvatarMaskBodyPart.LeftLeg),
        new Joint("RightKneeFlex", "Right Lower Leg Stretch", AvatarMaskBodyPart.RightLeg),
    };

    [MenuItem("Tools/VRChat Track/Create Robot MVP Controls")]
    private static void CreateControls()
    {
        var selected = Selection.activeGameObject;
        var avatar = selected == null ? null : selected.GetComponent<VRCAvatarDescriptor>();
        var animator = selected == null ? null : selected.GetComponent<Animator>();
        if (avatar == null || animator == null || !animator.isHuman)
        {
            Fail("Select the Robot Avatar root with a humanoid Animator and VRCAvatarDescriptor.");
            return;
        }
        if (!selected.scene.IsValid() || !selected.scene.path.StartsWith("Assets/", StringComparison.Ordinal))
        {
            Fail("First save the SDK sample scene as a new scene in Assets, then select its Robot Avatar root.");
            return;
        }
        if (AssetDatabase.IsValidFolder(OutputFolder) || avatar.expressionParameters != null || avatar.customExpressions)
        {
            Fail("This helper only supports a fresh sample avatar. Existing output or expression settings will not be overwritten.");
            return;
        }
        var layers = avatar.baseAnimationLayers;
        var gestureIndex = Array.FindIndex(layers, layer => layer.type == VRCAvatarDescriptor.AnimLayerType.Gesture);
        var locomotionIndex = Array.FindIndex(layers, layer => layer.type == VRCAvatarDescriptor.AnimLayerType.Base);
        if (gestureIndex < 0 || (!layers[gestureIndex].isDefault && layers[gestureIndex].animatorController != null))
        {
            Fail("No untouched Gesture layer was found. Existing avatar controllers will not be overwritten.");
            return;
        }
        if (locomotionIndex < 0 || (!layers[locomotionIndex].isDefault && layers[locomotionIndex].animatorController != null))
        {
            Fail("No untouched Base layer was found. Existing avatar controllers will not be overwritten.");
            return;
        }
        var missingMuscles = Joints.Where(joint => !HumanTrait.MuscleName.Contains(joint.Muscle)).Select(joint => joint.Muscle).ToArray();
        if (missingMuscles.Length != 0)
        {
            Fail("Missing humanoid muscles: " + string.Join(", ", missingMuscles));
            return;
        }

        AssetDatabase.CreateFolder("Assets", "VRChatTrackMVP");
        var expressionParameters = ScriptableObject.CreateInstance<VRCExpressionParameters>();
        expressionParameters.parameters = Joints.Select(joint => new VRCExpressionParameters.Parameter
        {
            name = "Puppet/" + joint.Name,
            valueType = VRCExpressionParameters.ValueType.Float,
            defaultValue = IdleDefault(joint),
            saved = false,
            networkSynced = true,
            bitWidth = 8,
        }).ToArray();
        AssetDatabase.CreateAsset(expressionParameters, OutputFolder + "/Parameters.asset");
        var menu = ScriptableObject.CreateInstance<VRCExpressionsMenu>();
        AssetDatabase.CreateAsset(menu, OutputFolder + "/Menu.asset");

        var controller = AnimatorController.CreateAnimatorControllerAtPath(OutputFolder + "/Gesture.controller");
        controller.AddParameter("VelocityMagnitude", AnimatorControllerParameterType.Float);
        foreach (var joint in Joints)
            controller.AddParameter(new AnimatorControllerParameter
            {
                name = "Puppet/" + joint.Name,
                type = AnimatorControllerParameterType.Float,
                defaultFloat = IdleDefault(joint),
            });

        // Desktop IK normally controls hands and arms. Let the Animator drive them.
        var baseLayer = controller.layers[0];
        // VRChat uses the first Gesture layer's mask for the playable layer.
        var gestureMask = new AvatarMask();
        for (var part = 0; part < (int)AvatarMaskBodyPart.LastBodyPart; part++)
            gestureMask.SetHumanoidBodyPartActive((AvatarMaskBodyPart)part, false);
        foreach (var part in new[] { AvatarMaskBodyPart.LeftArm, AvatarMaskBodyPart.RightArm })
            gestureMask.SetHumanoidBodyPartActive(part, true);
        AssetDatabase.CreateAsset(gestureMask, OutputFolder + "/Gesture.mask");
        baseLayer.avatarMask = gestureMask;
        var controllerLayers = controller.layers;
        controllerLayers[0] = baseLayer;
        controller.layers = controllerLayers;
        var setupState = baseLayer.stateMachine.AddState("Tracking Setup");
        setupState.writeDefaultValues = false;
        var tracking = setupState.AddStateMachineBehaviour<VRCAnimatorTrackingControl>();
        tracking.trackingLeftHand = VRC_AnimatorTrackingControl.TrackingType.Animation;
        tracking.trackingRightHand = VRC_AnimatorTrackingControl.TrackingType.Animation;

        // Humanoid clips override an entire masked arm, even when only one muscle
        // is keyed. Combine shoulder and elbow into one layer per arm.
        AddArmLayer(controller, Joints[0], Joints[2]);
        AddArmLayer(controller, Joints[1], Joints[3]);
        CreateLocomotionController();
        ConfigureAdditiveKnees();
        var locomotionController = AssetDatabase.LoadAssetAtPath<AnimatorController>(OutputFolder + "/Locomotion.controller");

        Undo.RecordObject(avatar, "Configure VRChat Track Robot MVP");
        avatar.customExpressions = true;
        avatar.expressionParameters = expressionParameters;
        avatar.expressionsMenu = menu;
        avatar.customizeAnimationLayers = true;
        var gesture = layers[gestureIndex];
        gesture.isDefault = false;
        gesture.animatorController = controller;
        layers[gestureIndex] = gesture;
        var locomotion = layers[locomotionIndex];
        locomotion.isDefault = false;
        locomotion.animatorController = locomotionController;
        layers[locomotionIndex] = locomotion;
        avatar.baseAnimationLayers = layers;
        EditorUtility.SetDirty(avatar);
        EditorSceneManager.MarkSceneDirty(selected.scene);
        AssetDatabase.SaveAssets();
        const string done = "Generated experimental controls. Save the scene, then use Build & Test to check all directions and WASD.";
        if (Application.isBatchMode)
            Debug.Log("VRChat Track: " + done);
        else
            EditorUtility.DisplayDialog("VRChat Track", done, "OK");
    }

    private static void Fail(string message)
    {
        if (Application.isBatchMode)
            throw new InvalidOperationException(message);
        EditorUtility.DisplayDialog("VRChat Track", message, "OK");
    }

    private static AnimatorStateMachine AddLayer(AnimatorController controller, string name, AvatarMaskBodyPart bodyPart)
    {
        var maskPath = OutputFolder + "/" + name + ".mask";
        var mask = AssetDatabase.LoadAssetAtPath<AvatarMask>(maskPath);
        if (mask == null)
        {
            mask = new AvatarMask();
            for (var part = 0; part < (int)AvatarMaskBodyPart.LastBodyPart; part++)
                mask.SetHumanoidBodyPartActive((AvatarMaskBodyPart)part, false);
            mask.SetHumanoidBodyPartActive(bodyPart, true);
            AssetDatabase.CreateAsset(mask, maskPath);
        }

        var stateMachine = new AnimatorStateMachine { name = name };
        AssetDatabase.AddObjectToAsset(stateMachine, controller);
        var layer = new AnimatorControllerLayer
        {
            name = name,
            defaultWeight = 1,
            blendingMode = AnimatorLayerBlendingMode.Override,
            avatarMask = mask,
            stateMachine = stateMachine,
        };
        controller.AddLayer(layer);
        return stateMachine;
    }

    private static string Suffix(float value)
    {
        return value < 0 ? "Minus" : value > 0 ? "Plus" : "Neutral";
    }

    private static BlendTree CreateTree(AnimatorController controller, string name, string parameter)
    {
        var tree = new BlendTree
        {
            name = name,
            blendType = BlendTreeType.Simple1D,
            blendParameter = "Puppet/" + parameter,
            useAutomaticThresholds = false,
        };
        AssetDatabase.AddObjectToAsset(tree, controller);
        return tree;
    }

    private static void SetMuscle(AnimationClip clip, Joint joint, float value)
    {
        var curve = AnimationCurve.Constant(0, 1f / 30f, value);
        AnimationUtility.SetEditorCurve(clip, EditorCurveBinding.FloatCurve("", typeof(Animator), joint.Muscle), curve);
    }

    // These values were measured on the official Robot humanoid: zero corresponds
    // approximately to a T-pose with straight elbows and knees. A positive flex
    // is approximately 90 degrees; a negative flex clamps at straight.
    private static float ArmMuscle(float raise) { return raise < 0 ? -1f : raise > 0 ? 1f : 0.31f; }
    private static float FlexMuscle(float flex) { return flex > 0 ? -0.1f : 1f; }
    private static float IdleDefault(Joint joint) { return joint.Name.EndsWith("ArmRaise", StringComparison.Ordinal) ? -1f : 0f; }

    private static void AddArmLayer(AnimatorController controller, Joint shoulder, Joint elbow)
    {
        var stateMachine = AddLayer(controller, shoulder.Name, shoulder.BodyPart);
        var raiseTree = CreateTree(controller, shoulder.Name + " Blend", shoulder.Name);
        foreach (var raise in new[] { -1f, 0f, 1f })
        {
            var elbowTree = CreateTree(controller, shoulder.Name + " " + Suffix(raise) + " Elbow", elbow.Name);
            foreach (var flex in new[] { -1f, 0f, 1f })
            {
                var clip = new AnimationClip { frameRate = 30 };
                SetMuscle(clip, shoulder, ArmMuscle(raise));
                SetMuscle(clip, elbow, FlexMuscle(flex));
                var name = shoulder.Name + Suffix(raise) + "_" + elbow.Name + Suffix(flex);
                clip.name = name;
                AssetDatabase.CreateAsset(clip, OutputFolder + "/" + name + ".anim");
                elbowTree.AddChild(clip, flex);
            }
            raiseTree.AddChild(elbowTree, raise);
        }
        var tracked = stateMachine.AddState("Tracked");
        tracked.motion = raiseTree;
        tracked.writeDefaultValues = false;
    }

    private static void AddKneeLayer(AnimatorController controller, Joint joint)
    {
        var stateMachine = AddLayer(controller, joint.Name, joint.BodyPart);
        var tree = CreateTree(controller, joint.Name + " Blend", joint.Name);
        foreach (var threshold in new[] { -1f, 0f, 1f })
        {
            var clipPath = OutputFolder + "/" + joint.Name + Suffix(threshold) + ".anim";
            var clip = AssetDatabase.LoadAssetAtPath<AnimationClip>(clipPath);
            if (clip == null)
            {
                clip = new AnimationClip { name = joint.Name + " " + threshold, frameRate = 30 };
                SetMuscle(clip, joint, FlexMuscle(threshold));
                AssetDatabase.CreateAsset(clip, clipPath);
            }
            tree.AddChild(clip, threshold);
        }
        var tracked = stateMachine.AddState("Tracked");
        tracked.motion = tree;
        tracked.writeDefaultValues = false;
        SetFootTracking(tracked, joint.BodyPart, VRC_AnimatorTrackingControl.TrackingType.Animation);
        // Give walking animations their knees back while keyboard locomotion is active.
        var moving = stateMachine.AddState("Moving");
        moving.writeDefaultValues = false;
        SetFootTracking(moving, joint.BodyPart, VRC_AnimatorTrackingControl.TrackingType.Tracking);
        var startMoving = tracked.AddTransition(moving);
        startMoving.hasExitTime = false;
        startMoving.hasFixedDuration = true;
        startMoving.duration = 0;
        startMoving.AddCondition(AnimatorConditionMode.Greater, 0.10f, "VelocityMagnitude");
        var stopMoving = moving.AddTransition(tracked);
        stopMoving.hasExitTime = false;
        stopMoving.hasFixedDuration = true;
        stopMoving.duration = 0;
        stopMoving.AddCondition(AnimatorConditionMode.Less, 0.07f, "VelocityMagnitude");
    }

    internal static void SetFootTracking(AnimatorState state, AvatarMaskBodyPart bodyPart,
        VRC_AnimatorTrackingControl.TrackingType mode)
    {
        var control = state.behaviours.OfType<VRCAnimatorTrackingControl>().FirstOrDefault()
            ?? state.AddStateMachineBehaviour<VRCAnimatorTrackingControl>();
        if (bodyPart == AvatarMaskBodyPart.LeftLeg)
            control.trackingLeftFoot = mode;
        else if (bodyPart == AvatarMaskBodyPart.RightLeg)
            control.trackingRightFoot = mode;
        else
            throw new ArgumentException("Foot tracking requires a left or right leg.", nameof(bodyPart));
        EditorUtility.SetDirty(control);
    }

    private static void CreateLocomotionController()
    {
        var path = OutputFolder + "/Locomotion.controller";
        if (AssetDatabase.LoadAssetAtPath<AnimatorController>(path) != null)
            throw new InvalidOperationException("Locomotion controller already exists; refusing to overwrite.");
        if (!AssetDatabase.CopyAsset(LocomotionSample, path))
            throw new InvalidOperationException("Could not copy the SDK locomotion controller.");
        var controller = AssetDatabase.LoadAssetAtPath<AnimatorController>(path);
        controller.AddParameter("VelocityMagnitude", AnimatorControllerParameterType.Float);
        controller.AddParameter("Puppet/LeftKneeFlex", AnimatorControllerParameterType.Float);
        controller.AddParameter("Puppet/RightKneeFlex", AnimatorControllerParameterType.Float);
        AddKneeLayer(controller, Joints[4]);
        AddKneeLayer(controller, Joints[5]);
        EditorUtility.SetDirty(controller);
        AssetDatabase.SaveAssets();
        Debug.Log("VRCHAT_TRACK_LOCOMOTION_CONTROLLER: CREATED");
    }

    private static void ConfigureAdditiveKnees()
    {
        var controller = AssetDatabase.LoadAssetAtPath<AnimatorController>(OutputFolder + "/Locomotion.controller");
        if (controller == null) throw new InvalidOperationException("Locomotion controller is missing.");
        var layers = controller.layers;
        foreach (var joint in new[] { Joints[4], Joints[5] })
        {
            var index = Array.FindIndex(layers, layer => layer.name == joint.Name);
            if (index < 0) throw new InvalidOperationException("Knee layer is missing: " + joint.Name);
            var neutralPath = OutputFolder + "/" + joint.Name + "AddNeutral.anim";
            var plusPath = OutputFolder + "/" + joint.Name + "AddPlus.anim";
            var neutral = AssetDatabase.LoadAssetAtPath<AnimationClip>(neutralPath);
            if (neutral == null)
            {
                neutral = new AnimationClip { name = joint.Name + " Add Neutral", frameRate = 30 };
                SetMuscle(neutral, joint, 1f);
                AssetDatabase.CreateAsset(neutral, neutralPath);
            }
            var plus = AssetDatabase.LoadAssetAtPath<AnimationClip>(plusPath);
            if (plus == null)
            {
                plus = new AnimationClip { name = joint.Name + " Add Plus", frameRate = 30 };
                SetMuscle(plus, joint, -0.1f);
                AssetDatabase.CreateAsset(plus, plusPath);
            }
            AnimationUtility.SetAdditiveReferencePose(neutral, neutral, 0f);
            AnimationUtility.SetAdditiveReferencePose(plus, neutral, 0f);
            EditorUtility.SetDirty(neutral);
            EditorUtility.SetDirty(plus);
            var tracked = layers[index].stateMachine.states.Single(item => item.state.name == "Tracked").state;
            var moving = layers[index].stateMachine.states.Single(item => item.state.name == "Moving").state;
            var tree = tracked.motion as BlendTree;
            if (tree == null) throw new InvalidOperationException("Missing knee blend tree: " + joint.Name);
            var children = tree.children;
            for (var i = 0; i < children.Length; i++)
                children[i].motion = children[i].threshold > 0 ? plus : neutral;
            tree.children = children;
            moving.motion = neutral;
            layers[index].blendingMode = AnimatorLayerBlendingMode.Additive;
            EditorUtility.SetDirty(tree);
            EditorUtility.SetDirty(moving);
        }
        controller.layers = layers;
        EditorUtility.SetDirty(controller);
        AssetDatabase.SaveAssets();
        Debug.Log("VRCHAT_TRACK_ADDITIVE_KNEES: CONFIGURED");
    }

    // Update the already-generated Robot assets to the same defaults as new ones.
    public static void UpdateExistingIdleDefaults()
    {
        var expressions = AssetDatabase.LoadAssetAtPath<VRCExpressionParameters>(OutputFolder + "/Parameters.asset");
        var controller = AssetDatabase.LoadAssetAtPath<AnimatorController>(OutputFolder + "/Gesture.controller");
        if (expressions == null || expressions.parameters == null || controller == null)
            throw new InvalidOperationException("Generated parameters or Gesture controller is missing.");
        var animatorParameters = controller.parameters;
        foreach (var joint in Joints)
        {
            var name = "Puppet/" + joint.Name;
            var expression = expressions.parameters.Single(parameter => parameter.name == name);
            var animatorParameter = animatorParameters.Single(parameter => parameter.name == name);
            expression.defaultValue = IdleDefault(joint);
            animatorParameter.defaultFloat = IdleDefault(joint);
        }
        controller.parameters = animatorParameters;
        EditorUtility.SetDirty(expressions);
        EditorUtility.SetDirty(controller);
        AssetDatabase.SaveAssets();
        Debug.Log("VRCHAT_TRACK_IDLE_DEFAULTS: PASS");
    }
}
