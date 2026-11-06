package com.vrchattrack.replay

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.view.WindowManager
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Spinner
import android.widget.TextView
import java.io.ByteArrayOutputStream
import java.io.File
import java.util.UUID
import java.util.concurrent.Executors

/** Separate application: no camera, LAN sender or live tracking classes. */
@Suppress("DEPRECATION")
class ReplayActivity : Activity() {
    private val worker = Executors.newSingleThreadExecutor()
    private val gate = ReplayGate()
    @Volatile private var source: ReplaySource? = null
    @Volatile private var reportFile: File? = null
    @Volatile private var uiGeneration = -1L
    private lateinit var status: TextView
    private lateinit var importButton: Button
    private lateinit var runButton: Button
    private lateinit var stopButton: Button
    private lateinit var exportButton: Button
    private lateinit var mode: Spinner
    private lateinit var delegate: Spinner

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        check(packageManager.checkPermission(Manifest.permission.INTERNET, packageName) == PackageManager.PERMISSION_DENIED)
        check(packageManager.checkPermission(Manifest.permission.CAMERA, packageName) == PackageManager.PERMISSION_DENIED)
        val padding = (20 * resources.displayMetrics.density).toInt()
        val column = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(padding, padding, padding, padding)
            fitsSystemWindows = true
        }
        fun label(value: String) = TextView(this).apply { text = value; textSize = 17f; column.addView(this) }
        label("固定影像離線回放")
        label("匯入已保存的 ZIP，比較同圖 Lite／Full。此 App 無網路及相機權限，不送 OSC。")
        label("每 3 秒一張的照片不能重建原本的連續串流；結果只供離線診斷。")
        importButton = Button(this).apply {
            text = "1. 匯入影像對照 ZIP"
            setOnClickListener { startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                type = "application/zip"; addCategory(Intent.CATEGORY_OPENABLE)
            }, IMPORT) }
            column.addView(this)
        }
        label("推論方式")
        mode = Spinner(this).apply {
            adapter = ArrayAdapter(this@ReplayActivity, android.R.layout.simple_spinner_dropdown_item, listOf("IMAGE（獨立單張）", "VIDEO（依原影格順序）"))
            column.addView(this)
        }
        label("處理模式；GPU 失敗不會自動換成 CPU")
        delegate = Spinner(this).apply {
            adapter = ArrayAdapter(this@ReplayActivity, android.R.layout.simple_spinner_dropdown_item, listOf("CPU", "GPU"))
            column.addView(this)
        }
        runButton = Button(this).apply { text = "2. 比較 Lite／Full"; setOnClickListener { compare() }; column.addView(this) }
        stopButton = Button(this).apply {
            text = "停止本輪"
            setOnClickListener { gate.cancel(); uiGeneration = -1; status.text = "正在停止；本輪不發布結果。"; refresh() }
            column.addView(this)
        }
        exportButton = Button(this).apply {
            text = "3. 匯出完成的回放結果 JSON"
            setOnClickListener { startActivityForResult(Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
                type = "application/json"; addCategory(Intent.CATEGORY_OPENABLE)
                putExtra(Intent.EXTRA_TITLE, "android-pose-replay.json")
            }, EXPORT) }
            column.addView(this)
        }
        status = label("請先匯入 ZIP。尚未開始推論。")
        setContentView(ScrollView(this).apply { addView(column) })
        refresh()
    }

    private fun refresh() {
        if (!::status.isInitialized || isDestroyed) return
        val busy = gate.busy()
        importButton.isEnabled = !busy
        runButton.isEnabled = !busy && source != null
        exportButton.isEnabled = !busy && reportFile != null
        stopButton.isEnabled = busy
        mode.isEnabled = !busy
        delegate.isEnabled = !busy
        if (busy) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }

    private fun ui(ticket: ReplayGate.Ticket, action: () -> Unit) = runOnUiThread {
        if (!isDestroyed && uiGeneration == ticket.generation) action()
    }

    private fun work(action: (ReplayGate.Ticket) -> Unit) {
        if (gate.busy()) return
        val ticket = gate.begin()
        uiGeneration = ticket.generation
        refresh()
        worker.execute {
            try { action(ticket)
            } catch (_: ReplayCancelled) { ui(ticket) { status.text = "已停止；未發布本輪結果。" }
            } catch (problem: Exception) {
                ui(ticket) { status.text = "未完成：${problem.javaClass.simpleName}。請保留原 ZIP，再檢查輸入或選用模式。" }
            } finally {
                gate.finish(ticket)
                runOnUiThread { refresh() }
            }
        }
    }

    private fun compare() {
        val selected = source ?: return
        val plan = ReplayPlan(if (mode.selectedItemPosition == 0) ReplayMode.IMAGE else ReplayMode.VIDEO,
                              if (delegate.selectedItemPosition == 0) ReplayDelegate.CPU else ReplayDelegate.GPU)
        reportFile = null
        status.text = "開始 ${plan.delegate}／${plan.mode} 比較；不使用相機或網路。"
        work { ticket ->
            val report = ReplayRunner.run(selected, plan, gate, ticket,
                factory = { model, settings -> AndroidReplayInference(applicationContext, model, settings) },
                progress = { model, index, count -> ui(ticket) { status.text = "${model.name}：$index／$count" } })
            report.put("runtime", androidReplayRuntime(applicationContext))
            val directory = File(noBackupFilesDir, "replay-reports").apply { check(isDirectory || mkdirs()) }
            val pending = File(directory, "${UUID.randomUUID()}.pending")
            val destination = File(directory, "replay-${report.getString("runId")}.json")
            try {
                pending.writeText(report.toString(), Charsets.UTF_8)
                if (!gate.publish(ticket) {
                    check(!destination.exists() && pending.renameTo(destination))
                    reportFile = destination
                }) throw ReplayCancelled()
            } finally { if (pending.exists()) pending.delete() }
            val cases = report.getJSONArray("cases")
            val completed = (0 until cases.length()).count { cases.getJSONObject(it).getString("status") == "completed" }
            ui(ticket) { status.text = "本輪已結束：$completed／2 個模型完成。可匯出 JSON；失敗項目有獨立記錄。" }
        }
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        val uri = data?.data ?: return
        if (resultCode != RESULT_OK) return
        if (requestCode == IMPORT) {
            source = null; reportFile = null; status.text = "正在核對 ZIP 與所有影像配對。"
            work { ticket ->
                val bytes = requireNotNull(contentResolver.openInputStream(uri)).use { input ->
                    val output = ByteArrayOutputStream()
                    val buffer = ByteArray(8192)
                    while (true) {
                        if (!gate.current(ticket)) throw ReplayCancelled()
                        val count = input.read(buffer)
                        if (count < 0) break
                        require(output.size().toLong() + count <= ReplayArchive.MAX_ZIP_BYTES)
                        output.write(buffer, 0, count)
                    }
                    output.toByteArray()
                }
                val imported = ReplayArchive.read(bytes) { !gate.current(ticket) }
                if (!gate.publish(ticket) { source = imported }) throw ReplayCancelled()
                ui(ticket) { status.text = "已核對 ${imported.frames.size} 張同影格圖片。尚未開始推論。" }
            }
        } else if (requestCode == EXPORT) {
            val completed = reportFile ?: return
            work { ticket ->
                requireNotNull(contentResolver.openOutputStream(uri, "w")).use { out ->
                    completed.inputStream().use { input ->
                        val buffer = ByteArray(8192)
                        while (true) {
                            if (!gate.current(ticket)) throw ReplayCancelled()
                            val count = input.read(buffer)
                            if (count < 0) break
                            out.write(buffer, 0, count)
                        }
                    }
                }
                ui(ticket) { status.text = "已匯出回放結果 JSON；沒有匯出圖片。" }
            }
        }
    }

    override fun onStop() {
        gate.cancel(); uiGeneration = -1
        if (::status.isInitialized && gate.busy()) status.text = "已要求停止；等待處理資源關閉。"
        super.onStop()
    }
    override fun onResume() { super.onResume(); refresh() }
    override fun onDestroy() { gate.cancel(); worker.shutdown(); super.onDestroy() }
    companion object { private const val IMPORT = 101; private const val EXPORT = 102 }
}
