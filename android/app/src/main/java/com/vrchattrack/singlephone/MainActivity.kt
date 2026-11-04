package com.vrchattrack.singlephone

import android.Manifest
import android.annotation.SuppressLint
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Log
import android.view.WindowManager
import android.view.inputmethod.InputMethodManager
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import com.google.mediapipe.tasks.core.Delegate
import java.util.Locale
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import kotlin.math.abs
import kotlin.math.ceil

class MainActivity : AppCompatActivity() {
    private data class PhaseSamples(
        val timings: MutableList<ProcessingTiming> = mutableListOf(),
        var noPoseCount: Int = 0,
    )

    private data class BenchmarkRun(
        val cpu: PhaseSamples = PhaseSamples(),
        val gpu: PhaseSamples = PhaseSamples(),
        var phase: Delegate = Delegate.CPU,
        var phaseStartMs: Long = 0L,
    ) {
        fun currentSamples(): PhaseSamples = if (phase == Delegate.CPU) cpu else gpu
    }

    private lateinit var previewView: PreviewView
    private lateinit var overlayView: PoseOverlayView
    private lateinit var statusView: TextView
    private lateinit var timingView: TextView
    private lateinit var benchmarkView: TextView
    private lateinit var networkStatusView: TextView
    private lateinit var receiverHostView: EditText
    private lateinit var receiverPortView: EditText
    private lateinit var networkButton: Button
    private lateinit var retryButton: Button
    private lateinit var switchButton: Button
    private lateinit var benchmarkButton: Button
    private lateinit var analysisExecutor: ExecutorService
    private val mainHandler = Handler(Looper.getMainLooper())
    private var cameraProvider: ProcessCameraProvider? = null
    private var imageAnalysis: ImageAnalysis? = null
    // Creation, use and close all occur on the same analysis executor, as GPU requires.
    private var poseLandmarker: PoseLandmarkerEngine? = null
    private var requestedDelegate = Delegate.GPU
    private var activeDelegate = Delegate.GPU
    @Volatile private var pipelineGeneration = 0
    @Volatile private var lanSender: LanPoseSender? = null
    private var pipelineStarting = false
    private var benchmark: BenchmarkRun? = null
    private var resultWindowStartedAtMs = 0L
    private var resultsInWindow = 0
    private var resultFps = 0f

    private val cameraPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            if (granted) {
                startPosePipeline()
            } else {
                abortBenchmark("未取得相機權限，無法比較。")
                statusView.text = getString(R.string.camera_permission_denied)
                pipelineStarting = false
                updateControls()
            }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        setContentView(R.layout.activity_main)
        analysisExecutor = Executors.newSingleThreadExecutor()

        previewView = findViewById(R.id.camera_preview)
        previewView.scaleType = PreviewView.ScaleType.FILL_CENTER
        overlayView = findViewById(R.id.pose_overlay)
        statusView = findViewById(R.id.status_text)
        timingView = findViewById(R.id.timing_text)
        benchmarkView = findViewById(R.id.benchmark_text)
        networkStatusView = findViewById(R.id.network_status)
        receiverHostView = findViewById(R.id.receiver_host)
        receiverPortView = findViewById(R.id.receiver_port)
        networkButton = findViewById(R.id.network_button)
        retryButton = findViewById(R.id.retry_button)
        switchButton = findViewById(R.id.switch_delegate_button)
        benchmarkButton = findViewById(R.id.benchmark_button)

        retryButton.setOnClickListener { checkCameraPermissionAndStart() }
        switchButton.setOnClickListener {
            requestedDelegate = if (activeDelegate == Delegate.CPU) Delegate.GPU else Delegate.CPU
            checkCameraPermissionAndStart()
        }
        benchmarkButton.setOnClickListener { beginBenchmark() }
        val preferences = getSharedPreferences(LAN_PREFERENCES, MODE_PRIVATE)
        val prefilledHost = intent.getStringExtra(EXTRA_RECEIVER_HOST)
        receiverHostView.setText(prefilledHost ?: preferences.getString("host", ""))
        receiverPortView.setText(
            intent.getIntExtra(EXTRA_RECEIVER_PORT, preferences.getInt("port", DEFAULT_PORT)).toString(),
        )
        networkButton.setOnClickListener {
            if (lanSender == null) startLanSender() else stopLanSender()
        }
        if (prefilledHost != null) {
            // Prefill only; the user or an explicit test action must press the button.
            networkButton.isFocusableInTouchMode = true
            networkButton.requestFocus()
        }

        if (intent.getBooleanExtra(EXTRA_BENCHMARK, false)) {
            beginBenchmark()
        } else {
            checkCameraPermissionAndStart()
        }
    }

    private fun beginBenchmark() {
        benchmark = BenchmarkRun()
        requestedDelegate = Delegate.CPU
        benchmarkView.text = "準備比較 CPU 與 GPU，請維持相同站位並讓全身入鏡。"
        updateControls()
        checkCameraPermissionAndStart()
    }

    private fun checkCameraPermissionAndStart() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) ==
            PackageManager.PERMISSION_GRANTED
        ) {
            startPosePipeline()
        } else {
            statusView.text = getString(R.string.camera_permission_required)
            cameraPermissionLauncher.launch(Manifest.permission.CAMERA)
        }
    }

    private fun startPosePipeline() {
        val generation = ++pipelineGeneration
        val requested = requestedDelegate
        pipelineStarting = true
        updateControls()
        resultWindowStartedAtMs = 0L
        resultsInWindow = 0
        resultFps = 0f
        statusView.text = getString(R.string.pose_initializing)
        timingView.text = getString(R.string.timing_waiting)
        overlayView.clear()
        imageAnalysis?.clearAnalyzer()
        cameraProvider?.unbindAll()

        val listener = object : PoseLandmarkerEngine.Listener {
            override fun onPoseFrame(frame: PoseFrame) {
                if (generation == pipelineGeneration) lanSender?.offer(frame)
                runOnUiThread {
                    if (generation == pipelineGeneration && !isFinishing && !isDestroyed) {
                        renderPoseFrame(frame)
                    }
                }
            }

            override fun onError(message: String) {
                runOnUiThread {
                    if (generation == pipelineGeneration && !isFinishing && !isDestroyed) {
                        handlePipelineError(message)
                    }
                }
            }
        }

        analysisExecutor.execute {
            try {
                poseLandmarker?.close()
                poseLandmarker = null
                var fallbackNotice: String? = null
                val engine = try {
                    PoseLandmarkerEngine(applicationContext, listener, requested)
                } catch (error: Exception) {
                    if (requested != Delegate.GPU) throw error
                    Log.e(TAG, "GPU initialization failed; falling back to CPU", error)
                    fallbackNotice = "GPU 初始化失敗，已切回 CPU。"
                    PoseLandmarkerEngine(applicationContext, listener, Delegate.CPU)
                }
                poseLandmarker = engine
                runOnUiThread {
                    if (generation == pipelineGeneration && !isFinishing && !isDestroyed) {
                        activeDelegate = engine.delegate
                        requestedDelegate = engine.delegate
                        fallbackNotice?.let { notice ->
                            abortBenchmark(notice)
                            benchmarkView.text = notice
                        }
                        updateSwitchLabel()
                        statusView.text = getString(R.string.pose_model_ready)
                        startCameraPreview(generation)
                    }
                }
            } catch (error: Exception) {
                Log.e(TAG, "Pose pipeline initialization failed", error)
                runOnUiThread {
                    if (generation == pipelineGeneration && !isFinishing && !isDestroyed) {
                        abortBenchmark("辨識初始化失敗：${error.javaClass.simpleName}")
                        pipelineStarting = false
                        statusView.text =
                            getString(R.string.pose_init_error_prefix) + error.javaClass.simpleName
                        updateControls()
                    }
                }
            }
        }
    }

    @SuppressLint("UnsafeOptInUsageError")
    private fun startCameraPreview(generation: Int) {
        statusView.text = getString(R.string.camera_starting)
        val cameraProviderFuture = ProcessCameraProvider.getInstance(this)
        cameraProviderFuture.addListener(
            {
                if (generation != pipelineGeneration || isFinishing || isDestroyed) {
                    return@addListener
                }
                try {
                    cameraProvider = cameraProviderFuture.get()
                    val preview = Preview.Builder().build().also { useCase ->
                        useCase.surfaceProvider = previewView.surfaceProvider
                    }
                    imageAnalysis =
                        ImageAnalysis.Builder()
                            .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                            .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_RGBA_8888)
                            .build()
                            .also { analyzer ->
                                analyzer.setAnalyzer(analysisExecutor) { imageProxy ->
                                    val engine = poseLandmarker
                                    if (engine == null) imageProxy.close()
                                    else engine.analyze(imageProxy, isFrontCamera = true)
                                }
                            }

                    cameraProvider?.unbindAll()
                    cameraProvider?.bindToLifecycle(
                        this,
                        CameraSelector.DEFAULT_FRONT_CAMERA,
                        preview,
                        imageAnalysis,
                    )
                    pipelineStarting = false
                    updateControls()
                    statusView.text = getString(R.string.camera_ready)
                    scheduleBenchmarkPhase(generation)
                } catch (exception: Exception) {
                    Log.e(TAG, "Camera initialization failed", exception)
                    abortBenchmark("相機啟動失敗：${exception.javaClass.simpleName}")
                    pipelineStarting = false
                    statusView.text =
                        getString(R.string.camera_error_prefix) + exception.javaClass.simpleName
                    updateControls()
                }
            },
            ContextCompat.getMainExecutor(this),
        )
    }

    private fun renderPoseFrame(frame: PoseFrame) {
        overlayView.setPoseFrame(frame)
        val now = SystemClock.uptimeMillis()
        if (resultWindowStartedAtMs == 0L) resultWindowStartedAtMs = now
        resultsInWindow += 1
        val elapsedMs = now - resultWindowStartedAtMs
        if (elapsedMs >= FPS_WINDOW_MS) {
            resultFps = resultsInWindow * 1_000f / elapsedMs
            resultWindowStartedAtMs = now
            resultsInWindow = 0
        }
        val quality = when {
            !frame.poseDetected -> getString(R.string.pose_no_person)
            frame.keyLandmarksWithConfidence == 0 -> getString(R.string.pose_confidence_unavailable)
            else -> getString(
                R.string.pose_confidence_summary,
                frame.keyLandmarksAboveThreshold,
                frame.keyLandmarksWithConfidence,
            )
        }
        statusView.text = getString(
            R.string.pose_status,
            frame.landmarks.size,
            frame.worldLandmarks.size,
            frame.inferenceMs,
            resultFps,
            quality,
        )
        val timing = frame.timing
        timingView.text = if (timing != null) {
            getString(
                R.string.timing_status,
                frame.delegate.toString(),
                timing.prepareMs,
                timing.taskMs,
                timing.extractMs,
                timing.totalMs,
            )
        } else {
            getString(R.string.timing_waiting)
        }
        recordBenchmarkFrame(frame, now)
    }

    private fun scheduleBenchmarkPhase(generation: Int) {
        val run = benchmark ?: return
        if (activeDelegate != run.phase) {
            abortBenchmark("測試模式與執行模式不一致，請重新比較。")
            updateControls()
            return
        }
        run.phaseStartMs = SystemClock.uptimeMillis()
        benchmarkView.text = "${run.phase} 預熱中，請讓全身保持入鏡。"
        mainHandler.postDelayed(
            {
                if (benchmark === run && generation == pipelineGeneration && !isDestroyed) {
                    finishBenchmarkPhase(run)
                }
            },
            BENCHMARK_PHASE_MS,
        )
    }

    private fun recordBenchmarkFrame(frame: PoseFrame, now: Long) {
        val run = benchmark ?: return
        if (run.phaseStartMs == 0L || frame.delegate != run.phase) return
        val elapsed = now - run.phaseStartMs
        if (elapsed < BENCHMARK_WARMUP_MS || elapsed >= BENCHMARK_PHASE_MS) return
        val samples = run.currentSamples()
        if (frame.poseDetected && frame.timing != null) {
            samples.timings.add(frame.timing)
        } else if (!frame.poseDetected) {
            samples.noPoseCount += 1
        }
        val remainingSeconds = ((BENCHMARK_PHASE_MS - elapsed + 999L) / 1_000L).coerceAtLeast(0L)
        benchmarkView.text =
            "${run.phase} 量測中，剩餘 ${remainingSeconds} 秒，人體樣本 ${samples.timings.size} 筆。"
    }

    private fun finishBenchmarkPhase(run: BenchmarkRun) {
        val samples = run.currentSamples()
        logBenchmarkSummary(run.phase, samples)
        if (run.phase == Delegate.CPU) {
            run.phase = Delegate.GPU
            run.phaseStartMs = 0L
            requestedDelegate = Delegate.GPU
            benchmarkView.text = formatSummary(Delegate.CPU, run.cpu) + "\n正在切換 GPU…"
            startPosePipeline()
        } else {
            benchmarkView.text = formatComparison(run)
            benchmark = null
            updateControls()
        }
    }

    private fun handlePipelineError(message: String) {
        Log.e(TAG, "Pose pipeline error on $activeDelegate: $message")
        overlayView.clear()
        if (activeDelegate == Delegate.GPU) {
            val notice = "GPU 執行失敗，已切回 CPU：$message"
            abortBenchmark(notice)
            benchmarkView.text = notice
            requestedDelegate = Delegate.CPU
            startPosePipeline()
        } else {
            abortBenchmark("辨識失敗：$message")
            statusView.text = getString(R.string.pose_error_prefix) + message
            pipelineStarting = false
            updateControls()
        }
    }

    private fun abortBenchmark(message: String) {
        if (benchmark != null) {
            Log.w(TAG, "BENCHMARK_ABORT $message")
            benchmark = null
            benchmarkView.text = message
        }
    }

    private fun formatSummary(delegate: Delegate, phase: PhaseSamples): String {
        val values = phase.timings
        if (values.isEmpty()) {
            return "$delegate：沒有有效人體樣本（未偵測 ${phase.noPoseCount} 次）。"
        }
        return String.format(
            Locale.US,
            "%s n=%d：合計 p50 %.1f / p95 %.1f ms\n準備 %.1f｜MediaPipe %.1f｜擷取 %.1f ms（各項中位數）",
            delegate,
            values.size,
            percentile(values.map { it.totalMs }, 0.50),
            percentile(values.map { it.totalMs }, 0.95),
            percentile(values.map { it.prepareMs }, 0.50),
            percentile(values.map { it.taskMs }, 0.50),
            percentile(values.map { it.extractMs }, 0.50),
        )
    }

    private fun formatComparison(run: BenchmarkRun): String {
        val cpu = run.cpu.timings
        val gpu = run.gpu.timings
        val detail = formatSummary(Delegate.CPU, run.cpu) + "\n" + formatSummary(Delegate.GPU, run.gpu)
        if (cpu.isEmpty() || gpu.isEmpty()) return detail + "\n樣本不足，請全身入鏡後重新比較。"
        val cpuMedian = percentile(cpu.map { it.totalMs }, 0.50)
        val gpuMedian = percentile(gpu.map { it.totalMs }, 0.50)
        val difference = gpuMedian - cpuMedian
        val direction = if (difference < 0.0) "快" else "慢"
        val percent = if (cpuMedian > 0.0) abs(difference) * 100.0 / cpuMedian else 0.0
        val conclusion = if (abs(difference) < 0.05) {
            "GPU 與 CPU 的合計中位數相同。"
        } else {
            String.format(Locale.US, "GPU 較 CPU %s %.1f ms（%.1f%%，合計中位數）。", direction, abs(difference), percent)
        }
        val sampleNote = if (cpu.size < MIN_RELIABLE_SAMPLES || gpu.size < MIN_RELIABLE_SAMPLES) {
            "\n人體樣本較少，結果僅供參考。"
        } else ""
        return detail + "\n" + conclusion + sampleNote
    }

    private fun logBenchmarkSummary(delegate: Delegate, phase: PhaseSamples) {
        val values = phase.timings
        if (values.isEmpty()) {
            Log.i(TAG, "BENCHMARK delegate=$delegate samples=0 noPose=${phase.noPoseCount}")
            return
        }
        Log.i(
            TAG,
            String.format(
                Locale.US,
                "BENCHMARK delegate=%s samples=%d noPose=%d prepP50=%.2f taskP50=%.2f extractP50=%.2f totalP50=%.2f totalP95=%.2f",
                delegate, values.size, phase.noPoseCount,
                percentile(values.map { it.prepareMs }, 0.50),
                percentile(values.map { it.taskMs }, 0.50),
                percentile(values.map { it.extractMs }, 0.50),
                percentile(values.map { it.totalMs }, 0.50),
                percentile(values.map { it.totalMs }, 0.95),
            ),
        )
    }

    private fun percentile(values: List<Double>, fraction: Double): Double {
        val sorted = values.sorted()
        val index = (ceil(fraction * sorted.size).toInt() - 1).coerceIn(0, sorted.lastIndex)
        return sorted[index]
    }

    private fun updateSwitchLabel() {
        switchButton.text = getString(
            if (activeDelegate == Delegate.CPU) R.string.switch_to_gpu else R.string.switch_to_cpu,
        )
    }

    private fun updateControls() {
        val enabled = !pipelineStarting && benchmark == null
        retryButton.isEnabled = enabled
        switchButton.isEnabled = enabled
        benchmarkButton.isEnabled = enabled
    }

    private fun startLanSender() {
        val host = receiverHostView.text.toString().trim()
        val port = receiverPortView.text.toString().toIntOrNull()
        try {
            LanPoseSender.privateIpv4(host)
            require(port != null && port in 1..65535) { "UDP 埠號必須介於 1–65535" }
        } catch (error: IllegalArgumentException) {
            networkStatusView.text = "Wi-Fi 傳輸：${error.message}"
            return
        }
        val validPort = requireNotNull(port)
        getSharedPreferences(LAN_PREFERENCES, MODE_PRIVATE).edit()
            .putString("host", host)
            .putInt("port", validPort)
            .apply()
        (getSystemService(INPUT_METHOD_SERVICE) as InputMethodManager)
            .hideSoftInputFromWindow(receiverHostView.windowToken, 0)
        lateinit var sender: LanPoseSender
        val listener = object : LanPoseSender.Listener {
            override fun onStatus(status: LanStatus) {
                runOnUiThread {
                    if (lanSender === sender && !isFinishing && !isDestroyed) {
                        val state = if (status.hasRecentAck) "收到 ACK" else "等待 ACK"
                        val p50 = status.rttP50Ms?.let { String.format(Locale.US, "%.1f", it) } ?: "--"
                        val p95 = status.rttP95Ms?.let { String.format(Locale.US, "%.1f", it) } ?: "--"
                        networkStatusView.text = getString(
                            R.string.network_status, state, status.sent, status.acknowledged,
                            p50, p95, status.overwritten, status.expired, status.lastBytes,
                        )
                    }
                }
            }

            override fun onError(message: String) {
                runOnUiThread {
                    if (lanSender === sender && !isFinishing && !isDestroyed) {
                        stopLanSender()
                        networkStatusView.text = "Wi-Fi 傳輸錯誤：$message"
                    }
                }
            }
        }
        sender = LanPoseSender(applicationContext, host, validPort, listener)
        lanSender = sender
        receiverHostView.isEnabled = false
        receiverPortView.isEnabled = false
        networkButton.text = getString(R.string.network_stop)
        networkStatusView.text = getString(R.string.network_waiting)
        sender.start()
    }

    private fun stopLanSender() {
        val sender = lanSender
        lanSender = null
        sender?.close()
        receiverHostView.isEnabled = true
        receiverPortView.isEnabled = true
        networkButton.text = getString(R.string.network_start)
        networkStatusView.text = getString(R.string.network_stopped)
    }

    override fun onStop() {
        stopLanSender()
        super.onStop()
    }

    override fun onDestroy() {
        pipelineGeneration += 1
        mainHandler.removeCallbacksAndMessages(null)
        cameraProvider?.unbindAll()
        imageAnalysis?.clearAnalyzer()
        analysisExecutor.execute {
            poseLandmarker?.close()
            poseLandmarker = null
        }
        analysisExecutor.shutdown()
        super.onDestroy()
    }

    private companion object {
        const val TAG = "PoseBenchmark"
        const val EXTRA_BENCHMARK = "benchmark"
        const val EXTRA_RECEIVER_HOST = "receiver_host"
        const val EXTRA_RECEIVER_PORT = "receiver_port"
        const val LAN_PREFERENCES = "lan_receiver"
        const val DEFAULT_PORT = 8765
        const val FPS_WINDOW_MS = 1_000L
        const val BENCHMARK_WARMUP_MS = 3_000L
        const val BENCHMARK_PHASE_MS = 23_000L
        const val MIN_RELIABLE_SAMPLES = 10
    }
}
